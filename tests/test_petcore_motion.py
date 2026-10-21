from __future__ import annotations

from petcore.contracts.content import AnimationSpec
from petcore.engine.enums import AnimatType, GraphType
from petcore.engine.geometry import (
    MOVE_STRIDE_DEFAULT_PX,
    band_bounds,
    clamp_position,
    position_from_ratio,
    ratio_in_span,
    rect_distance,
    rect_overlap_area,
)
from petcore.engine.motion import clamp_to_screens, stride_for

LEFT = (0, 0, 1920, 1080)
RIGHT = (1920, 0, 2560, 1440)
TOP = (0, 0, 1920, 1080)
BOTTOM = (0, 1080, 1920, 1080)
UPPER = (1920, -800, 2560, 1440)
MAIN_NEGATIVE = (-1920, -120, 1920, 1080)

SIDE_BY_SIDE = (LEFT, RIGHT)
STACKED = (TOP, BOTTOM)
OFFSET = (LEFT, UPPER)


def _spec(name: str = "walk") -> AnimationSpec:
    return AnimationSpec(name=name, graph=GraphType.MOVE, animat=AnimatType.B_LOOP)


# ---------------------------------------------------------------- clamp_position


def test_clamp_position_leaves_an_inside_position_untouched():
    assert clamp_position(100, 200, 640, 360, LEFT) == (100, 200)
    assert clamp_position(0, 0, 640, 360, LEFT) == (0, 0)
    assert clamp_position(1280, 720, 640, 360, LEFT) == (1280, 720)


def test_clamp_position_pushes_every_edge_back_inside():
    assert clamp_position(-50, 500, 640, 360, LEFT) == (0, 500)
    assert clamp_position(1900, 500, 640, 360, LEFT) == (1280, 500)
    assert clamp_position(500, -10, 640, 360, LEFT) == (500, 0)
    assert clamp_position(500, 2000, 640, 360, LEFT) == (500, 720)
    assert clamp_position(-50, -10, 640, 360, LEFT) == (0, 0)
    assert clamp_position(5000, 5000, 640, 360, LEFT) == (1280, 720)


def test_clamp_position_handles_a_negative_origin():
    bounds = MAIN_NEGATIVE  # (left, top, width, height)
    left, top = bounds[0], bounds[1]
    assert clamp_position(-1500, 100, 640, 360, bounds) == (-1500, 100)
    assert clamp_position(-3000, 100, 640, 360, bounds) == (left, 100)
    assert clamp_position(500, 100, 640, 360, bounds) == (left + 1920 - 640, 100)
    assert clamp_position(-1500, -500, 640, 360, bounds) == (-1500, top)
    assert clamp_position(-1500, 2000, 640, 360, bounds) == (-1500, top + 1080 - 360)


def test_clamp_position_with_content_larger_than_bounds_pins_to_origin():
    assert clamp_position(50, 50, 640, 360, (0, 0, 100, 100)) == (0, 0)
    assert clamp_position(-50, -50, 640, 360, (-10, -10, 0, 0)) == (-10, -10)


# ---------------------------------------------------------------- band_bounds


def test_band_bounds_without_screens_returns_the_body():
    body = (100, 50, 640, 360)
    assert band_bounds(body, ()) == body


def test_band_bounds_side_by_side_union():
    # Only the screen the body overlaps in x contributes: a body on the left
    # screen keeps the left screen's band.
    assert band_bounds((100, 100, 64, 64), SIDE_BY_SIDE) == LEFT
    # Beyond the left screen's height only the taller right screen matches.
    assert band_bounds((3000, 1200, 64, 64), SIDE_BY_SIDE) == RIGHT
    # A body straddling the seam gets the union of both screens.
    assert band_bounds((1800, 100, 200, 200), SIDE_BY_SIDE) == (0, 0, 4480, 1440)


def test_band_bounds_stacked_union():
    # Both screens share the same x span, so any body touching that column
    # gets the full column height and may travel between the two screens.
    assert band_bounds((100, 100, 64, 64), STACKED) == (0, 0, 1920, 2160)
    assert band_bounds((900, 1000, 100, 200), STACKED) == (0, 0, 1920, 2160)
    assert band_bounds((100, 2000, 64, 64), STACKED) == (0, 0, 1920, 2160)


