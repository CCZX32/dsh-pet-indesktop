"""灵动岛采样层（`petcore/platform/netmon.py` / `sysmon.py`）的单测。

全部用替身读数：不碰真实网卡、不等真实 1 秒、不依赖 psutil 是否装好。
"""

from __future__ import annotations

import pytest

from petcore.platform import netmon, sysmon


# ---------------------------------------------------------------- 网络


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 1.0), ("x", 1.0), (float("nan"), 1.0), (0.1, 0.5), (1.5, 1.5), (600, 60.0)],
)
def test_net_interval_is_clamped(value, expected):
    assert netmon.clamp_interval(value) == expected


@pytest.mark.parametrize(
    ("bps", "text"),
    [
        (0, "0B"),
        (512, "512B"),
        (812 * 1024, "812K"),
        (1.2 * 1024**2, "1.2M"),
        (941 * 1024**2, "941M"),
        (1.2 * 1024**3, "1.2G"),
        (999 * 1024**3, "999G"),
    ],
)
def test_format_rate_never_exceeds_the_five_column_budget(bps, text):
    rendered = netmon.format_rate(bps)
    assert rendered == text
    assert len(rendered) <= netmon.RATE_FIELD_WIDTH


def test_network_slot_text_keeps_a_constant_width():
    widths = {
        len(netmon.format_network_slot(down, up))
        for down, up in (
            (0, 0),
            (812 * 1024, 340 * 1024),
            (1.2 * 1024**2, 941 * 1024**2),
            (1023 * 1024**2, 1023 * 1024**2),
        )
    }
    assert len(widths) == 1
    assert len(netmon.format_network_slot(0, 0)) == len(netmon.NETWORK_BOX_SAMPLE)


def test_rate_meter_first_sample_only_primes():
    clock = [100.0]
    readings = [[(1000.0, 500.0)], [(3048.0, 1524.0)]]
    meter = netmon.NetRateMeter(reader=lambda: readings.pop(0)[0], clock=lambda: clock[0])
    assert meter.sample() is None
    clock[0] += 1.0
    sample = meter.sample()
    assert sample is not None
    assert sample.down_bps == pytest.approx(2048.0)
    assert sample.up_bps == pytest.approx(1024.0)


def test_rate_meter_ema_smooths_the_second_delta():
    clock = [0.0]
    readings = [(0.0, 0.0), (1000.0, 0.0), (3000.0, 0.0)]
    meter = netmon.NetRateMeter(reader=lambda: readings.pop(0), clock=lambda: clock[0])
    meter.sample()
    clock[0] += 1.0
    first = meter.sample()
    clock[0] += 1.0
    second = meter.sample()
    assert first is not None and second is not None
    assert first.down_bps == pytest.approx(1000.0)
    assert second.down_bps == pytest.approx(1000.0 * 0.5 + 2000.0 * 0.5)


def test_rate_meter_ignores_counter_resets_and_missing_readers():
    clock = [0.0]
    readings = [(5000.0, 5000.0), (10.0, 10.0)]
    meter = netmon.NetRateMeter(reader=lambda: readings.pop(0), clock=lambda: clock[0])
    meter.sample()
    clock[0] += 1.0
    sample = meter.sample()
    assert sample is not None
    assert sample.down_bps == 0.0 and sample.up_bps == 0.0

    broken = netmon.NetRateMeter(reader=lambda: None, clock=lambda: 0.0)
    assert broken.sample() is None


def test_net_monitor_poll_and_lifecycle():
    class Meter:
        def __init__(self):
            self.calls = 0

        def sample(self):
            self.calls += 1
            return netmon.RateSample(down_bps=1.0, up_bps=2.0)

    monitor = netmon.NetMonitor(interval=0.5, meter=Meter())
    assert monitor.snapshot() is None
    sample = monitor.poll()
    assert sample is not None and sample.text.startswith("↓")
    assert monitor.snapshot() is sample
    monitor.start()
    try:
        assert monitor.running() is True
    finally:
        monitor.stop()
    assert monitor.running() is False


# ---------------------------------------------------------------- 系统


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 1.0), ("x", 1.0), (0.2, 1.0), (5, 5.0), (600, 60.0)]
)
def test_sys_interval_has_a_one_hertz_floor(value, expected):
    assert sysmon.clamp_interval(value) == expected


@pytest.mark.parametrize(
    ("value", "text"),
    [(None, "--"), ("x", "--"), (float("nan"), "--"), (24.4, "24%"), (0, "0%"), (100, "100%")],
)
def test_percent_formatters(value, text):
    assert sysmon.format_cpu(value) == text
    assert sysmon.format_mem(value) == text


def test_percent_box_sample_covers_every_real_reading():
    # 盒宽样本是**声明值**（888%），真实读数只会在盒内伸缩，不反向定义盒宽
    assert sysmon.MAX_TEXT == "888%"
    for percent in (0, 9, 24, 99, 100):
        assert len(sysmon.format_cpu(percent)) <= len(sysmon.MAX_TEXT)


def test_cpu_meter_primes_before_reporting():
    readings = [0.0, 37.0]
    meter = sysmon.CpuMeter(lambda: readings.pop(0))
    assert meter.sample() is None
    assert meter.primed is True
    assert meter.sample() == 37.0
    meter.reset()
    assert meter.primed is False


def test_sys_monitor_reports_both_metrics_and_survives_reader_failures():
    readings = [0.0, 21.0]
    monitor = sysmon.SysMonitor(
        interval=1.0,
        cpu_reader=lambda: readings.pop(0),
        mem_reader=lambda: 61.0,
    )
    first = monitor.poll()
    assert first.cpu_percent is None       # 首拍只建基线
    assert first.mem_percent == 61.0
    second = monitor.poll()
    assert second.cpu_percent == 21.0
    assert second.error == ""

    def boom():
        raise sysmon.PsutilUnavailable("no psutil")

    broken = sysmon.SysMonitor(interval=1.0, cpu_reader=boom, mem_reader=lambda: 1.0)
    sample = broken.poll()
    assert sample.cpu_percent is None
    assert sample.mem_percent is None
    assert "psutil" in sample.error


def test_sys_monitor_lifecycle_is_idempotent():
    monitor = sysmon.SysMonitor(interval=1.0, cpu_reader=lambda: 5.0, mem_reader=lambda: 5.0)
    monitor.start()
    monitor.start()
    monitor.stop()
    monitor.stop()
    assert monitor.running() is False
