# -*- coding: utf-8 -*-
"""灵动岛「设备槽」（CPU / 内存）的**共享**采样核心（零 Qt，依赖全部可注入）。

一条后台守护线程喂两个段：CPU 与内存的读数来自同一份 psutil 快照，拆成两条
线程只是多一份 ~23ms 的 syscall 与一份竞态。取舍：

- **绝不在 GUI 线程采样**。先例见 ``pet/net_monitor.py``：psutil 单次调用本机
  实测 **23ms**（63 张网卡的表遍历）；CPU + 内存两次调用同理在几十毫秒量级，
  塞进 16ms 的动画帧预算就是把界面卡成幻灯片。GUI 侧只读一次快照。
- **1Hz 上限，不可配**。CPU/内存占用是秒级趋势量，更快的刷新只烧 CPU；且
  ``psutil.cpu_percent(interval=None)`` 的差分区间越短噪声越大（一个采样间隔
  内的抖动会被放大成满量程跳变）。所以 :func:`clamp_interval` 把下界钉在
  1.0s，``set_interval`` 只能放慢。
- **无订阅不采样**。段被禁用 / 岛不可见时订阅数归零，线程只空转计时，
  不产生任何 syscall——用户关掉指标段就该真的零开销。
- **诚实降级**。psutil 缺失或平台无此计数器时抛 :class:`PsutilUnavailable`
  （不是返回 0），采样线程把它收成 ``state="error"`` 的快照并带原因，
  段显示 ``--``、卡片写明为什么——``--`` 不伪造 0。
- **差分首样本为 None**。``cpu_percent(interval=None)`` 首次调用没有参照区间
  （恒 0），:class:`CpuMeter` 吃掉这一轮并报 None，绝不把 0 当"CPU 空闲"报出去。

线程纪律：``stop()`` 默认只置停止事件；``close()`` 做**有界** join（在途一次
采样 ~23ms，1s 预算足够；读数卡死时宁可放弃 join 也不吊死调用方）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from pet.island_segments import STATE_ERROR, STATE_OK

logger = logging.getLogger(__name__)

#: 采样间隔区间：下界 = 1Hz 硬上限（CPU/内存是秒级趋势量，不可配更快）。
MIN_INTERVAL_SECONDS = 1.0
MAX_INTERVAL_SECONDS = 60.0
DEFAULT_INTERVAL_SECONDS = 1.0
#: 最坏宽度样本：3 位数字 + 百分号（段的盒宽由它声明，见 ``island_segments``）。
MAX_TEXT = "888%"
#: 无读数时的占位文案（与 ``island_segments.UNKNOWN_TEXT`` 同一口径）。
UNKNOWN_TEXT = "--"

#: 采样线程名（收口断言与线程枚举用）。
THREAD_NAME = "pet-sys-monitor"


class PsutilUnavailable(RuntimeError):
    """psutil 不可用（未安装 / 导入失败）——读数不可用，不是 0。"""


def clamp_interval(value: Any) -> float:
    """``SysMonitor`` 的间隔口径：夹在 [1.0, 60.0] 秒，坏值回默认。

    1.0s 是**硬上限**（1Hz）：传更快只会被夹回来，这是不可配的规格约束。
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INTERVAL_SECONDS
    if number != number:  # NaN
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, number))


def _psutil():
    """惰性取 psutil 模块；不可用即抛（调用方据此报"读数不可用"，不吞成 0）。"""
    try:
        import psutil
    except Exception as exc:  # pragma: no cover - 环境缺 psutil 时走这里
        raise PsutilUnavailable(f"psutil 不可用：{exc}") from exc
    return psutil


def read_cpu_percent() -> float:
    """系统级 CPU 占用百分比（``interval=None`` 差分口径）。

    **只许在采样线程里调用**（单次调用毫秒级，见模块 docstring）。首调没有
    参照区间，所以调用方必须经 :class:`CpuMeter` 走——直接用它会把首调的 0
    当成"CPU 空闲"。
    """
    return float(_psutil().cpu_percent(interval=None))


def read_mem_percent() -> float:
    """物理内存占用百分比。同上，只许在采样线程里调用。"""
    return float(_psutil().virtual_memory().percent)


