"""灵动岛 GPU/FPS 探针接线的测试。

平台采集器一律用假对象：这里验的是启停闸门与样本翻译，不是 PDH/PresentMon。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from petcore.island import segments as isl
from petcore.platform.gpu import AdapterReading, EngineKey, EngineReading, GpuSample
from petcore.ui.island import DynamicIsland
from petcore.ui.probes import IslandProbeHub, fps_segment, gpu_segment


class _Config:
    def __init__(self, metrics):
        self.data = {
            "island_enabled": True,
            "island_metrics": list(metrics),
            "island_show_icon": True,
            "island_show_name": True,
            "island_show_status": True,
            "island_info_mode": "time",
            "island_custom_text": "",
            "island_style": "dark",
            "island_opacity": 1.0,
            "island_accent": "blue",
            "island_x": None,
            "island_y": None,
        }

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        pass


def _app():
    return QApplication.instance() or QApplication([])


class _FakeSample:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeMonitor:
    def __init__(self, sample):
        self.sample = sample
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def snapshot(self):
        return self.sample


def test_gpu_segment_keeps_readings_and_reasons_apart() -> None:
    ok = GpuSample(
        percent=24.0,
        sampled_at=1.0,
        state="ok",
        adapter=AdapterReading(
            luid="0", percent=24.0, name="测试显卡", busiest=EngineReading(EngineKey("0", 0, "3D"), 24.0, engtype="3D")
        ),
    )
    segment = gpu_segment(ok)
    assert (segment.id, segment.text, segment.max_text) == (isl.GPU, "24", "100")
    assert segment.state == isl.STATE_OK
    assert segment.detail["unit"] == "%"
    assert "测试显卡" in segment.detail["source"]

    missing = GpuSample(percent=None, sampled_at=1.0, state="error", error_reason="PDH 无数据")
    degraded = gpu_segment(missing)
    assert degraded.text == "--"
    assert degraded.state == isl.STATE_ERROR
    assert degraded.detail["error_reason"] == "PDH 无数据"


def test_fps_segment_formats_and_caps() -> None:
    assert fps_segment(_FakeSample(state="ok", fps=144.6)).text == "145"
    assert fps_segment(_FakeSample(state="ok", fps=12000)).text == "9999+"
    no_target = fps_segment(_FakeSample(state="unknown", fps=None, error_reason="没有可采集的目标"))
    assert no_target.text == "--"
    assert no_target.state == isl.STATE_UNKNOWN
    assert no_target.detail["error_reason"] == "没有可采集的目标"


def test_hub_starts_only_what_is_needed_and_clears_when_idle() -> None:
    _app()
    island = DynamicIsland(_Config(["cpu", "gpu", "fps"]))
    gpu = _FakeMonitor(GpuSample(percent=31.0, sampled_at=1.0, state="ok"))
    fps = _FakeMonitor(_FakeSample(state="ok", fps=60.0, detail={}))
    hub = IslandProbeHub(island, gpu_factory=lambda: gpu, fps_factory=lambda: fps)
    try:
        hub.sync({"gpu"})
        assert (gpu.starts, fps.starts) == (1, 0)
        assert hub._timer.isActive()

        hub.sync({"gpu", "fps"})
        assert fps.starts == 1
        hub._poll()
        ids = {segment.seg_id for segment in island._row}
        assert isl.GPU in ids and isl.FPS in ids

        hub.sync(set())
        assert (gpu.stops, fps.stops) == (1, 1)
        assert not hub._timer.isActive()
        assert not any(segment.seg_id in (isl.GPU, isl.FPS) for segment in island._row)
    finally:
        hub.shutdown()
        island.deleteLater()


def test_island_asks_the_host_for_exactly_the_visible_unfolded_probes() -> None:
    _app()
    config = _Config(["gpu"])
    island = DynamicIsland(config)
    wanted: list[frozenset[str]] = []
    island.set_probe_sync_callback(lambda ids: wanted.append(frozenset(ids)))
    try:
        island.show()
        island._sync_sampling()
        assert wanted[-1] == frozenset({isl.GPU})

        config.set("island_metrics", ["cpu"])
        island.refresh_from_config()
        island._sync_sampling()
        assert wanted[-1] == frozenset()

        island.hide()
        island._sync_sampling()
        assert wanted[-1] == frozenset()
    finally:
        island.hide()
        island.deleteLater()


def test_hub_retries_a_refused_start_on_the_next_poll() -> None:
    """start() 在旧 worker 收口中时会被拒；只靠 wanted 边沿就再也不重试（AUD-31）。"""
    _app()

    class _Refusing(_FakeMonitor):
        def __init__(self, sample):
            super().__init__(sample)
            self.refusals = 1

        def start(self):
            if self.refusals > 0:
                self.refusals -= 1
                return False
            super().start()
            return True

    island = DynamicIsland(_Config(["cpu", "gpu"]))
    gpu = _Refusing(GpuSample(percent=12.0, sampled_at=1.0, state="ok"))
    hub = IslandProbeHub(island, gpu_factory=lambda: gpu, fps_factory=None)
    try:
        hub.sync({"gpu"})
        assert gpu.starts == 0, "第一次启动被拒"
        hub._poll()  # noqa: SLF001 - 调和节拍就是 poll
        assert gpu.starts == 1, "下一拍必须重试并成功"
    finally:
        hub.shutdown()


def test_expanding_the_card_does_not_thrash_the_probes(app=None) -> None:
    """展开卡片不许把 GPU 采样推进「停→起」振荡（AUD-25）。"""
    _app()
    class _RunningFake(_FakeMonitor):
        def __init__(self, sample):
            super().__init__(sample)
            self._running = False

        def start(self):
            super().start()
            self._running = True

        def stop(self):
            super().stop()
            self._running = False

        def running(self):
            return self._running

    island = DynamicIsland(_Config(["cpu", "gpu"]))
    gpu = _RunningFake(GpuSample(percent=21.0, sampled_at=1.0, state="ok"))
    hub = IslandProbeHub(island, gpu_factory=lambda: gpu, fps_factory=None)
    try:
        island.set_probe_sync_callback(hub.sync)
        island.show()
        _app().processEvents()
        before = gpu.starts
        island.expand_card()
        _app().processEvents()
        for _ in range(3):
            hub._poll()  # noqa: SLF001 - 模拟每秒一次的推送
            _app().processEvents()
        assert gpu.stops == 0, f"卡片态不该停采（stops={gpu.stops}）"
        assert gpu.starts == before, "卡片态不该重新拉起采样"
    finally:
        hub.shutdown()
