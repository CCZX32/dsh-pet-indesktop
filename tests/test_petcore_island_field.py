"""灵动岛碰撞几何（`petcore/engine/island_field.py`）的单测。

全部是纯函数：不建窗口、不碰 Qt、不依赖平台。口径与主分支
`pet/island_collision.py:292-341` 相同（矩形径向半径 + 轴上强制向上），
只把「岛」「身体框」抽象成数据。
"""

from __future__ import annotations

import math

import pytest

from petcore.engine import island_field as field


# ---------------------------------------------------------------- 体育场
def test_stadium_caps_the_capsule_height():
    stadium = field.stadium_from_rect(100, 10, 300, 44)
    assert stadium is not None
    assert stadium.height == pytest.approx(44.0)
    assert stadium.radius == pytest.approx(22.0)
    assert stadium.axis_y == pytest.approx(32.0)
    assert stadium.x0 == pytest.approx(122.0)
    assert stadium.x1 == pytest.approx(378.0)


def test_expanded_card_only_walls_the_capsule_body():
    """展开卡片时只覆盖 44px 胶囊：卡片区域不是幽灵墙。"""
    stadium = field.stadium_from_rect(100, 10, 300, 320)
    assert stadium is not None
    assert stadium.height == pytest.approx(field.CAPSULE_HEIGHT)
    assert stadium.axis_y == pytest.approx(32.0)


@pytest.mark.parametrize(
    "rect",
    [
        (0, 0, 0, 44),
        (0, 0, 300, 0),
        (float("nan"), 0, 300, 44),
        (0, float("inf"), 300, 44),
        (0, 0, -10, 44),
    ],
)
def test_invalid_rects_never_build_a_wall(rect):
    assert field.stadium_from_rect(*rect) is None


# ---------------------------------------------------------------- 推出
def _stadium():
    # 胶囊：宽 200 高 44 → 半径 22，轴 y=122，轴 [122, 278]
    return field.stadium_from_rect(100, 100, 200, 44)


def test_body_above_the_axis_is_pushed_up():
    stadium = _stadium()
    pushed = field.push_out((150, 70, 40, 40), stadium)  # 中心 (170, 90)，轴 122
    assert pushed is not None
    assert pushed.nx == pytest.approx(0.0)
    assert pushed.ny == pytest.approx(-1.0)
    assert pushed.depth == pytest.approx(42.0 - 32.0)
    # 推到位后不再重叠（幂等）
    assert field.push_out((pushed.left, pushed.top, 40, 40), stadium) is None


def test_pushed_body_sits_exactly_on_the_surface():
    stadium = _stadium()
    pushed = field.push_out((150, 70, 40, 40), stadium)
    assert pushed is not None
    center_y = pushed.top + 20
    # 表面 = 轴 y - (身体径向 20 + 岛半径 22) - 1 的缝隙
    assert center_y == pytest.approx(stadium.axis_y - 20 - stadium.radius - 1.0)


def test_side_wall_uses_half_width_not_half_height():
    """矩形口径：侧壁用半宽，不用半高（椭圆/整框会让四角穿模）。"""
    stadium = _stadium()
    body = (40, 90, 80, 64)  # 中心 (80, 122)：纵向与轴同高，正对左端半圆
    pushed = field.push_out(body, stadium)
    assert pushed is not None
    assert pushed.nx == pytest.approx(-1.0)
    assert pushed.ny == pytest.approx(0.0)
    radial = field.rect_radial(40.0, 32.0, pushed.nx, pushed.ny)
    assert radial == pytest.approx(40.0)  # 半宽
    assert radial > 32.0  # 绝不是半高


def test_center_on_the_axis_is_pushed_upward():
    stadium = _stadium()
    pushed = field.push_out((150, 102, 40, 40), stadium)  # 中心 (170, 122) = 轴上
    assert pushed is not None
    assert pushed.ny == pytest.approx(-1.0)
    assert pushed.nx == pytest.approx(0.0)


def test_body_outside_the_stadium_is_untouched():
    stadium = _stadium()
    assert field.push_out((0, 0, 40, 40), stadium) is None
    assert field.push_out((400, 100, 40, 40), stadium) is None
    # 贴着表面外侧（留 1px 缝隙，中心距轴 43px）不算重叠
    assert field.push_out((150, 59, 40, 40), stadium) is None


def test_rect_radial_matches_the_half_extent_on_the_axis():
    assert field.rect_radial(20.0, 30.0, 0.0, -1.0) == pytest.approx(30.0)
    assert field.rect_radial(20.0, 30.0, -1.0, 0.0) == pytest.approx(20.0)
    diagonal = field.rect_radial(20.0, 30.0, math.sqrt(0.5), math.sqrt(0.5))
    assert 20.0 < diagonal < 30.0


# ---------------------------------------------------------------- 冲量
def test_relative_approach_is_negative_when_closing():
    vn = field.relative_approach((0.0, 200.0), (0.0, 0.0), (0.0, -1.0))
    assert vn == pytest.approx(-200.0)


def test_island_speed_participates_in_the_approach():
    """岛竖直上移撞向静止桌宠：相对接近速度来自岛速（颠勺的燃料）。"""
    vn = field.relative_approach((0.0, 0.0), (0.0, -600.0), (0.0, -1.0))
    assert vn == pytest.approx(-600.0)


