"""灵动岛的 GPU/FPS 探针接线。

平台探针（PDH 读数、PresentMon 子进程）都是零 Qt 的独立采样器，生命周期由
宿主按「岛现在还需要什么」来管：岛隐藏、段被关掉或被折进 ``+N`` 时立刻停采。
本模块只做三件事——启停、把平台样本翻译成段快照、把快照推给岛；不做采集，
也不碰 Qt 之外的平台细节。
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QObject, QTimer

from ..island import segments as isl
from ..performance import runtime_metrics

logger = logging.getLogger("petcore.ui.probes")

#: 段快照的定宽样本：模板宽只认它，读数与告警级不进宽度键。
GPU_BOX_TEXT = "100"
FPS_BOX_TEXT = "9999"
#: 探针读数推送节拍；采样器自己另有 1 Hz 硬下界，这里只读缓存快照。
PROBE_POLL_MS = 1000
#: FPS 没读数时重新解析前台目标的间隔（秒）。
FPS_TARGET_LOOKUP_SECONDS = 5.0


def _foreground_window_info():
    from ..platform.foreground import foreground_window_info

    try:
        return foreground_window_info()
    except Exception:  # noqa: BLE001 - 前台探测失败等于没有目标
        logger.debug("foreground lookup failed", exc_info=True)
        return None


def gpu_segment(sample) -> isl.SegmentSnapshot:
    """``GpuSample`` → 段快照。非 ``ok`` 一律 ``--`` + 具体原因，绝不写 0。"""
    import math

    percent = getattr(sample, "percent", None)
    ok = str(getattr(sample, "state", "")) == "ok" and isinstance(percent, (int, float))
    if ok and not math.isfinite(float(percent)):
        ok = False
    detail = dict(getattr(sample, "detail", {}) or {})
    detail.setdefault("unit", "%")
    reason = str(getattr(sample, "error_reason", "") or "")
    if not ok and reason:
        detail["error_reason"] = reason
    adapter = getattr(sample, "adapter", None)
    label = str(getattr(adapter, "name", "") or "")
    engine = getattr(getattr(adapter, "busiest", None), "engtype", "")
    if engine:
        label = f"{label} · {engine}" if label else str(engine)
    if label and "source" not in detail:
        detail["source"] = label
    return isl.SegmentSnapshot(
        isl.GPU,
        label="GPU",
        text=f"{float(percent):.0f}" if ok else "--",
        max_text=GPU_BOX_TEXT,
        state=isl.STATE_OK if ok else _state(getattr(sample, "state", "")),
        detail=detail,
    )


def fps_segment(sample) -> isl.SegmentSnapshot:
    """``FpsSample`` → 段快照。无目标/无权限/后端缺失都只写原因。"""
    fps = getattr(sample, "fps", None)
    ok = str(getattr(sample, "state", "")) == "ok" and isinstance(fps, (int, float))
    detail = dict(getattr(sample, "detail", {}) or {})
    detail.setdefault("unit", "fps")
    reason = str(getattr(sample, "error_reason", "") or "")
    if not ok and reason:
        detail["error_reason"] = reason
    target = str(getattr(sample, "target", "") or "")
    if target:
        detail.setdefault("source", target)
    text = "--"
    if ok:
        value = float(fps)
        text = f"{value:.0f}" if value < 10000 else "9999+"
    return isl.SegmentSnapshot(
        isl.FPS,
        label="帧率",
        text=text,
        max_text=FPS_BOX_TEXT,
        state=isl.STATE_OK if ok else _state(getattr(sample, "state", "")),
        detail=detail,
    )


def _state(value) -> str:
    text = str(value or "")
    return text if text in isl.STATES else isl.STATE_UNKNOWN


class IslandProbeHub(QObject):
    """按岛的「还需要哪些段」启停 GPU/FPS 采样器，并逐秒推送快照。"""

    def __init__(self, island, *, gpu_factory=None, fps_factory=None, parent=None) -> None:
        super().__init__(parent)
        self.island = island
        self._gpu_factory = gpu_factory
        self._fps_factory = fps_factory
        self._gpu = None
        self._fps = None
        self._last_target_lookup = 0.0
        self._wanted: frozenset[str] = frozenset()
        self._timer = QTimer(self)
        self._timer.setInterval(PROBE_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._closed = False

    def sync(self, wanted) -> None:
        """``wanted``：岛当前仍需要采样的段 id 集合（空集 = 全停）。"""
        if self._closed:
            return
        wanted = frozenset(str(item) for item in (wanted or ()))
        self._wanted = wanted
        self._sync_one(isl.GPU, wanted, "_gpu", self._gpu_factory)
        self._sync_one(isl.FPS, wanted, "_fps", self._fps_factory)
        # 采样器句柄停采后仍留着复用，所以「要不要轮询」只看需求集合，不看句柄。
        active = bool(wanted & {isl.GPU, isl.FPS})
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active and self._timer.isActive():
            self._timer.stop()
        if not active:
            # 停采就把段退回「未接入探针」的明确状态，别留着旧读数发霉。
            self.island.clear_probe_snapshot()

    def _sync_one(self, metric_id: str, wanted: frozenset[str], attr: str, factory) -> None:
        monitor = getattr(self, attr)
        if metric_id in wanted:
            if monitor is None and factory is not None:
                try:
                    monitor = factory()
                except Exception:  # noqa: BLE001 - 探针创建失败只影响这一段
                    logger.debug("probe factory failed: %s", metric_id, exc_info=True)
                    monitor = None
                setattr(self, attr, monitor)
            if monitor is not None:
                try:
                    monitor.start()
                except Exception:  # noqa: BLE001
                    logger.debug("probe start failed: %s", metric_id, exc_info=True)
            return
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:  # noqa: BLE001
                logger.debug("probe stop failed: %s", metric_id, exc_info=True)

    def _poll(self) -> None:
        if self._closed:
            return
        # 每拍调和一次：`start()` 在旧 worker 收口中时会被拒（返回 False），
        # 只靠 wanted 边沿触发就再也不重试了（审计 AUD-31）。
        self._reconcile()
        if self._gpu is not None:
            self._push(isl.GPU, gpu_segment, self._gpu.snapshot(), "gpu_samples")
        if self._fps is not None:
            self._retarget_fps()
            self._push(isl.FPS, fps_segment, self._fps.snapshot(), "fps_samples")

    def _reconcile(self) -> None:
        """按需求逐拍调和：只在监控器**没在跑**时才重试 start()。"""
        wanted = self._wanted
        if not wanted:
            return
        for metric_id, attr, factory in (
            (isl.GPU, "_gpu", self._gpu_factory),
            (isl.FPS, "_fps", self._fps_factory),
        ):
            if metric_id not in wanted:
                continue
            monitor = getattr(self, attr)
            running = getattr(monitor, "running", None)
            if monitor is not None and callable(running):
                try:
                    if running():
                        continue
                except Exception:  # noqa: BLE001 - 监控器自己的问题，不阻塞调和
                    pass
            self._sync_one(metric_id, wanted, attr, factory)

    def _retarget_fps(self) -> None:
        """FPS 段只看前台应用：没有目标或目标已退出时重新解析一次。

        解析用的是「前台窗口 pid」，一个 ``GetForegroundWindow`` + 一次 pid 查询，
        所以最多每 5 秒做一次，绝不在每拍都做。
        """
        probe = self._fps
        if probe is None or not hasattr(probe, "set_target"):
            return
        now = time.monotonic()
        if now - self._last_target_lookup < FPS_TARGET_LOOKUP_SECONDS:
            return
        sample = probe.snapshot()
        if getattr(sample, "state", "") == "ok":
            return
        self._last_target_lookup = now
        info = _foreground_window_info() or {}
        pid = info.get("pid")
        if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
            return
        name = str(info.get("process") or "")
        try:
            probe.set_target(pid, name)
        except Exception:  # noqa: BLE001 - 换目标失败只影响这一段
            logger.debug("fps retarget failed", exc_info=True)

    def _push(self, metric_id: str, convert, sample, counter: str) -> None:
        if sample is None:
            return
        try:
            snapshot = convert(sample)
        except Exception:  # noqa: BLE001 - 翻译失败不该拖垮岛
            logger.debug("probe snapshot convert failed: %s", metric_id, exc_info=True)
            return
        runtime_metrics.inc(counter)
        self.island.set_probe_snapshot(snapshot)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        for attr in ("_gpu", "_fps"):
            monitor = getattr(self, attr)
            if monitor is not None:
                try:
                    monitor.stop()
                except Exception:  # noqa: BLE001
                    logger.debug("probe shutdown failed: %s", attr, exc_info=True)


__all__ = ["IslandProbeHub", "fps_segment", "gpu_segment"]
