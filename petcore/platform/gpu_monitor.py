"""GPU 占用采样器（零 Qt）：单读线程 + 最新快照，形状与 :class:`~petcore.platform.sysmon.SysMonitor` 一致。

读数口径与失败面全在 :mod:`petcore.platform.gpu`（纯数据源）：本模块只负责"什么时候
采"和"把哪一拍给 GUI 看"。三条纪律：

- **间隔硬下界 1.0s**：GPU 占用是秒级趋势量，更快的采样没有意义且浪费电；传入更快
  只会被 :func:`clamp_interval` 夹回来。
- **syscall 只在采样线程里**：GUI 线程只 ``snapshot()`` 读缓存。PDH query 属于创建它的
  线程，所以 :meth:`GpuMonitor.poll` 的同步单步采样同样"谁调谁付账"（调用线程就是
  那一拍的 owner）。
- **query 跨 start/stop 复用**：``SamplingLoop`` 没有"线程退出前"的钩子，stop 之后那只
  query 由下一任 worker 线程接管（:class:`~petcore.platform.gpu.GpuReader` 只在 owner
  线程已退出时允许接管，并重建基线）。因此每只 monitor 最多一只 query，不随
  start/stop 次数增长；停采期间只是不再 collect，不销毁重建（重建要再付一次注册成本）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..performance import runtime_metrics
from . import gpu
from .gpu import GpuReader, GpuSample
from .sampling import SamplingLoop

logger = logging.getLogger(__name__)

#: 采样间隔口径：夹在 [1.0, 60.0] 秒（1 Hz 是上限，不可更快）。
DEFAULT_INTERVAL_SECONDS = 1.0
MIN_INTERVAL_SECONDS = 1.0
MAX_INTERVAL_SECONDS = 60.0
#: 采样线程名（排查线程泄漏时按它找）。
THREAD_NAME = "petcore-gpu-monitor"


def clamp_interval(value: Any) -> float:
    """间隔口径：坏值回默认，其余夹进 [1.0, 60.0]。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INTERVAL_SECONDS
    if number != number:  # NaN
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, number))


def idle_sample() -> GpuSample:
    """还没采过任何一拍的占位样本：``sampling`` + ``percent=None``（不是 0）。

    ``sampled_at=0`` 是"没有时间戳"，呈现层按未更新处理。
    """
    return GpuSample(percent=None, sampled_at=0.0, state=gpu.STATE_SAMPLING)


class GpuMonitor:
    """后台采样线程：持有最新 :class:`GpuSample`，GUI 只 ``snapshot()``。"""

    def __init__(self, *, interval: Any = 1.0, reader: GpuReader | None = None) -> None:
        self.interval = clamp_interval(interval)
        self._reader = reader if reader is not None else GpuReader()
        self._sampling = SamplingLoop[GpuSample](
            name=THREAD_NAME,
            interval=self.interval,
            read=self._read_sample,
            # 不重建 query、也不清基线：基线何时作废由 GpuReader 按实际间隔自己判
            # （长停 > 5s 才算作废），代际切换本身不构成"基线过期"。
            reset=None,
            empty=idle_sample(),
            logger=logger,
        )

    def start(self) -> None:
        """请求采样；老 worker 还没退干净时按 ``SamplingLoop`` 的约定下一拍再调一次。"""
        self._sampling.start()

    def stop(self) -> None:
        """取消采样但不等线程退出（阻塞中的读数仍可能 ``running()`` 为真）。"""
        self._sampling.stop()

    def running(self) -> bool:
        return self._sampling.running()

    def wait_stopped(self, timeout: float = 2.0) -> bool:
        """在非 GUI 线程上等待收口；**不**调用 stop、也不消费 start 意图。"""
        return self._sampling.wait_stopped(timeout)

    def snapshot(self) -> GpuSample:
        """最新一拍的缓存（GUI 线程唯一该调的读取入口）。"""
        return self._sampling.snapshot()

    def poll(self) -> GpuSample:
        """同步单步采样；后台线程仍存活时只返回缓存，不并发调用 reader。

        **调用线程就是这一拍的 owner**：PDH query 还没建立时，首次 ``poll()`` 会在调用
        线程里付掉注册成本（实测约半秒），不要在 GUI 线程上用它做首拍。
        """
        return self._sampling.poll()

    def _read_sample(self) -> GpuSample:
        runtime_metrics.inc("gpu_samples")
        try:
            return self._reader.read()
        except Exception as exc:  # noqa: BLE001 - 采样失败只降级，不掉线程
            logger.debug("GPU 采集：读数抛异常", exc_info=True)
            return GpuSample(
                percent=None,
                sampled_at=time.monotonic(),
                state=gpu.STATE_ERROR,
                error_reason=f"{type(exc).__name__}: {exc}",
            )
