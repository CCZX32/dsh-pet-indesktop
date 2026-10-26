"""petcore GPU 探针：不可用语义、状态归一、间隔钳制与真实读数。"""

from __future__ import annotations

import math
import sys
import threading
import time

import pytest

from petcore.platform import gpu, gpu_monitor

#: 真实实例名样本（文法与主分支探针实测一致：pid/luid/phys/eng/engtype）。
_INSTANCE_3D = "pid_%d_luid_0x00000000_0x%08X_phys_0_eng_%d_engtype_3D"


class _FakePdh:
    """最小 PDH 替身：两段式数组读取 + 可脚本化的状态码。"""

    def __init__(self, items=((_INSTANCE_3D % (1, 0x1111, 0), 42.0),)):
        self.items = [(name, gpu.PDH_CSTATUS_VALID_DATA, value) for name, value in items]
        self.opened = 0
        self.collects = 0
        self.closes = 0
        self.path = ""

    def open_query(self):
        self.opened += 1
        return "query"

    def add_counter(self, query, path):
        self.path = path
        return "counter"

    def collect(self, query):
        self.collects += 1

    def counter_array(self, counter, size=None):
        if size is None:
            bytes_needed = 24 * len(self.items)
            return gpu.PDH_MORE_DATA, bytes_needed, len(self.items), []
        return 0, 24 * len(self.items), len(self.items), list(self.items)

    def close_query(self, query):
        self.closes += 1


class _StubReader:
    """GpuMonitor 的读数缝：不做任何 syscall。"""

    def __init__(self, percent=7.0):
        self.percent = percent
        self.reads = 0
        self.sampled = threading.Event()

    def read(self):
        self.reads += 1
        self.sampled.set()
        return gpu.GpuSample(percent=self.percent, sampled_at=time.monotonic())


# ---------------------------------------------------------------- 不可用语义
def test_pdh_unavailable_reports_none_and_reason(monkeypatch):
    """load 失败（`_pdh` 空 + 已记录原因）不得回退成 0。"""
    monkeypatch.setattr(gpu, "_pdh", None)
    monkeypatch.setattr(gpu, "_pdh_error", "pdh.dll 装载失败（测试模拟）")
    sample = gpu.GpuReader().read()
    assert sample.percent is None
    assert sample.error_reason
    assert sample.state in {gpu.STATE_ERROR, gpu.STATE_UNSUPPORTED}
    assert sample.detail.get("error_reason") == sample.error_reason


def test_non_windows_is_unsupported(monkeypatch):
    monkeypatch.setattr(gpu, "_platform_supported", lambda: False)
    sample = gpu.GpuReader().read()
    assert sample.state == gpu.STATE_UNSUPPORTED
    assert sample.percent is None
    assert sample.error_reason


def test_first_sample_only_builds_baseline():
    """首拍只建基线：报 sampling，绝不把刚注册的速率计数器当读数。"""
    api = _FakePdh()
    reader = gpu.GpuReader(api=api, adapter_provider=dict)
    first = reader.read()
    assert first.state == gpu.STATE_SAMPLING
    assert first.percent is None
    second = reader.read()
    assert second.state == gpu.STATE_OK
    assert second.percent == 42.0
    assert api.path == gpu.COUNTER_PATH


# ---------------------------------------------------------------- 状态归一
def test_unknown_state_never_becomes_ok():
    assert gpu.normalize_state("ok") == gpu.STATE_OK
    assert gpu.normalize_state("SAMPLING") == gpu.STATE_SAMPLING
    assert gpu.normalize_state("weird") == gpu.STATE_ERROR
    assert gpu.normalize_state(None) == gpu.STATE_ERROR
    sample = gpu.GpuSample(percent=12.0, sampled_at=0.0, state="weird")
    assert sample.state == gpu.STATE_ERROR
    assert sample.percent is None
    assert sample.error_reason


def test_ok_without_finite_reading_is_downgraded():
    sample = gpu.GpuSample(percent=float("nan"), sampled_at=0.0)
    assert sample.state == gpu.STATE_ERROR
    assert sample.percent is None


def test_ok_reading_is_clamped_to_percent_range():
    assert gpu.GpuSample(percent=140.0, sampled_at=0.0).percent == 100.0
    assert gpu.GpuSample(percent=-4.0, sampled_at=0.0).percent == 0.0


