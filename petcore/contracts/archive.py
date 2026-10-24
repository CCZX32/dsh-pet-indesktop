"""远程功能包的资源预算契约（只依赖标准库）。

预算**只作用于市场分发通道的 feature 包**：本地目录 / ZIP 安装（`mods.install`）
保持零预算，角色 / content 包也不套这组数值。三个上限都是硬上限——读流与解包
过程中持续计数，越界立即失败；不信 ZIP 条目声明，也不信 HTTP 的 `Content-Length`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: 市场 feature 包默认预算：压缩 64 MiB / 展开 256 MiB / 10000 个条目（目录也计数）。
MARKET_ARCHIVE_LIMITS_BYTES = (64 * 1024 * 1024, 256 * 1024 * 1024, 10_000)


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """一组不可变预算。任何字段都必须为正整数。"""

    compressed_bytes: int
    expanded_bytes: int
    entries: int

    def __post_init__(self) -> None:
        for name in ("compressed_bytes", "expanded_bytes", "entries"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be int, got {type(value).__name__}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")

    def allows(
        self, *, compressed: int = 0, expanded: int = 0, entries: int = 0
    ) -> bool:
        """三个维度都在预算内才为真（等于上限算通过）。"""
        return (
            int(compressed) <= self.compressed_bytes
            and int(expanded) <= self.expanded_bytes
            and int(entries) <= self.entries
        )


class BudgetExceeded(RuntimeError):
    """预算越界。``kind`` ∈ ``compressed`` / ``expanded`` / ``entries``。"""

    def __init__(self, kind: str, limit: int, actual: int) -> None:
        self.kind = str(kind)
        self.limit = int(limit)
        self.actual = int(actual)
        super().__init__(f"{self.kind} budget exceeded: {self.actual} > {self.limit}")


#: 市场通道的默认预算实例（数值见 :data:`MARKET_ARCHIVE_LIMITS_BYTES`）。
MARKET_ARCHIVE_LIMITS = ArchiveLimits(*MARKET_ARCHIVE_LIMITS_BYTES)


class ArchiveOrigin(str, Enum):
    """解包来源，用于决定是否自动套用市场功能包预算。"""

    MARKET = "market"
    LOCAL = "local"
    BUNDLED = "bundled"


def _tighten_limits(explicit: ArchiveLimits, ceiling: ArchiveLimits) -> ArchiveLimits:
    """只收紧预算，不允许显式参数绕过远程功能包上限。"""
    return ArchiveLimits(
        min(explicit.compressed_bytes, ceiling.compressed_bytes),
        min(explicit.expanded_bytes, ceiling.expanded_bytes),
        min(explicit.entries, ceiling.entries),
    )


def effective_archive_limits(
    origin: ArchiveOrigin | str,
    kind: str,
    explicit_limits: ArchiveLimits | None = None,
) -> ArchiveLimits | None:
    """返回本次解包真正使用的预算。

    市场来源的 ``feature`` 包始终受市场硬上限约束；显式预算只能更严格。
    其他来源/类型不自动套用市场预算，保留调用方显式传入的测试或策略限制。
    """
    try:
        normalized_origin = ArchiveOrigin(origin)
    except ValueError:
        normalized_origin = ArchiveOrigin.LOCAL
    if normalized_origin is ArchiveOrigin.MARKET and str(kind).strip().lower() == "feature":
        return (
            MARKET_ARCHIVE_LIMITS
            if explicit_limits is None
            else _tighten_limits(explicit_limits, MARKET_ARCHIVE_LIMITS)
        )
    return explicit_limits