def test_trampoline_velocity_uses_the_static_restitution():
    vx, vy = field.impulse_velocity(-200.0, (0.0, -1.0))
    assert vx == pytest.approx(0.0)
    assert vy == pytest.approx(-(1.0 + field.STATIC_RESTITUTION) * 200.0)


def test_impulse_speed_is_capped():
    vx, vy = field.impulse_velocity(-100000.0, (1.0, 0.0))
    assert math.hypot(vx, vy) <= field.MAX_IMPULSE_SPEED + 1e-6


def test_reflect_never_amplifies_the_thrown_speed():
    vx, vy = field.reflect_velocity((0.0, 900.0), (0.0, -1.0), 0.68)
    assert vy == pytest.approx(-900.0 * 0.68)
    assert math.hypot(vx, vy) <= 900.0
    assert field.RESTITUTION < 1.0


# ---------------------------------------------------------------- 接触速度
def test_tracked_velocity_uses_the_body_delta():
    vx, vy = field.tracked_velocity((100.0, 100.0), (112.0, 100.0), 0.016)
    assert vx == pytest.approx(750.0)
    assert vy == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("prev", "cur", "dt"),
    [
        (None, (100.0, 100.0), 0.016),  # 首次接触
        ((100.0, 100.0), (100.0, 100.0), 0.0),  # dt 非法
        ((100.0, 100.0), (100.0, 100.0), 9.0),  # 间隔过长
    ],
)
def test_tracked_velocity_falls_back_to_zero(prev, cur, dt):
    assert field.tracked_velocity(prev, cur, dt) == (0.0, 0.0)


def test_tracked_velocity_rejects_teleports():
    """发起移动计划时会先算一次 240px 外的落点：那不是接近速度。"""
    vx, vy = field.tracked_velocity((100.0, 100.0), (340.0, 100.0), 0.002)
    assert (vx, vy) == (0.0, 0.0)


# ---------------------------------------------------------------- 岛速采样
def test_first_sample_only_primes_the_baseline():
    sample = field.sample_island_velocity(None, (0.0, 0.0, 300.0, 44.0), 0.016, dragging=True)
    assert (sample.vx, sample.vy) == (0.0, 0.0)
    assert sample.update_baseline is True


def test_size_change_only_resets_the_sample_point():
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (0.0, 0.0, 320.0, 44.0), 0.016, dragging=True
    )
    assert (sample.vx, sample.vy) == (0.0, 0.0)
    assert sample.update_baseline is True


def test_high_frequency_reports_skip_without_zeroing():
    """一次 mouseMoveEvent 会喂两遍同一 rect：跳过时不许清基线（会退化成只推不拍）。"""
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (5.0, 0.0, 300.0, 44.0), 0.001, dragging=True
    )
    assert sample.update_baseline is False
    assert sample.keep_velocity is False


def test_long_pause_does_not_resurrect_speed():
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (40.0, 0.0, 300.0, 44.0), 9.0, dragging=True
    )
    assert (sample.vx, sample.vy) == (0.0, 0.0)
    assert sample.update_baseline is True


def test_teleport_is_not_sampled():
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (3000.0, 0.0, 300.0, 44.0), 0.016, dragging=True
    )
    assert (sample.vx, sample.vy) == (0.0, 0.0)


def test_paired_same_rect_keeps_the_drag_velocity():
    kept = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (0.0, 0.0, 300.0, 44.0), 0.016, dragging=True
    )
    assert kept.keep_velocity is True
    stopped = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (0.0, 0.0, 300.0, 44.0), 0.016, dragging=False
    )
    assert stopped.keep_velocity is False
    assert (stopped.vx, stopped.vy) == (0.0, 0.0)


def test_drag_moves_are_measured_in_pixels_per_second():
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (16.0, 0.0, 300.0, 44.0), 0.016, dragging=True
    )
    assert sample.vx == pytest.approx(1000.0)
    assert sample.keep_velocity is False


def test_overspeed_is_clamped_only_while_dragging():
    clamped = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (48.0, 0.0, 300.0, 44.0), 0.016, dragging=True
    )
    assert clamped.vx == pytest.approx(field.MAX_ISLAND_SPEED)
    reset = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (48.0, 0.0, 300.0, 44.0), 0.016, dragging=False
    )
    assert (reset.vx, reset.vy) == (0.0, 0.0)


def test_release_sample_is_always_zero():
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0),
        (0.0, 40.0, 300.0, 44.0),
        0.016,
        dragging=False,
        released=True,
    )
    assert (sample.vx, sample.vy) == (0.0, 0.0)


def test_a_stopped_island_zeroes_speed_even_on_a_dense_report():
    """停手后同一帧的第二遍上报（dt 很小、rect 没动）不许留着停手前的速度。"""
    sample = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (0.0, 0.0, 300.0, 44.0), 0.001, dragging=False
    )
    assert (sample.vx, sample.vy) == (0.0, 0.0)
    assert sample.update_baseline is True
    # 拖拽中同样的上报必须"跳过"（不清零也不刷新基线）
    dragging = field.sample_island_velocity(
        (0.0, 0.0, 300.0, 44.0), (0.0, 0.0, 300.0, 44.0), 0.001, dragging=True
    )
    assert dragging.update_baseline is False
