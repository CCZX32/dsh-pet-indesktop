"""CPU / 内存采样（零 Qt）：psutil 差分 + 定宽文案 + 后台采样线程。

移植自主分支 ``pet/sys_monitor.py``，**砍掉 GPU 分支**（PDH 读数器与订阅账本留给
后续批次）：本批设备槽只有 CPU 与内存两段。

纪律：

- **首拍不伪造数据**：``psutil.cpu_percent(interval=None)`` 首次调用没有参照区间，
  所以经 :class:`CpuMeter` 走——首拍返回 None（段按 ``sampling`` 渲染 ``--``）。
- **只许在采样线程里调 syscall**：GUI 线程只读快照。
- 间隔硬上限 1 Hz（传更快会被夹回来），这是不可配的规格约束。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: 采样间隔口径：夹在 [1.0, 60.0] 秒（1 Hz 是上限，不可更快）。
DEFAULT_INTERVAL_SECONDS = 1.0
MIN_INTERVAL_SECONDS = 1.0
MAX_INTERVAL_SECONDS = 60.0
#: 字段盒的测宽样本（最坏形态 ``888%``）——盒宽由它定死，读数只在盒内伸缩。
MAX_TEXT = "888%"
#: 无读数时的占位文案（与 ``island.segments.UNKNOWN_TEXT`` 同一口径）。
UNKNOWN_TEXT = "--"
#: 采样线程名（排查线程泄漏时按它找）。
THREAD_NAME = "petcore-sys-monitor"


class PsutilUnavailable(RuntimeError):
    """psutil 不可用（未安装 / 导入失败）——读数不可用，不是 0。"""


def clamp_interval(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INTERVAL_SECONDS
    if number != number:  # NaN
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, number))


def _psutil():
    try:
        import psutil
    except Exception as exc:  # pragma: no cover - 环境缺 psutil 时走这里
        raise PsutilUnavailable(f"psutil 不可用：{exc}") from exc
    return psutil


def read_cpu_percent() -> float:
    """系统级 CPU 占用百分比（``interval=None`` 差分口径；只许在采样线程里调）。"""
    return float(_psutil().cpu_percent(interval=None))


def read_mem_percent() -> float:
    """物理内存占用百分比（同上）。"""
    return float(_psutil().virtual_memory().percent)


def format_cpu(percent: Any) -> str:
    """CPU 占用 → ``"24%"``；无读数 / 非数字 → ``"--"``。"""
    return _format_percent(percent)


def format_mem(percent: Any) -> str:
    """内存占用 → ``"61%"``；无读数 / 非数字 → ``"--"``。"""
    return _format_percent(percent)


def _format_percent(percent: Any) -> str:
    """取整是刻意的：小数会让盒内数字每秒抖，宽度由字段盒兜住。"""
    if percent is None:
        return UNKNOWN_TEXT
    try:
        number = float(percent)
    except (TypeError, ValueError):
        return UNKNOWN_TEXT
    if number != number:  # NaN
        return UNKNOWN_TEXT
    return f"{number:.0f}%"


class CpuMeter:
    """``psutil.cpu_percent(interval=None)`` 的差分语义封装（首拍只建基线）。"""

    def __init__(self, reader=read_cpu_percent) -> None:
        self._reader = reader
        self._primed = False

    @property
    def primed(self) -> bool:
        return self._primed

    def reset(self) -> None:
        self._primed = False

    def sample(self) -> float | None:
        value = self._reader()
        if self._primed:
            return value
        self._primed = True
        return None


@dataclass(frozen=True)
class SysSample:
    """一拍系统读数；``None`` 表示该项还不可用（首拍 / 采样失败）。"""

    cpu_percent: float | None = None
    mem_percent: float | None = None
    error: str = ""
    sampled_at: float = 0.0
    detail: dict = field(default_factory=dict)


class SysMonitor:
    """后台采样线程：CPU + 内存共享一份快照，GUI 只 ``snapshot()``。"""

    def __init__(
        self,
        *,
        interval=1.0,
        cpu_reader=read_cpu_percent,
        mem_reader=read_mem_percent,
    ) -> None:
        self.interval = clamp_interval(interval)
        self._meter = CpuMeter(cpu_reader)
        self._mem_reader = mem_reader
        self._lock = threading.Lock()
        self._latest = SysSample()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=THREAD_NAME, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def snapshot(self) -> SysSample:
        with self._lock:
            return self._latest

    def poll(self) -> SysSample:
        """同步采一拍（测试与小间隔心跳用）。"""
        cpu = None
        error = ""
        try:
            cpu = self._meter.sample()
        except PsutilUnavailable as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - 读数失败只降级
            error = f"{type(exc).__name__}: {exc}"
        mem = None
        if not error:
            try:
                mem = float(self._mem_reader())
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
        sample = SysSample(
            cpu_percent=cpu,
            mem_percent=mem,
            error=error,
            sampled_at=time.time(),
        )
        with self._lock:
            self._latest = sample
        return sample

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - 采样线程不许死
                logger.debug("sys poll failed", exc_info=True)
