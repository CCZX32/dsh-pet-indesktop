"""artifact 下载编排：多 URL 回退、续传、大小与 SHA-256 校验。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..contracts.archive import MARKET_ARCHIVE_LIMITS, ArchiveLimits
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


def download_artifact(
    fetcher: ArtifactFetcher,
    root: Path,
    package: MarketPackage,
    version: MarketVersion,
    *,
    limits: ArchiveLimits | None = MARKET_ARCHIVE_LIMITS,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    timeout: float = 15.0,
) -> DownloadResult:
    directory = download_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    part = _part_path(directory, package.id, version.version)
    final = _final_path(directory, package.id, version.version)
    attempts: list[str] = []

    if final.is_file():
        try:
            if verify.sha256_file(final) == version.sha256 and final.stat().st_size == version.size:
                return DownloadResult(path=final, url="cache", sha256=version.sha256)
        except OSError:
            pass
        try:
            final.unlink()
        except OSError:
            pass

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
                try:
                    part.unlink()
                except OSError:
                    pass
            continue
        try:
            os.replace(part, final)
        except OSError as exc:
            attempts.append(f"{url}: 写入下载目录失败：{exc}")
            continue
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
) -> int:
    """优先走逐跳加固的 `fetch`（T02）；测试替身只实现 `download` 时保持旧路径。"""
    fetch = getattr(fetcher, "fetch", None)
    if callable(fetch):
        spec = TransferSpec(
            urls=(url,),
            expected_size=version.size,
            allowed_hosts=GITHUB_ARTIFACT_HOSTS,
            timeout=timeout,
        )
        staging = directory / f".fetch-{package.id}-{version.version}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            report = fetch(
                spec, staging, limits=limits, progress=progress, cancel=cancel
            )
            os.replace(report.path, part)
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
