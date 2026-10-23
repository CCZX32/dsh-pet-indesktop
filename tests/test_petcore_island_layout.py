"""灵动岛布局层（`petcore/island/layout.py`）的单测：落位、收缩、锚点。

全部用度量替身（每字符固定宽度），不依赖平台字体；不启动窗口。
"""

from __future__ import annotations

import pytest

from petcore.island import layout, segments as isl


class FakeMetrics:
    """字体度量替身：每字符固定 ``step`` px。"""

    def __init__(self, step: int = 10) -> None:
        self.step = step

    def horizontalAdvance(self, text) -> int:
        return len(str(text)) * self.step

    def height(self) -> int:
        return 17

    def lineSpacing(self) -> int:
        return 20

    def ascent(self) -> int:
        return 13

    def descent(self) -> int:
        return 4

    def leading(self) -> int:
        return 0

    def averageCharWidth(self) -> int:
        return self.step


FM = FakeMetrics(10)
PRIMARY = layout.KIND_PRIMARY


def _primary(text="88:88", box="88:88"):
    return layout._InfoSeg(
        kind=PRIMARY,
        seg_id="primary",
        label="",
        text=text,
        box_text=box,
        state=isl.STATE_OK,
    )


def _metric(seg_id, label, text, box, *, unit="", severity="", state=isl.STATE_OK):
    return layout._InfoSeg(
        kind=layout.KIND_METRIC,
        seg_id=seg_id,
        label=label,
        text=text,
        box_text=box,
        state=state,
        unit=unit,
        severity=severity,
    )


def _cpu(text="24", state=isl.STATE_OK, severity=""):
    return _metric("cpu", "CPU", text, "888", unit="%", state=state, severity=severity)


def _mem(text="61", state=isl.STATE_OK, severity=""):
    return _metric("mem", "内存", text, "888", unit="%", state=state, severity=severity)


# ---------------------------------------------------------------- 落位


