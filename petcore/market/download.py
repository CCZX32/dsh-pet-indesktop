"""artifact 下载编排：多 URL 回退、续传、大小与 SHA-256 校验。"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..contracts.archive import ArchiveLimits
from ..contracts.http import TransferSpec
from . import verify
from .errors import DownloadError, IntegrityError, TransferCancelled
from .model import MarketPackage, MarketVersion

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]

#: GitHub Release 下载会从 `github.com` 跳到这些 CDN 主机；逐跳校验靠这张显式名单。
GITHUB_ARTIFACT_HOSTS = (
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
)


class ArtifactFetcher(Protocol):
    def download(
        self,
        url: str,
        part_path: Path,
        *,
        expected_size: int | None = None,
        timeout: float = 15.0,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
    ) -> int:
        ...


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    url: str
    sha256: str
    attempts: tuple[str, ...] = ()


def download_dir(root: Path) -> Path:
    return Path(root) / "market" / "downloads"


def _part_path(directory: Path, package_id: str, version: str) -> Path:
    return directory / f"{package_id}-{version}.zip.part"


def _final_path(directory: Path, package_id: str, version: str) -> Path:
    return directory / f"{package_id}-{version}.zip"


def _state_path(directory: Path, package_id: str, version: str) -> Path:
    return directory / f"{package_id}-{version}.download.json"


def _write_state(path: Path, package: MarketPackage, version: MarketVersion) -> None:
    payload = {
        "package_id": package.id,
        "version": version.version,
        "size": version.size,
        "sha256": version.sha256.lower(),
    }
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _state_matches(path: Path, package: MarketPackage, version: MarketVersion) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return payload == {
        "package_id": package.id,
        "version": version.version,
        "size": version.size,
        "sha256": version.sha256.lower(),
    }


def _discard_resume_state(part: Path, state: Path) -> None:
    for path in (part, state):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _preserve_staged_part(staging: Path, part: Path) -> None:
    candidates = sorted(staging.glob("*.part"))
    if not candidates:
        return
    source = candidates[0]
    try:
        os.replace(source, part)
    except OSError:
        try:
            shutil.copyfile(source, part)
        except OSError:
            return


def download_artifact(
    fetcher: ArtifactFetcher,
    root: Path,
    package: MarketPackage,
    version: MarketVersion,
    *,
    limits: ArchiveLimits | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    timeout: float = 15.0,
    local_file_root: Path | None = None,
    allow_local_file: bool = False,
) -> DownloadResult:
    directory = download_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    part = _part_path(directory, package.id, version.version)
    final = _final_path(directory, package.id, version.version)
    state = _state_path(directory, package.id, version.version)
    attempts: list[str] = []

    if part.exists() and not _state_matches(state, package, version):
        _discard_resume_state(part, state)
    if part.exists():
        _write_state(state, package, version)

    if final.is_file():
        try:
            if verify.sha256_file(final) == version.sha256 and final.stat().st_size == version.size:
                state.unlink(missing_ok=True)
                return DownloadResult(path=final, url="cache", sha256=version.sha256)
        except OSError:
            pass
        try:
            final.unlink()
        except OSError:
            pass

    _write_state(state, package, version)
    for url in version.urls:
        try:
            size = _fetch_one(
                fetcher,
                url,
                part,
                directory,
                package,
                version,
                limits=limits,
                progress=progress,
                cancel=cancel,
                timeout=timeout,
                local_file_root=local_file_root,
                allow_local_file=allow_local_file,
            )
            if size != version.size:
                raise IntegrityError(f"大小不一致：期望 {version.size}，实际 {size}")
            digest = verify.sha256_file(part)
            if digest != version.sha256:
                raise IntegrityError("SHA-256 与索引不一致")
        except TransferCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 记录后尝试下一个源
            attempts.append(f"{url}: {type(exc).__name__}: {exc}")
            if isinstance(exc, IntegrityError):
                _discard_resume_state(part, state)
            continue
        try:
            os.replace(part, final)
        except OSError as exc:
            attempts.append(f"{url}: 写入下载目录失败：{exc}")
            continue
        try:
            state.unlink(missing_ok=True)
        except OSError:
            pass
        return DownloadResult(
            path=final, url=url, sha256=version.sha256, attempts=tuple(attempts)
        )

    detail = "；".join(attempts) or "没有可用的下载地址"
    raise DownloadError(f"{package.id} {version.version} 下载失败：{detail}")


def _fetch_one(
    fetcher: ArtifactFetcher,
    url: str,
    part: Path,
    directory: Path,
    package: MarketPackage,
    version: MarketVersion,
    *,
    limits: ArchiveLimits | None,
    progress: ProgressCallback | None,
    cancel: CancelCallback | None,
    timeout: float,
    local_file_root: Path | None,
    allow_local_file: bool,
) -> int:
    """优先走逐跳加固的 `fetch`（T02）；测试替身只实现 `download` 时保持旧路径。"""
    fetch = getattr(fetcher, "fetch", None)
    if callable(fetch):
        spec = TransferSpec(
            urls=(url,),
            expected_size=version.size,
            allowed_hosts=GITHUB_ARTIFACT_HOSTS,
            timeout=timeout,
            allowed_schemes=("https", "http", "file")
            if allow_local_file
            else ("https", "http"),
            allow_local_file=allow_local_file,
            local_root=str(local_file_root) if local_file_root is not None else None,
        )
        staging = directory / f".fetch-{package.id}-{version.version}"
        staging.mkdir(parents=True, exist_ok=True)
        # HttpFetcher uses the URL basename. Seed that transient name from the
        # stable package/version part so cancellation can resume without losing it.
        if part.is_file():
            name = Path(url.split("?", 1)[0].rstrip("/")).name or "artifact.zip"
            staged_part = staging / f"{name}.part"
            if not staged_part.exists():
                shutil.copyfile(part, staged_part)
        try:
            report = fetch(
                spec, staging, limits=limits, progress=progress, cancel=cancel
            )
            os.replace(report.path, part)
        except Exception:
            # Preserve only the resumable bytes; do not leave a Qt/network staging
            # tree that can be mistaken for an installable artifact.
            _preserve_staged_part(staging, part)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return part.stat().st_size
    return fetcher.download(
        url,
        part,
        expected_size=version.size,
        timeout=timeout,
        progress=progress,
        cancel=cancel,
    )
