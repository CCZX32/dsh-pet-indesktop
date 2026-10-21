from __future__ import annotations

from petcore.engine.geometry import (
    body_at,
    body_local_rect,
    body_position_ratio,
    clamp_body,
    clamp_body_to_screens,
)

SHENSHEN = (212, 60, 428, 330)
LEFT = (0, 0, 1920, 1080)
UPPER = (1920, -800, 2560, 1440)


def test_body_local_rect_falls_back_to_the_whole_window():
    assert body_local_rect(None, 0.72) == (0, 0, 461, 259)


def test_body_local_rect_scales_the_manifest_box():
    assert body_local_rect(SHENSHEN, 0.72) == (153, 43, 156, 194)
    assert body_local_rect(SHENSHEN, 1.0) == (212, 60, 216, 270)


def test_clamp_body_puts_the_visible_body_on_the_screen_edge():
    body = body_local_rect(SHENSHEN, 0.72)
    left = clamp_body(-9999, -9999, body, LEFT)
    right = clamp_body(9999, 9999, body, LEFT)

    assert body_at(*left, body) == (0, 0, 156, 194)
    assert body_at(*right, body) == (1764, 886, 156, 194)
    assert right[0] + body[0] + body[2] == LEFT[2]
    assert right[0] < LEFT[2] - body[2]


def test_clamp_body_treats_an_oversized_body_as_flush_left_top():
    body = (10, 20, 2500, 2000)
    assert clamp_body(-9999, -9999, body, LEFT) == (-10, -20)


def test_body_position_ratio_round_trips_through_the_legal_span():
    body = body_local_rect(SHENSHEN, 0.72)
    x, y = clamp_body(-9999, -9999, body, LEFT)
    rx, ry = body_position_ratio(x, y, 461, 259, LEFT, body)
    assert (rx, ry) == (0.0, 0.0)

    x2 = round(LEFT[0] - body[0] + rx * (LEFT[2] - body[2]))
    y2 = round(LEFT[1] - body[1] + ry * (LEFT[3] - body[3]))
    assert (x2, y2) == (x, y)


def test_multi_screen_allows_body_across_a_connected_seam():
    body = body_local_rect(SHENSHEN, 0.72)
    seam_x = LEFT[2] - body[0] - body[2] // 2
    assert clamp_body_to_screens(seam_x, 100, body, (LEFT, UPPER)) == (seam_x, 100)


def test_multi_screen_pushes_out_of_a_desktop_hole():
    body = body_local_rect(SHENSHEN, 0.72)
    # (2000, 800) 落在 Left 右侧与 Upper 下侧之间的空洞里。
    assert clamp_body_to_screens(2000, 800, body, (LEFT, UPPER)) == (1611, 800)