def test_placement_orders_segments_with_19px_slots():
    row = (_primary(), _cpu(), _mem())
    placements = layout.place_info_segments(
        row, start_x=100, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    assert [p.seg.seg_id for p in placements] == ["primary", "cpu", "mem"]
    # 主信息段紧贴起点，没有槽位与竖线
    assert placements[0].box_x == pytest.approx(100)
    assert placements[0].divider_x is None
    # 指标段前有 19px 槽位，竖线居中
    assert placements[1].divider_x == pytest.approx(100 + 50 + 9)
    assert placements[1].label_x == pytest.approx(100 + 50 + 19)
    # 段之间不重叠
    for previous, current in zip(placements, placements[1:]):
        assert current.label_x > previous.right


def test_unit_box_width_is_uniform_across_the_row():
    row = (_primary(), _cpu(), _mem())
    placements = layout.place_info_segments(
        row, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    units = {p.seg.seg_id: p.unit_w for p in placements if p.unit_x is not None}
    assert units == {"cpu": 10, "mem": 10}
    # 单位盒紧贴数值盒 1px
    cpu = next(p for p in placements if p.seg.seg_id == "cpu")
    assert cpu.unit_x == pytest.approx(cpu.box_x + cpu.box_w + 1)


def test_non_ok_state_keeps_box_but_hides_unit():
    ok_row = (_primary(), _cpu("24"))
    sampling_row = (_primary(), _cpu("--", state=isl.STATE_SAMPLING))
    ok = layout.place_info_segments(
        ok_row, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    sampling = layout.place_info_segments(
        sampling_row, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    assert [p.box_w for p in ok] == [p.box_w for p in sampling]
    assert [p.right for p in ok] == [p.right for p in sampling]
    assert sampling[1].unit_text == ""


def test_chip_box_has_padding_and_no_divider():
    row = (_primary(), _cpu(), layout.chip_segment(2))
    placements = layout.place_info_segments(
        row, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    chip = placements[-1]
    assert chip.seg.kind == layout.KIND_CHIP
    assert chip.divider_x is None
    assert chip.box_w == max(26, 2 * 10 + 2 * 6)
    # 文字在盒内居中
    assert chip.text_x == pytest.approx(chip.box_x + (chip.box_w - chip.text_w) / 2.0)


def test_chip_alert_dot_does_not_change_box_width():
    plain = (_primary(), _cpu(), layout.chip_segment(1))
    alerted = (_primary(), _cpu(), layout.chip_segment(1, isl.ALERT_CRIT))
    left = layout.place_info_segments(
        plain, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    right = layout.place_info_segments(
        alerted, start_x=0, primary_fm=FM, value_fm=FM, label_fm=FM
    )
    assert [p.box_w for p in left] == [p.box_w for p in right]
    assert [p.right for p in left] == [p.right for p in right]
    assert right[-1].alert_dot_x is not None
    assert right[-1].text_x > left[-1].text_x


def test_elide_to_width_never_exceeds_limit():
    for limit in (0, 1, 15, 40, 96):
        text = layout.elide_to_width("一二三四五六七八九十", limit, FM)
        assert FM.horizontalAdvance(text) <= limit


# ---------------------------------------------------------------- 收缩


def _plan(row, *, available, name="鲸鱼娘", lead=45.0, trail=18.0):
    return layout.plan_info_row(
        row,
        lead_w=lead,
        trail_w=trail,
        name_text=name,
        available_w=available,
        primary_fm=FM,
        value_fm=FM,
        label_fm=FM,
        name_fm=FM,
    )


def test_roomy_row_keeps_name_and_all_segments():
    plan = _plan((_primary(), _cpu(), _mem()), available=10000)
    assert plan.level == layout.LEVEL_NONE
    assert plan.name == "鲸鱼娘"
    assert plan.folded == ()
    assert plan.visible == ("primary", "cpu", "mem")


def test_shrink_levels_go_name_elide_then_hide_then_fold():
    row = (_primary(), _cpu(), _mem())
    # 名字要够长才会先被"收窄"（≤40px 的省略级是它存在的唯一理由）
    long_name = "鲸鱼娘和她的管理员朋友们"
    roomy = _plan(row, available=10000, name=long_name)
    plan_a = _plan(row, available=roomy.width - 1, name=long_name)
    assert plan_a.level == layout.LEVEL_NAME_ELIDE
    assert FM.horizontalAdvance(plan_a.name) <= 40
    plan_b = _plan(row, available=roomy.width - 60, name=long_name)
    assert plan_b.name in ("", plan_a.name)
    levels = {
        _plan(row, available=width, name=long_name).level
        for width in (roomy.width, roomy.width - 30, roomy.width - 80, 200, 130)
    }
    assert layout.LEVEL_NAME_ELIDE in levels
    assert layout.LEVEL_NAME_HIDE in levels
    folded = _plan(row, available=200, name=long_name)
    assert folded.level >= layout.LEVEL_FOLD_BASE
    assert folded.folded
    assert folded.visible[-1] == "chip"


def test_fold_prefers_the_tail_and_never_drops_primary():
    row = (_primary(), _cpu(), _mem())
    plan = _plan(row, available=1)
    assert "primary" in plan.visible
    # 折叠次序 = 尾部优先：mem 先牺牲
    assert plan.folded[0] == "mem"
    assert plan.folded_count >= 1


def test_plan_is_pure_and_reversible():
    row = (_primary(), _cpu(), _mem())
    wide = _plan(row, available=10000)
    narrow = _plan(row, available=200)
    again = _plan(row, available=10000)
    assert wide == again
    assert narrow != wide


def test_readings_never_change_the_planned_width():
    row = (_primary(), _cpu("9"), _mem("9"))
    other = (_primary(), _cpu("100"), _mem("100"))
    left = _plan(row, available=10000)
    right = _plan(other, available=10000)
    assert left.width == right.width


def test_primary_box_may_grow_but_metrics_do_not():
    short = _plan((_primary("9:00", "88:88"), _cpu()), available=10000)
    longer = _plan((_primary("余额 ¥88888.88", "88:88"), _cpu()), available=10000)
    assert longer.width > short.width


def test_apply_shrink_uses_current_texts_and_current_severity():
    planned = _plan((_primary(), _cpu(), _mem()), available=1)
    current = (_primary(), _cpu("77"), _mem("88", state=isl.STATE_ERROR))
    row = layout.apply_shrink(planned, current, primary_fm=FM)
    assert row[0].seg_id == "primary"
    assert row[-1].kind == layout.KIND_CHIP
    # error 段被折时必须把 chip 染成 crit（折叠不埋没故障）
    if "mem" in planned.folded:
        assert row[-1].severity == isl.ALERT_CRIT


def test_apply_shrink_tolerates_segments_missing_from_the_plan():
    planned = _plan((_primary(), _cpu(), _mem()), available=1)
    row = layout.apply_shrink(planned, (_primary(), _cpu()), primary_fm=FM)
    assert [seg.seg_id for seg in row] == ["primary", "cpu"] or row[-1].kind == layout.KIND_CHIP


def test_apply_shrink_without_segments_returns_empty():
    planned = _plan((_primary(),), available=10000)
    assert layout.apply_shrink(planned, (), primary_fm=FM) == ()


# ---------------------------------------------------------------- 锚点


def test_anchored_x_keeps_the_edge_in_use():
    # 左 1/3：左缘固定
    assert layout.anchored_x(x=10, width=120, new_width=200, screen_left=0, screen_width=1200) == 10
    # 中间 1/3：中心固定
    middle = layout.anchored_x(
        x=560, width=120, new_width=200, screen_left=0, screen_width=1200
    )
    assert middle == pytest.approx(520)
    # 右 1/3：右缘固定
    right = layout.anchored_x(
        x=1070, width=120, new_width=200, screen_left=0, screen_width=1200
    )
    assert right == pytest.approx(990)


def test_anchored_x_returns_input_when_screen_is_unknown():
    assert layout.anchored_x(x=42, width=100, new_width=200, screen_left=0, screen_width=0) == 42
