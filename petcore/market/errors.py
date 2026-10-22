"""市场层错误：稳定分类，供 CLI、UI 与日志使用。"""

from __future__ import annotations


class MarketError(RuntimeError):
    """所有市场错误的基类。"""


class IntegrityError(MarketError):
    """大小或 SHA-256 与索引不一致。"""


class ManifestMismatch(MarketError):
    """包内 mod.json 与索引声明不一致。"""


class DownloadError(MarketError):
    """所有 URL 都失败。"""


class TransferCancelled(MarketError):
    """用户取消下载；``.part`` 保留以便续传。"""
