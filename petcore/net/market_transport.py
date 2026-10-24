"""市场 artifact 的下载入口（契约实现；逐跳加固见 T02）。

分工：
- 契约在 ``petcore/contracts/http.py``（``TransferSpec``）与 ``contracts/archive.py``（预算）。
- 这里只负责把 spec 变成磁盘上的一个文件；压缩预算在读流中立即生效。
- 大小与 SHA-256 的最终校验属于 ``petcore/market/verify.py``，传输层不重复判。
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from ..contracts.archive import ArchiveLimits, BudgetExceeded
from ..contracts.http import ResumePolicy, TransferReport, TransferSpec
from ..market.errors import TransferCancelled
from . import market as _market

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_CHUNK_BYTES = 256 * 1024


def _file_path(url: str) -> Path:
    parts = urlsplit(url)
    raw_path = urllib.request.url2pathname(parts.path)
    if parts.netloc and parts.netloc.lower() not in {"", "localhost"}:
        raw_path = f"//{parts.netloc}{raw_path}"
    return Path(raw_path)


def local_file_root_for_index(url: str) -> Path | None:
    """Return the directory authorized by an explicit ``file://`` index.

    URL parsing stays inside the network boundary so market/UI layers do not
    import ``urllib`` directly.  Non-file origins deliberately return ``None``.
    """
    parts = urlsplit(str(url))
    if parts.scheme.lower() != "file":
        return None
    return _file_path(str(url)).resolve().parent


def _is_within(root: Path, target: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _local_error(message: str) -> _market.errors.NetworkError:
    return _market.errors.NetworkError(message, reason=_market.errors.PROTOCOL)


def _fetch_local_file(
    spec: TransferSpec,
    dest_dir: Path,
    url: str,
    limits: ArchiveLimits | None,
    *,
    progress=None,
    cancel=None,
) -> TransferReport:
    """读取已获明确授权的 ``file://`` artifact，并以有界流原子落盘。"""
    parts = urlsplit(url)
    if parts.scheme.lower() != "file":
        raise _local_error("本地文件分支收到非 file 协议")
    if not spec.allow_local_file or "file" not in {
        str(item).lower() for item in spec.allowed_schemes
    }:
        raise _local_error("未显式授权 file:// artifact")
    if not spec.local_root:
        raise _local_error("file:// artifact 缺少本地授权根目录")
    source = _file_path(url)
    root = Path(spec.local_root)
    if not _is_within(root, source):
        raise _local_error("file:// artifact 超出授权根目录")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise _market.errors.NetworkError(
            f"本地文件不可读：{type(exc).__name__}", reason=_market.errors.NETWORK
        ) from exc
    if limits is not None and size > limits.compressed_bytes:
        raise BudgetExceeded("compressed", limits.compressed_bytes, size)

    name = source.name or "artifact.zip"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    partial = dest_dir / f"{name}.part"
    done = 0
    try:
        with source.open("rb") as src, partial.open("wb") as dst:
            while True:
                if cancel is not None and cancel():
                    raise TransferCancelled("download cancelled")
                block = src.read(_CHUNK_BYTES)
                if not block:
                    break
                done += len(block)
                if limits is not None and done > limits.compressed_bytes:
                    raise BudgetExceeded("compressed", limits.compressed_bytes, done)
                dst.write(block)
                if progress is not None:
                    progress(done, size)
        os.replace(partial, final)
    except TransferCancelled:
        partial.unlink(missing_ok=True)
        raise
    except BudgetExceeded:
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise _market.errors.NetworkError(
            f"本地文件读取失败：{type(exc).__name__}", reason=_market.errors.NETWORK
        ) from exc
    return TransferReport(url=url, bytes_read=done, path=str(final))


def _effective_schemes(spec: TransferSpec, url: str) -> tuple[str, ...]:
    """本机回环额外放行明文 http；网络跳转永不借此放行 file。"""
    schemes = tuple(
        str(item).lower()
        for item in spec.allowed_schemes
        if str(item).lower() != "file"
    )
    if spec.allow_loopback_http and "http" not in schemes:
        host = (urlsplit(url).hostname or "").lower()
        if host in _LOOPBACK_HOSTS:
            schemes = schemes + ("http",)
    return schemes


def _artifact_name(spec: TransferSpec) -> str:
    for url in spec.urls:
        name = Path(urlsplit(url).path).name
        if name:
            return name
    return "artifact.zip"


def fetch_artifact(
    spec: TransferSpec,
    dest_dir: Path,
    *,
    limits: ArchiveLimits | None = None,
    progress=None,
    cancel=None,
) -> TransferReport:
    """下载 artifact 到 ``dest_dir``，返回落盘路径与字节数。"""
    if not spec.urls:
        raise ValueError("TransferSpec.urls must not be empty")
    if cancel is not None and cancel():
        raise TransferCancelled("download cancelled")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    first = spec.urls[0]
    if urlsplit(first).scheme.lower() == "file":
        return _fetch_local_file(
            spec, dest_dir, first, limits, progress=progress, cancel=cancel
        )

    name = _artifact_name(spec)
    part = dest_dir / f"{name}.part"
    final = dest_dir / name
    if spec.resume is ResumePolicy.RESTART or getattr(spec.resume, "value", spec.resume) == ResumePolicy.RESTART.value:
        part.unlink(missing_ok=True)
    policy = _market.TransportPolicy(
        max_redirects=spec.max_redirects,
        allowed_schemes=_effective_schemes(spec, first),
        allowed_hosts=tuple(spec.allowed_hosts),
    )
    outcome = _market.download_with_outcome(
        first,
        part,
        expected_size=spec.expected_size,
        timeout=spec.timeout,
        progress=progress,
        cancel=cancel,
        policy=policy,
        max_bytes=limits.compressed_bytes if limits is not None else None,
    )
    os.replace(part, final)
    return TransferReport(
        url=outcome.url,
        bytes_read=outcome.bytes_written,
        path=str(final),
        resumed_from=outcome.resumed_from,
        redirects=outcome.redirects,
    )