def test_band_bounds_offset_layout_spans_both_screens():
    # Body overlaps the left screen in x and the upper screen in y: the band is
    # the bounding box of the screens the body touches.
    assert band_bounds((1800, 100, 200, 200), OFFSET) == (0, -800, 4480, 1880)


def test_band_bounds_outside_every_screen_falls_back_to_the_full_desktop():
    # No screen intersects the body on either axis. Returning the body itself
    # would clamp the pet to a zero-room hole, so the full desktop union wins.
    band = band_bounds((5000, 5000, 64, 64), SIDE_BY_SIDE)
    assert band == (0, 0, 4480, 1440)
    assert band[2] > 0 and band[3] > 0

    negative = band_bounds((-5000, -5000, 64, 64), (MAIN_NEGATIVE, RIGHT))
    assert negative == (-1920, -120, 6400, 1560)
    assert negative[2] > 0 and negative[3] > 0


# ---------------------------------------------------------------- rect helpers


def test_rect_overlap_area():
    assert rect_overlap_area((0, 0, 100, 100), (50, 50, 100, 100)) == 2500
    assert rect_overlap_area((0, 0, 100, 100), (100, 0, 100, 100)) == 0
    assert rect_overlap_area((0, 0, 100, 100), (200, 200, 100, 100)) == 0
    assert rect_overlap_area((0, 0, 100, 100), (10, 10, 10, 10)) == 100


def test_rect_distance():
    assert rect_distance((0, 0, 100, 100), (0, 0, 100, 100)) == 0
    assert rect_distance((0, 0, 100, 100), (150, 0, 100, 100)) == 50
    assert rect_distance((0, 0, 100, 100), (0, 150, 100, 100)) == 50
    assert rect_distance((0, 0, 100, 100), (130, 140, 100, 100)) == 70
    assert rect_distance((0, 0, 100, 100), (50, 50, 10, 10)) == 0


# ---------------------------------------------------------------- ratio helpers


def test_ratio_in_span_clamps_to_the_span():
    assert ratio_in_span(100, 100, 800) == 0.0
    assert ratio_in_span(900, 100, 800) == 1.0
    assert ratio_in_span(500, 100, 800) == 0.5
    assert ratio_in_span(0, 100, 800) == 0.0
    assert ratio_in_span(2000, 100, 800) == 1.0


def test_ratio_in_span_without_length_is_the_middle():
    assert ratio_in_span(100, 100, 0) == 0.5
    assert ratio_in_span(-500, -2000, -10) == 0.5


def test_position_from_ratio_is_clamped_and_rounded():
    assert position_from_ratio(0.0, 100, 800) == 100
    assert position_from_ratio(1.0, 100, 800) == 900
    assert position_from_ratio(0.5, 100, 800) == 500
    assert position_from_ratio(-1.0, 100, 800) == 100
    assert position_from_ratio(2.0, 100, 800) == 900


def test_ratio_round_trip():
    for start in (0, 1920, -1920):
        for position in range(start, start + 800, 7):
            ratio = ratio_in_span(position, start, 800)
            assert position_from_ratio(ratio, start, 800) == position
    assert position_from_ratio(ratio_in_span(1920 + 800, 1920, 800), 1920, 800) == 2720


# ---------------------------------------------------------------- clamp_to_screens


def test_clamp_to_screens_without_screens_is_a_no_op():
    assert clamp_to_screens(5000, 5000, 640, 360, ()) == (5000, 5000)


def test_clamp_to_screens_keeps_a_window_inside_the_desktop():
    assert clamp_to_screens(-200, 500, 640, 360, SIDE_BY_SIDE) == (0, 500)
    assert clamp_to_screens(4300, 500, 640, 360, SIDE_BY_SIDE) == (3840, 500)
    assert clamp_to_screens(100, -100, 640, 360, SIDE_BY_SIDE) == (100, 0)
    assert clamp_to_screens(100, 5000, 640, 360, SIDE_BY_SIDE) == (100, 720)


