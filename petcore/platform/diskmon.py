"""灵动岛「磁盘剩余」段的后台采样（零 Qt，只在采样线程里做一次 syscall）。

口径：

- **读的是剩余量，不是占用率**：C 盘还剩多少是用户真正想看的数字；占用率已被
  ``mem`` 段的百分比语义占住，混在一起会被误读。
- **只用 stdlib**：``shutil.disk_usage`` 在 Windows 上就是 ``GetDiskFreeSpaceEx``，
  不产生磁盘 IO、没有新依赖，单次调用微秒级。
- **5 秒一拍**：可用空间是分钟级变化，1Hz 纯浪费电；岛的 1Hz 心跳只读缓存快照，
  5 秒陈旧无感。
- **读不到就报错，绝不写 0**：``0G`` 会被当成「C 盘满了」，那是假读数。
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import time
from dataclasses import dataclass

from ..performance import runtime_metrics
from .sampling import SamplingLoop

logger = logging.getLogger("petcore.platform.disk")

#: 默认/最小/最大采样间隔（秒）。可用空间按分钟级变化，比这更快没有意义。
DEFAULT_INTERVAL_SECONDS = 5.0
MIN_INTERVAL_SECONDS = 5.0
MAX_INTERVAL_SECONDS = 60.0

#: 胶囊段盒宽样本（4 列）：读数在盒内伸缩，**永不改岛宽**。
FREE_FIELD_SAMPLE = "888G"

#: 读不到读数时的占位（与 cpu/mem 的 ``--`` 同口径）。
UNKNOWN_TEXT = "--"


def clamp_interval(value) -> float:
    """把采样间隔夹进 [5, 60]；非数字/NaN/∞ 一律回默认值。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    if not math.isfinite(seconds):
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds))


def volume_path() -> str:
    """要统计的卷：Windows 取系统盘（默认 C:），其他平台取根。"""
    drive = str(os.environ.get("SystemDrive") or "").strip()
    if os.name == "nt":
        return (drive or "C:") + "\\"
    return "/"


def format_size(num_bytes) -> str:
    """人读的容量（≤4 列）：``412G`` / ``1.8T`` / ``0.4G``。"""
    if num_bytes is None:
        return UNKNOWN_TEXT
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return UNKNOWN_TEXT
    if not math.isfinite(value) or value < 0.0:
        return UNKNOWN_TEXT
    if value <= 0.0:
        return "0G"
    tb = value / float(1024**4)
    # 0.975T 起一律走 T：否则 1000GiB 会渲染成 5 列的 "1000G"，把段盒撑破。
    # 两条 .0f 分支的门取 9.95（而不是 10.0）：否则 9.96T 会渲染成 "10.0T"（5 列）。
    if tb >= 9.95:
        return f"{tb:.0f}T"
    if tb >= 0.975:
        return f"{tb:.1f}T"
    gb = value / float(1024**3)
    if gb >= 9.95:
        return f"{gb:.0f}G"
    return f"{gb:.1f}G"


def format_free(free_bytes) -> str:
    """胶囊上的读数：与 :func:`format_size` 同口径，读不到给 ``--``。"""
    return format_size(free_bytes)


def read_usage(path: str | None = None) -> tuple[int | None, int | None, str]:
    """``(free, total, error)``：失败时前两项为 ``None``，第三项是原因。"""
    target = path or volume_path()
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return None, None, str(exc.strerror or type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - 任何读取失败都按 error 上报，不许崩线程
        return None, None, type(exc).__name__
    return int(usage.free), int(usage.total), ""


@dataclass(frozen=True)
class DiskSample:
    """一个采样周期的快照（GUI 线程只读它，不做任何 syscall）。"""

    free_bytes: int | None
    total_bytes: int | None
    sampled_at: float
    error: str = ""
    source: str = ""

    @property
    def text(self) -> str:
        return format_free(self.free_bytes)

    @property
    def note(self) -> str:
        """卡片明细：总量与已用；读不到就空串（原因走 ``error``）。"""
        if self.error or self.free_bytes is None or self.total_bytes is None:
            return ""
        used = max(0, int(self.total_bytes) - int(self.free_bytes))
        return f"总 {format_size(self.total_bytes)} · 已用 {format_size(used)}"


class DiskMonitor:
    """后台采样线程：持有最新快照，GUI 只 ``snapshot()``。"""

    def __init__(self, *, interval=DEFAULT_INTERVAL_SECONDS, reader=read_usage) -> None:
        self.interval = clamp_interval(interval)
        self._reader = reader
        self._source = volume_path()
        # `SamplingLoop.start()` 会把快照清成 empty，而下一次读要等一个完整间隔（5s）。
        # 折叠→展开、隐藏→显示都是最常见的解除停采动作，不许因此闪 5 秒 `--`：
        # 这里保留最后一份样本兜底（时间戳照旧，卡片仍能看出是旧值）。
        self._last: DiskSample | None = None
        self._sampling = SamplingLoop[DiskSample | None](
            name="petcore-disk-monitor",
            interval=self.interval,
            read=self._read_sample,
            reset=None,
            empty=None,
            logger=logger,
        )

    def start(self) -> None:
        """请求采样；旧 worker 还在退出时由 owner 下一拍重试。"""
        self._sampling.start()

    def stop(self) -> None:
        """发取消，不等线程（阻塞在 syscall 里的读不许卡 GUI）。"""
        self._sampling.stop()

    def running(self) -> bool:
        return self._sampling.running()

    def wait_stopped(self, timeout: float = 2.0) -> bool:
        return self._sampling.wait_stopped(timeout)

    def snapshot(self) -> DiskSample | None:
        return self._sampling.snapshot() or self._last

    def poll(self) -> DiskSample | None:
        return self._sampling.poll()

    def _read_sample(self) -> DiskSample:
        runtime_metrics.inc("disk_samples")
        free, total, error = self._reader(self._source)
        sample = DiskSample(
            free_bytes=free,
            total_bytes=total,
            sampled_at=time.time(),
            error=error,
            source=self._source,
        )
        self._last = sample
        return sample
