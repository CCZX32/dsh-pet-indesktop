"""轻量级 petcore 运行时计数器。

计数器只保存聚合数字，不采集用户内容、URL 或凭据。UI 和网络层可以在
不引入彼此依赖的情况下记录 cache、采样和合并更新的实际次数。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    cpu_samples: int = 0
    network_samples: int = 0
    ui_updates: int = 0
    coalesced_updates: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    disk_writes: int = 0
    network_requests: int = 0
    active_threads: int = 0


class PerformanceCounters:
    _FIELDS = tuple(PerformanceSnapshot.__dataclass_fields__)

    def __init__(self) -> None:
        self._lock = Lock()
        self._values = {name: 0 for name in self._FIELDS}

    def inc(self, name: str, value: int = 1) -> None:
        if name not in self._values:
            raise KeyError(name)
        with self._lock:
            self._values[name] += int(value)

    def snapshot(self) -> PerformanceSnapshot:
        with self._lock:
            return PerformanceSnapshot(**self._values)

    def reset(self) -> None:
        with self._lock:
            for name in self._values:
                self._values[name] = 0

    def set_active_threads(self, value: int) -> None:
        with self._lock:
            self._values["active_threads"] = max(0, int(value))


runtime_metrics = PerformanceCounters()


__all__ = ["PerformanceCounters", "PerformanceSnapshot", "runtime_metrics"]
