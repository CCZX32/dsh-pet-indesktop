"""灵动岛「C 盘剩余」段：格式化、采样器、岛接线与配置白名单。

全部用替身读数，不真的去读 C 盘；只有一条「真实读一次」的用例会碰系统盘。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.island import segments as isl
from petcore.platform import diskmon
from petcore.ui import island as island_ui

app = QApplication.instance() or QApplication([])

GIB = 1024**3
TIB = 1024**4


# ---------------------------------------------------------------- 格式化
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "--"),
        ("x", "--"),
        (float("nan"), "--"),
        (-1, "--"),
        (0, "0G"),
        (412 * GIB, "412G"),
        (9.4 * GIB, "9.4G"),
        (972 * GIB, "972G"),
        (9.96 * GIB, "10G"),   # 两条 .0f 边界的另一侧：不许渲染成 5 列的 "10.0G"
        (9.99 * TIB, "10T"),
        (1000 * GIB, "1.0T"),  # 0.975T 起走 T：不许渲染出 5 列的 "1000G"
        (999 * GIB, "1.0T"),
        (float(1.8 * TIB), "1.8T"),
        (12 * TIB, "12T"),
    ],
)
def test_format_free_never_exceeds_the_four_column_budget(value, text):
    rendered = diskmon.format_free(value)
    assert rendered == text
    assert len(rendered) <= 4


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.1, 5.0), ("x", 5.0), (float("nan"), 5.0), (5.0, 5.0), (30, 30.0), (600, 60.0)],
)
def test_interval_is_clamped_to_the_slow_lane(value, expected):
    assert diskmon.clamp_interval(value) == expected


def test_box_sample_covers_the_real_envelope():
    assert len(diskmon.FREE_FIELD_SAMPLE) == 4
    assert diskmon.format_free(412 * GIB) != diskmon.UNKNOWN_TEXT


# ---------------------------------------------------------------- 读取
def test_volume_path_points_at_the_system_drive():
    path = diskmon.volume_path()
    assert path
    if os.name == "nt":
        assert path.endswith("\\")
        assert ":" in path


def test_read_usage_reports_failures_instead_of_zero():
    free, total, error = diskmon.read_usage("Z:\\definitely-not-a-volume\\nope")
    assert free is None and total is None
    assert error


def test_read_usage_reads_the_real_system_drive():
    free, total, error = diskmon.read_usage()
    assert not error
    assert free is not None and total is not None
    assert 0 <= free <= total < 10**15


# ---------------------------------------------------------------- 采样器
def _monitor(reader=diskmon.read_usage, interval=5.0):
    return diskmon.DiskMonitor(interval=interval, reader=reader)


def test_monitor_publishes_one_sample_per_poll():
    calls = []

    def reader(path):
        calls.append(path)
        return 400 * GIB, 1 * TIB, ""

    monitor = _monitor(reader)
    sample = monitor.poll()
    assert sample is not None
    assert sample.text == "400G"
    assert sample.note.startswith("总 1.0T")
    assert "已用" in sample.note
    assert len(calls) == 1
    assert monitor.snapshot() is sample


def test_restart_keeps_the_last_reading_visible():
    """折叠→展开/隐藏→显示会解除停采：`start()` 重置快照，但不许因此闪 5 秒 `--`。"""
    monitor = _monitor(lambda path: (321 * GIB, 1 * TIB, ""))
    monitor.poll()
    monitor.start()
    try:
        assert monitor.snapshot() is not None
        assert monitor.snapshot().text == "321G"
    finally:
        monitor.stop()
        assert monitor.wait_stopped(5)


def test_monitor_reports_an_error_sample_without_a_zero_reading():
    monitor = _monitor(lambda path: (None, None, "拒绝访问"))
    sample = monitor.poll()
    assert sample is not None
    assert sample.free_bytes is None
    assert sample.text == diskmon.UNKNOWN_TEXT
    assert sample.error == "拒绝访问"
    assert sample.note == ""


def test_stop_without_start_keeps_the_last_snapshot():
    """停采不清值：折叠/展开不会闪成 `--`（start() 才会重置快照）。"""
    monitor = _monitor(lambda path: (123 * GIB, 1 * TIB, ""))
    monitor.poll()
    assert monitor.snapshot() is not None
    monitor.stop()
    assert monitor.wait_stopped(5)
    assert monitor.snapshot() is not None


def test_monitor_thread_is_named_and_stops():
    monitor = _monitor()
    monitor.start()
    monitor.stop()
    assert monitor.wait_stopped(5)
    assert monitor.running() is False


# ---------------------------------------------------------------- 岛接线
@pytest.fixture()
def make_island(tmp_path):
    created = []

    def factory(values=None):
        config = Config(
            tmp_path,
            {"island_enabled": True, "island_metrics": ["disk"], **(values or {})},
        )
        widget = island_ui.DynamicIsland(config, character_name="深深")
        created.append(widget)
        return widget

    yield factory
    for widget in created:
        widget.stop()
        assert widget.disk_monitor.wait_stopped(5)
        assert widget.sys_monitor.wait_stopped(5)
        assert widget.net_monitor.wait_stopped(5)
        widget.close()
        widget.deleteLater()


def test_disk_segment_uses_a_fixed_box_and_a_readable_label(make_island):
    island = make_island()
    island.disk_monitor = _monitor(lambda path: (412 * GIB, 2 * TIB, ""))
    island.disk_monitor.poll()
    island._rebuild_row()
    seg = island._row[1]
    assert seg.seg_id == isl.DISK
    assert seg.label == island_ui.DISK_LABEL
    assert seg.text == "412G"
    assert seg.box_text == diskmon.FREE_FIELD_SAMPLE
    assert seg.state == isl.STATE_OK
    assert seg.detail["note"].startswith("总 2.0T")


def test_disk_segment_is_sampling_before_the_first_read(make_island):
    island = make_island()
    island._rebuild_row()
    seg = island._row[1]
    assert seg.state == isl.STATE_SAMPLING
    assert seg.text == ""


def test_disk_segment_reports_the_error_reason(make_island):
    island = make_island()
    island.disk_monitor = _monitor(lambda path: (None, None, "拒绝访问"))
    island.disk_monitor.poll()
    island._rebuild_row()
    seg = island._row[1]
    assert seg.state == isl.STATE_ERROR
    assert seg.detail["error_reason"] == "拒绝访问"


def test_card_row_carries_the_usage_note(make_island):
    island = make_island()
    island.disk_monitor = _monitor(lambda path: (412 * GIB, 2 * TIB, ""))
    island.disk_monitor.poll()
    island._rebuild_row()
    rows = island._card_rows()
    assert rows[0][0] == island_ui.DISK_LABEL
    assert rows[0][1] == "412G"
    assert "已用" in rows[0][2]


def test_card_row_shows_the_error_reason(make_island):
    island = make_island()
    island.disk_monitor = _monitor(lambda path: (None, None, "拒绝访问"))
    island.disk_monitor.poll()
    island._rebuild_row()
    row = island._card_rows()[0]
    assert row[1] == "--"
    assert row[2] == "拒绝访问"
    assert row[3] == isl.ALERT_CRIT


def test_hidden_island_does_not_sample_the_disk(make_island):
    island = make_island()
    island.show()
    island.start()
    island._sync_sampling()
    assert island.disk_monitor.running() is True
    island.hide()
    island._sync_sampling()
    # 取消是异步的（读线程可能还阻塞在 syscall 里）：要等它退出，别轮询 running()
    assert island.disk_monitor.wait_stopped(5)


def test_folding_the_disk_segment_stops_the_sampler(make_island):
    """胶囊上被折进「+N」= 看不见 = 停采（卡片展开态例外，见下一条）。"""
    island = make_island()

    class _Folded:
        folded = (isl.DISK,)

    island.show()
    island.start()
    island._plan = _Folded()
    island._sync_sampling()
    assert island.disk_monitor.wait_stopped(5)
    island._plan = None


def test_expanding_the_card_keeps_the_disk_sampler_alive(make_island):
    """展开卡片每段都有明细行：折行只是排版，不许据此停采（审计 AUD-25）。"""
    island = make_island()
    island.show()
    island.start()
    island._expanded = True
    island._plan = island._compute_plan(1)
    island._sync_sampling()
    assert island.disk_monitor.running() is True
    island._expanded = False


# ---------------------------------------------------------------- 配置
def test_config_keeps_the_disk_metric_and_drops_unknown_ids(tmp_path):
    config = Config(tmp_path, {"island_metrics": ["disk", "cpu", "nope"]})
    assert config.get("island_metrics") == ["disk", "cpu"]


def test_default_metrics_do_not_include_the_disk(tmp_path):
    config = Config(tmp_path, {})
    assert config.get("island_metrics") == ["cpu", "mem"]


def test_disk_is_a_reserved_segment_id():
    assert isl.DISK == "disk"
    assert isl.DISK in isl.BUILTIN_SEGMENT_IDS
    assert isl.DISK not in isl.ALERT_THRESHOLDS
