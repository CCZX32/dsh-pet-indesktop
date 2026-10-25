"""网络速率采样（零 Qt）：psutil 计数器差分 + EMA，产出定宽文案。

移植自主分支 ``pet/net_monitor.py``，**砍掉 UDP 延迟探测**（那需要 socket，而
core 的架构红线把网络库锁在 ``net/``）：本批网络段只报 ↓/↑ 速率。

定宽是刻意契约：胶囊宽度由文案宽度算出，速率位数每秒变化会让岛左右抖，所以
``format_rate`` 最多 5 列、``format_network_slot`` 按字段右对齐补齐。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..performance import runtime_metrics
from .sampling import SamplingLoop

logger = logging.getLogger(__name__)

#: 采样间隔：默认 1 秒，钳 [0.5, 60]（再快没有意义，psutil 计数器精度也撑不住）。
DEFAULT_INTERVAL_SECONDS = 1.0
MIN_INTERVAL_SECONDS = 0.5
MAX_INTERVAL_SECONDS = 60.0
#: 速率字段定宽（列）：``0B`` / ``812K`` / ``1.2M`` / ``941M`` 都塞得下。
RATE_FIELD_WIDTH = 5
#: EMA 系数：0.5 兼顾"看得见起落"与"不抽搐"。
EMA_ALPHA = 0.5
_UNKNOWN_LATENCY = "--"


def clamp_interval(value) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    if seconds != seconds:  # NaN
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds))


def _psutil():
    import psutil

    return psutil


def read_counters() -> tuple[float, float] | None:
    """累计字节数 ``(recv, sent)``；psutil 缺失或读取失败返回 None。"""
    try:
        counters = _psutil().net_io_counters()
    except Exception:  # noqa: BLE001 - 采样失败只降级，不影响桌宠
        logger.debug("net counters unavailable", exc_info=True)
        return None
    if counters is None:
        return None
    return float(counters.bytes_recv), float(counters.bytes_sent)


@dataclass(frozen=True)
class RateSample:
    down_bps: float
    up_bps: float


class NetRateMeter:
    """计数器差分 → 每秒速率（**纯计算**，时钟与读数都可注入，便于单测）。"""

    def __init__(self, *, reader=read_counters, clock=time.monotonic) -> None:
        self._reader = reader
        self._clock = clock
        self._last: tuple[float, float] | None = None
        self._last_at: float | None = None
        self._down = 0.0
        self._up = 0.0
        self._have_rate = False

    def reset(self) -> None:
        self._last = None
        self._last_at = None
        self._down = 0.0
        self._up = 0.0
        self._have_rate = False

    def sample(self) -> RateSample | None:
        """采样一次；第一拍只建立基线并返回 None（不伪造 0 速率）。"""
        counters = self._reader()
        if counters is None:
            return None
        now = self._clock()
        previous, previous_at = self._last, self._last_at
        self._last, self._last_at = counters, now
        if previous is None or previous_at is None:
            return None
        elapsed = max(0.05, now - previous_at)
        # 计数器回绕 / 换网卡：差值为负按 0 计（宁少不假）。
        down = max(0.0, (counters[0] - previous[0]) / elapsed)
        up = max(0.0, (counters[1] - previous[1]) / elapsed)
        # 第一个真实差值不平滑：EMA 从 0 起算会把它砍半，看上去像"刚启动网络很慢"。
        if self._have_rate:
            self._down = _ema(self._down, down)
            self._up = _ema(self._up, up)
        else:
            self._down, self._up = down, up
            self._have_rate = True
        return RateSample(down_bps=self._down, up_bps=self._up)


def _ema(previous: float, current: float, alpha: float = EMA_ALPHA) -> float:
    return previous * (1.0 - alpha) + current * alpha


def format_rate(bps) -> str:
    """字节/秒 → 紧凑单位，**最长 5 列**（``0B`` / ``812K`` / ``1.2M`` / ``941M``）。"""
    try:
        value = max(0.0, float(bps))
    except (TypeError, ValueError):
        value = 0.0
    if value < 1024:
        return f"{value:.0f}B"
    if value < 1024**2:
        return f"{value / 1024:.0f}K"
    if value < 100 * 1024**2:
        return f"{value / 1024**2:.1f}M"
    if value < 1024**3:
        return f"{value / 1024**2:.0f}M"
    if value < 100 * 1024**3:
        return f"{value / 1024**3:.1f}G"
    return f"{value / 1024**3:.0f}G"


def format_network_slot(down_bps, up_bps, latency_ms=None) -> str:
    """岛上网络槽的定宽文案，例如 ``↓  1.2M ↑   340K``。

    本批不测延迟（见模块 docstring），``latency_ms`` 只为与主分支的签名兼容保留：
    传了也按 ``--`` 占定宽位，不参与取值。
    """
    return (
        f"↓{format_rate(down_bps):>{RATE_FIELD_WIDTH}}"
        f" ↑{format_rate(up_bps):>{RATE_FIELD_WIDTH}}"
    )


#: 网络段盒宽样本：千兆满速这一**现实包络**（5 列全宽数字），读数在盒内右对齐伸缩。
NETWORK_BOX_SAMPLE = format_network_slot(1023 * 1024**2, 1023 * 1024**2)


@dataclass(frozen=True)
class NetSample:
    """一个采样周期的结果快照（GUI 线程只读它，不做任何 syscall）。"""

    down_bps: float
    up_bps: float
    sampled_at: float

    @property
    def text(self) -> str:
        return format_network_slot(self.down_bps, self.up_bps)


class NetMonitor:
    """后台采样线程：持有最新快照，GUI 只 ``snapshot()``。"""

    def __init__(self, *, interval=1.0, meter: NetRateMeter | None = None) -> None:
        self.interval = clamp_interval(interval)
        self._meter = meter or NetRateMeter()
        self._sampling = SamplingLoop[NetSample | None](
            name="island-net",
            interval=self.interval,
            read=self._read_sample,
            # Stateless injected meters used by synchronous callers need not
            # implement reset; the real NetRateMeter always does.
            reset=getattr(self._meter, "reset", None),
            empty=None,
            logger=logger,
        )

    def start(self) -> None:
        """Request sampling; retry next owner tick if an old worker is exiting."""
        self._sampling.start()

    def stop(self) -> None:
        """Cancel without waiting; a blocked reader may still be running()."""
        self._sampling.stop()

    def running(self) -> bool:
        return self._sampling.running()

    def wait_stopped(self, timeout: float = 2.0) -> bool:
        """Wait at most timeout seconds off the GUI thread; does not call stop."""
        return self._sampling.wait_stopped(timeout)

    def snapshot(self) -> NetSample | None:
        return self._sampling.snapshot()

    def poll(self) -> NetSample | None:
        """同步单步采样；后台线程仍存活时只返回缓存，不并发调用 reader。"""
        return self._sampling.poll()

    def _read_sample(self) -> NetSample | None:
        runtime_metrics.inc("network_samples")
        sample = self._meter.sample()
        if sample is None:
            return None
        return NetSample(
            down_bps=sample.down_bps, up_bps=sample.up_bps, sampled_at=time.time()
        )