# ---------------------------------------------------------------- 聚合口径
def test_engine_sum_then_adapter_max_then_busiest():
    """引擎级跨 pid 求和 → 适配器取 max → 跨适配器取 max（报最忙引擎，不是总算力）。"""
    items = [
        (_INSTANCE_3D % (1, 0x1111, 0), 30.0),
        (_INSTANCE_3D % (2, 0x1111, 0), 25.0),
        ("pid_1_luid_0x00000000_0x00001111_phys_0_eng_3_engtype_Video Decode", 40.0),
        (_INSTANCE_3D % (1, 0x2222, 0), 55.0),
        (_INSTANCE_3D % (1, 0x2222, 0), float("nan")),
        ("garbage", 99.0),
    ]
    engines = gpu.group_engines(items)
    assert [(e.key.luid, e.key.eng, e.percent, e.samples) for e in engines] == [
        ("0x00000000_0x00001111", 0, 55.0, 2),
        ("0x00000000_0x00001111", 3, 40.0, 1),
        ("0x00000000_0x00002222", 0, 55.0, 1),
    ]
    adapters = gpu.adapter_readings(engines)
    assert [(a.luid, a.percent) for a in adapters] == [
        ("0x00000000_0x00001111", 55.0),
        ("0x00000000_0x00002222", 55.0),
    ]
    best = gpu.busiest_adapter(adapters)
    assert best is not None and best.percent == 55.0

    known = {
        "0x00000000_0x00002222": gpu.AdapterInfo(
            luid="0x00000000_0x00002222", name="Microsoft Basic Render Driver",
            is_software=True),
    }
    assert [a.luid for a in gpu.adapter_readings(engines, known=known)] == [
        "0x00000000_0x00001111"
    ]


# ---------------------------------------------------------------- 线程纪律
def test_live_owner_thread_refuses_read_and_close():
    """owner 线程还活着时，跨线程 read/close 一律拒绝且不碰 PDH。"""
    api = _FakePdh()
    reader = gpu.GpuReader(api=api, adapter_provider=dict)
    started = threading.Event()
    release = threading.Event()
    outcome = {}

    def work():
        outcome["first"] = reader.read()
        started.set()
        release.wait(5.0)

    worker = threading.Thread(target=work, name="gpu-probe-owner")
    worker.start()
    try:
        assert started.wait(5.0)
        cross = reader.read()
        assert cross.state == gpu.STATE_ERROR
        assert cross.percent is None
        assert "创建它的线程" in cross.error_reason
        assert reader.close() is False
        assert api.closes == 0
    finally:
        release.set()
        worker.join(5.0)
    assert outcome["first"].state == gpu.STATE_SAMPLING


def test_dead_owner_thread_is_adopted_with_a_fresh_baseline():
    """owner 线程退出后由下一个采样线程接管同一只 query（不重开、不泄漏）。"""
    api = _FakePdh()
    reader = gpu.GpuReader(api=api, adapter_provider=dict)
    worker = threading.Thread(target=reader.read, name="gpu-probe-gone")
    worker.start()
    worker.join(10.0)
    assert api.opened == 1

    adopted = reader.read()
    assert adopted.state == gpu.STATE_SAMPLING   # 接管后的第一拍只重建基线
    assert api.opened == 1                       # 没有为接管再开第二只 query
    assert reader.read().state == gpu.STATE_OK


# ---------------------------------------------------------------- 采样器
def test_interval_is_clamped_to_one_second_floor():
    monitor = gpu_monitor.GpuMonitor(interval=0.1, reader=_StubReader())
    assert monitor.interval == 1.0
    assert gpu_monitor.clamp_interval(120) == 60.0
    assert gpu_monitor.clamp_interval("nonsense") == 1.0
    assert gpu_monitor.clamp_interval(float("nan")) == 1.0


def test_stop_is_idempotent_and_snapshot_never_fakes_zero():
    monitor = gpu_monitor.GpuMonitor(reader=_StubReader())
    monitor.stop()
    monitor.stop()
    assert monitor.running() is False
    sample = monitor.snapshot()
    assert sample.percent is None
    assert sample.state == gpu.STATE_SAMPLING


def test_monitor_publishes_then_stops():
    reader = _StubReader(percent=7.0)
    monitor = gpu_monitor.GpuMonitor(interval=0.1, reader=reader)
    monitor.start()
    try:
        # 事件同步 + 宽预算（首拍要等一个 interval，冷机/CI 慢 runner 是本地数倍）。
        assert reader.sampled.wait(10.0) is True
        deadline = time.monotonic() + 5.0
        while monitor.snapshot().percent is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert monitor.snapshot().percent == 7.0
    finally:
        monitor.stop()
    assert monitor.wait_stopped(10.0) is True
    assert monitor.running() is False


# ---------------------------------------------------------------- 本机真实读数
@pytest.mark.skipif(sys.platform != "win32", reason="PDH 只在 Windows 上存在")
def test_real_gpu_sample_on_this_machine():
    """真实跑一拍；拿不到就如实报不可用，**不伪造读数**。"""
    reader = gpu.GpuReader()
    try:
        first = reader.read()
        assert first.percent is None
        sample = first
        for _ in range(3):
            if sample.state == gpu.STATE_OK:
                break
            time.sleep(0.4)
            sample = reader.read()
    finally:
        assert reader.close() is True

    assert sample.state in gpu.STATES
    if sample.state == gpu.STATE_OK:
        assert isinstance(sample.percent, float)
        assert math.isfinite(sample.percent)
        assert 0.0 <= sample.percent <= 100.0
        assert sample.adapter is not None
    else:
        # 没有 GPU / 没有计数器对象：一律无读数 + 具体原因（unknown/unsupported/error）。
        assert sample.percent is None
        assert sample.error_reason
