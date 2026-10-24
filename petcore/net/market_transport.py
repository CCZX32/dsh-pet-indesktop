"""市场 artifact 的下载入口（契约实现；逐跳加固见 T02）。

分工：
- 契约在 `petcore/contracts/http.py`（`TransferSpec`）与 `contracts/archive.py`（预算）。
- 这里只负责「把 spec 变成磁盘上的一个文件」，并做**下载后**的压缩体积复核。
- 大小与 SHA-256 的最终校验属于 `petcore/market/verify.py`，传输层不重复判。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from ..contracts.archive import ArchiveLimits, BudgetExceeded
from ..contracts.http import TransferReport, TransferSpec
from . import market as _market


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
    """下载 `spec.urls[0]` 到 `dest_dir`，返回落盘路径与字节数。

    `limits` 目前只在**下载完成后**复核压缩体积（T02 会把计数移进读流）。
    """
    if not spec.urls:
        raise ValueError("TransferSpec.urls must not be empty")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _artifact_name(spec)
    part = dest_dir / f"{name}.part"
    final = dest_dir / name
    existing = part.stat().st_size if part.is_file() else 0
    url = spec.urls[0]
    written = _market.download_to(
        url,
        part,
        expected_size=spec.expected_size,
        timeout=spec.timeout,
        progress=progress,
        cancel=cancel,
    )
    if limits is not None and written > limits.compressed_bytes:
        part.unlink(missing_ok=True)
        raise BudgetExceeded("compressed", limits.compressed_bytes, written)
    os.replace(part, final)
    return TransferReport(
        url=url,
        bytes_read=written,
        path=str(final),
        resumed_from=existing,
    )
