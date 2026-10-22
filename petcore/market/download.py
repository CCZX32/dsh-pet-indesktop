"""artifact 下载编排：多 URL 回退、续传、大小与 SHA-256 校验。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import verify
from .errors import DownloadError, IntegrityError, TransferCancelled
from .model import MarketPackage, MarketVersion

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


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
            size = fetcher.download(
                url,
                part,
                expected_size=version.size,
                timeout=timeout,
                progress=progress,
                cancel=cancel,
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