def test_clamp_to_screens_leaves_a_window_that_spans_the_seam_alone():
    assert clamp_to_screens(1900, 500, 640, 360, SIDE_BY_SIDE) == (1900, 500)
    assert clamp_to_screens(3000, 1000, 640, 360, SIDE_BY_SIDE) == (3000, 1000)
    assert clamp_to_screens(900, 1000, 640, 360, STACKED) == (900, 1000)


def test_clamp_to_screens_with_a_negative_origin_desktop():
    screens = (MAIN_NEGATIVE, RIGHT)
    assert clamp_to_screens(-1500, 100, 640, 360, screens) == (-1500, 100)
    assert clamp_to_screens(-3000, 100, 640, 360, screens) == (-1920, 100)
    assert clamp_to_screens(-3000, -500, 640, 360, screens) == (-1920, -120)
    assert clamp_to_screens(4000, 2000, 640, 360, screens) == (3840, 1080)


def test_clamp_to_screens_with_an_oversized_window_pins_to_the_origin():
    assert clamp_to_screens(-500, 500, 5000, 5000, SIDE_BY_SIDE) == (0, 0)


# ---------------------------------------------------------------- stride_for


def test_stride_for_honours_the_character_table():
    strides = {"walk": 90, "run": 150}
    assert stride_for(_spec("walk"), strides) == 90
    assert stride_for(_spec("run"), strides) == 150


def test_stride_for_falls_back_to_the_default():
    assert MOVE_STRIDE_DEFAULT_PX == 120
    assert stride_for(_spec("walk"), None) == 120
    assert stride_for(_spec("walk"), {}) == 120
    assert stride_for(_spec("walk"), {"run": 150}) == 120
    assert stride_for(_spec("walk"), {"walk": 0}) == 120
    assert stride_for(_spec("walk"), {"walk": -150}) == 120
    assert stride_for(_spec("walk"), {"walk": "150"}) == 120


# ---------------------------------------------------------------- move plan / curve
from petcore.engine.motion import (  # noqa: E402
    body_reach,
    choose_move_direction,
    move_position_at_frame,
    quantize_move,
)


def test_body_reach_uses_the_body_width_and_margin():
    assert body_reach(0, 1920, 500, 160, 20) == (580.0, 100.0, 1820.0)


def test_choose_move_direction_prefers_the_only_reachable_side():
    assert choose_move_direction(50, 100, 1900, 60) == 1
    assert choose_move_direction(1850, 100, 1900, 60) == -1
    assert choose_move_direction(1000, 100, 1900, 60) in (-1, 1)
    assert choose_move_direction(1000, 1000, 1000, 60) is None


def test_quantize_move_locks_to_whole_strides():
    loops, distance, duration = quantize_move(200, 90, 1000, 2.0)
    assert (loops, distance, duration) == (2, 180.0, 4.0)
    loops, distance, duration = quantize_move(200, 90, 120, 2.0)
    assert (loops, distance) == (1, 90.0)


def test_move_position_at_frame_without_curve_is_linear_and_lands():
    plan = {
        "start_x": 0.0,
        "target_x": 100.0,
        "start_y": 10.0,
        "target_y": 10.0,
        "frames_per_loop": 10,
        "loops": 1,
        "total_frames": 10,
    }
    assert move_position_at_frame(plan, 0) == (0.0, 10.0)
    assert move_position_at_frame(plan, 5) == (50.0, 10.0)
    assert move_position_at_frame(plan, 9) == (100.0, 10.0)


def test_move_position_at_frame_curve_freezes_static_frames():
    # 前 5 帧原地，后 5 帧走完 100px（与 shenshen 的 curve 语义一致）。
    plan = {
        "start_x": 0.0,
        "target_x": 100.0,
        "start_y": 0.0,
        "target_y": 0.0,
        "frames_per_loop": 10,
        "loops": 1,
        "total_frames": 10,
        "curve": (0.0, 0.0, 0.0, 0.0, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    }
    assert move_position_at_frame(plan, 3) == (0.0, 0.0)
    assert move_position_at_frame(plan, 5) == (20.0, 0.0)
    assert move_position_at_frame(plan, 9) == (100.0, 0.0)