def format_cpu(percent: Any) -> str:
    """CPU 占用 → ``"24%"``；无读数 / 非数字 → ``"--"``。"""
    return _format_percent(percent)


def format_mem(percent: Any) -> str:
    """内存占用 → ``"61%"``；无读数 / 非数字 → ``"--"``。"""
    return _format_percent(percent)


def _format_percent(percent: Any) -> str:
    """百分比取整成字段盒文案。取整是刻意的：小数会让盒内数字每秒抖动，
    而行内宽度由字段盒兜住（超宽由 :func:`island_segments.format_field_box` 截断）。"""
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
    """``psutil.cpu_percent(interval=None)`` 的差分语义封装。

    首次成功读数只建立基线（psutil 自己那一轮没有参照区间，值恒 0），报 ``None``
    而不是伪造 0。**基线在"读数成功"之后才算建立**：首轮抛错时 psutil 并未消费
    它的基线，下一轮仍要再吃一次——否则会把 psutil 的第二轮前那个 0 当真实占用。
    """

    def __init__(self, reader=read_cpu_percent):
        self._reader = reader
        self._primed = False

    @property
    def primed(self) -> bool:
        return self._primed

    def reset(self) -> None:
        """重新建立基线（线程换代后用：新代的第一轮仍是 None）。"""
        self._primed = False

    def sample(self) -> float | None:
        value = self._reader()
        if self._primed:
            return value
        self._primed = True
        return None


# ---------------------------------------------------------------- 快照
@dataclass(frozen=True)
class SysSample:
    """一个采样周期的结果快照（GUI 线程只读它，不做任何 syscall）。

    ``state`` 用段契约的词表（``ok``/``error``）：``error`` 时两个读数字段都是
    None，``error_reason`` 带原因（卡片直接拿去显示）。``sampled_at`` 是采样
    时刻（``time.monotonic``）。
    """

    cpu_percent: float | None
    mem_percent: float | None
    sampled_at: float
    state: str = STATE_OK
    error_reason: str = ""


