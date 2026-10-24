"""市场 artifact 的下载入口（契约实现；逐跳加固见 T02）。

分工：
- 契约在 `petcore/contracts/http.py`（`TransferSpec`）与 `contracts/archive.py`（预算）。
- 这里只负责「把 spec 变成磁盘上的一个文件」；压缩预算在**读流中**立即生效。
- 大小与 SHA-256 的最终校验属于 `petcore/market/verify.py`，传输层不重复判。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from ..contracts.archive import ArchiveLimits
from ..contracts.http import ResumePolicy, TransferReport, TransferSpec
from . import market as _market

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _effective_schemes(spec: TransferSpec, url: str) -> tuple[str, ...]:
    """本机回环额外放行明文 http（本地镜像/测试）；其余只看 spec 白名单。"""
    schemes = tuple(spec.allowed_schemes)
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
    """下载 `spec.urls[0]` 到 `dest_dir`，返回落盘路径与字节数。

    - **压缩预算**：给了 `limits` 时，`limits.compressed_bytes` 在**读流中**按实际
      读到的字节累计（含已有 `.part`），一超上限就抛 `BudgetExceeded` 并删除
      `.part`，不依赖 `Content-Length`。
    - **续传口径**：只有 206 的 `Content-Range` 起点等于本地 `.part` 长度才真正
      追加；区间缺失/畸形/起点不符会丢弃 `.part` 从 0 重下，此时
      `TransferReport.resumed_from == 0`，表示本次没有沿用任何已有字节。
    - **取消**：取消时 `.part` **保留**（已写字节可用于下次续传），不截断、不删除。
    """
    if not spec.urls:
        raise ValueError("TransferSpec.urls must not be empty")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _artifact_name(spec)
    part = dest_dir / f"{name}.part"
    final = dest_dir / name
    if spec.resume is ResumePolicy.RESTART:
        part.unlink(missing_ok=True)
    policy = _market.TransportPolicy(
        max_redirects=spec.max_redirects,
        allowed_schemes=_effective_schemes(spec, spec.urls[0]),
        allowed_hosts=tuple(spec.allowed_hosts),
    )
    outcome = _market.download_with_outcome(
        spec.urls[0],
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