# ---------------------------------------------------------------- 采样线程
class SysMonitor:
    """后台守护线程：每 ``interval`` 秒读一次 CPU + 内存，只对订阅者说话。

    生命周期：调用方（灵动岛）在岛可见时 :meth:`start`、隐藏时 :meth:`stop`，
    段自己按显示与否 :meth:`subscribe` / :meth:`unsubscribe`——**订阅数为 0 时
    线程只空转，不产生任何 syscall**（关掉指标段就该真的零开销）。

    **代（generation）隔离**：与 ``pet/net_monitor.py`` 同一套纪律。``stop()``
    之后立刻 ``start()`` 时上一轮线程可能还卡在读数里，所以每轮自带 generation
    token 与独立的 :class:`CpuMeter`：旧代晚到的结果被丢弃，不会用更晚的时间戳
    盖掉新代快照；新一代第一轮也重新建基线（宁可少报一轮，不报错值）。
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        *,
        cpu_reader=read_cpu_percent,
        mem_reader=read_mem_percent,
        clock=time.monotonic,
        on_sample=None,
    ):
        self._interval = clamp_interval(interval)
        self._clock = clock
        self._cpu_reader = cpu_reader
        self._mem_reader = mem_reader
        self._on_sample = on_sample
        self._lock = threading.Lock()
        self._snapshot: SysSample | None = None
        self._subscribers: set[str] = set()
        self._generation, self._meter = self._new_generation()
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None

    # ------------------------------------------------------------ 状态
    @property
    def interval(self) -> float:
        return self._interval

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def snapshot(self) -> SysSample | None:
        """最近一次采样（还没跑完第一轮时返回 None）。线程安全。"""
        with self._lock:
            return self._snapshot

    def set_interval(self, interval: float) -> float:
        """运行中改采样间隔（即时生效，不重建线程）；返回值是夹过界的实际值。"""
        self._interval = clamp_interval(interval)
        return self._interval

    # ------------------------------------------------------------ 订阅
    def subscribe(self, key: str) -> int:
        """按稳定 key 订阅（段 id 就是天然的 key）；返回订阅后的计数。

        同 key 重复订阅不重复计数——否则段重建（值刷新导致的快照重建）会把
        计数越堆越高，退订一次也归不了零。"""
        with self._lock:
            self._subscribers.add(str(key))
            return len(self._subscribers)

    def unsubscribe(self, key: str) -> int:
        """退订；未订阅的 key 是 no-op（不抛、不把计数压成负数）。"""
        with self._lock:
            self._subscribers.discard(str(key))
            return len(self._subscribers)

    # ------------------------------------------------------------ 采样
    def _new_generation(self) -> tuple[object, CpuMeter]:
        """开一代新采样：token（身份）+ 独立 meter（基线不跨代）。"""
        return object(), CpuMeter(reader=self._cpu_reader)

    def _retire_generation(self) -> None:
        """换代：在途的旧代结果从此不再被接受（stop 时也走这里）。"""
        self._generation, self._meter = self._new_generation()

    def sample_once(self, now: float | None = None) -> SysSample:
        """同步采样一轮（当前代；线程循环与测试共用同一实现）。

        显式调用不查订阅数——调用方既然主动问，就给它一个样本。
        """
        return self._sample(self._generation, self._meter, now)

    def _sample(self, generation, meter: CpuMeter, now: float | None = None) -> SysSample:
        moment = self._clock() if now is None else float(now)
        try:
            cpu = meter.sample()
            sample = SysSample(
                cpu_percent=None if cpu is None else float(cpu),
                mem_percent=float(self._mem_reader()),
                sampled_at=moment,
                state=STATE_OK,
            )
        except Exception as exc:
            # 读数不可用 / 调用失败：收成 error 快照（而不是抛穿线程或报 0）。
            # 半份读数（CPU 有、内存没）不留：状态是 error，两个值都按"没有"算。
            logger.debug("设备槽：采样失败", exc_info=True)
            sample = SysSample(
                cpu_percent=None,
                mem_percent=None,
                sampled_at=moment,
                state=STATE_ERROR,
                error_reason=f"{type(exc).__name__}: {exc}",
            )
        self._publish(generation, sample)
        return sample

    def _publish(self, generation, sample: SysSample) -> bool:
        """发布一次采样；**只认当前代**（旧代晚到的结果直接丢弃）。"""
        with self._lock:
            if self._generation is not generation:
                return False
            self._snapshot = sample
        if callable(self._on_sample):
            try:
                self._on_sample(sample)
            except Exception:  # pragma: no cover - 回调是宿主注入面，异常不外溢
                logger.debug("设备槽：采样回调异常", exc_info=True)
        return True

    # ------------------------------------------------------------ 线程
    def start(self) -> bool:
        if self.running:
            return False
        # 每次 start 一份独立的停止事件 + 一代独立的 generation/meter：紧接着
        # stop→start（隐藏后马上显示）时，上一轮线程只认自己的事件（不会被新一轮
        # clear() 复活成第二条常驻线程），晚到的结果也会被 _publish 按代拒收。
        event = threading.Event()
        self._stop_event = event
        self._retire_generation()
        generation, meter = self._generation, self._meter
        self._thread = threading.Thread(
            target=self._run, args=(event, generation, meter),
            daemon=True, name=THREAD_NAME,
        )
        self._thread.start()
        return True

    def stop(self, *, wait: bool = False, timeout: float = 2.0) -> None:
        """置停止事件并换代；``wait=True`` 时**有界** join（测试 / 退出路径用）。"""
        event, self._stop_event = self._stop_event, None
        if event is not None:
            event.set()
        thread, self._thread = self._thread, None
        self._retire_generation()
        if wait and thread is not None:
            thread.join(timeout)

    def close(self) -> None:
        """停止线程并收口（有界 join：在途一次采样毫秒级，1s 预算足够）。

        读数卡死时宁可放弃 join（线程是 daemon，进程退出不受阻）也不吊死调用方。
        """
        self.stop(wait=True, timeout=1.0)

    def _run(self, stop: threading.Event, generation, meter: CpuMeter) -> None:
        while not stop.is_set() and self._stop_event is stop:
            started = self._clock()
            try:
                if self.subscriber_count > 0:  # 无订阅不采样：关掉的段零 syscall
                    self._sample(generation, meter)
            except Exception:  # pragma: no cover - _sample 已兜异常，这里是最后一道
                logger.exception("设备槽：采样异常（线程继续）")
            sleep = max(0.05, self._interval - (self._clock() - started))
            if stop.wait(sleep):
                break
