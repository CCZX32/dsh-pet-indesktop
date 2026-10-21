from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from petcore.engine.geometry import body_local_rect
from petcore.platform.screens import (
    ScreenInfo,
    ScreenLayout,
    adopt_position,
    clamp_rect,
    migrate_layout,
    nearest_screen,
    position_ratio,
    restore_position,
    screen_for_rect,
    snapshot_from_qt,
)

LEFT = ScreenInfo("Left", 0, 0, 1920, 1080)
RIGHT = ScreenInfo("Right", 1920, 0, 2560, 1440)
WIDTH = 640
HEIGHT = 360


def _side_by_side() -> ScreenLayout:
    return ScreenLayout((LEFT, RIGHT), "Left")


def _stacked() -> ScreenLayout:
    top = ScreenInfo("Top", 0, 0, 1920, 1080)
    bottom = ScreenInfo("Bottom", 0, 1080, 1920, 1080)
    return ScreenLayout((top, bottom), "Top")


def _offset_with_hole() -> ScreenLayout:
    upper = ScreenInfo("Upper", 1920, -800, 2560, 1440)
    return ScreenLayout((LEFT, upper), "Left")


def _diagonal() -> ScreenLayout:
    lower = ScreenInfo("Lower", 1920, 1080, 1920, 1080)
    return ScreenLayout((LEFT, lower), "Left")


def _negative_primary() -> ScreenLayout:
    main = ScreenInfo("Main", -1920, -120, 1920, 1080)
    right = ScreenInfo("Right", 0, 0, 2560, 1440)
    return ScreenLayout((main, right), "Main")


def _three_way_tie() -> ScreenLayout:
    center = ScreenInfo("Center", 0, 2000, 100, 100)
    alpha = ScreenInfo("Alpha", 0, 0, 1000, 1000)
    beta = ScreenInfo("Beta", 1000, 0, 1000, 1000)
    return ScreenLayout((center, alpha, beta), "Center")


ALL_LAYOUTS = [_side_by_side, _stacked, _offset_with_hole, _diagonal, _negative_primary]


def _state(**values):
    defaults = {"screen_name": None, "rx": None, "ry": None, "pos_x": None, "pos_y": None}
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_screen_info_edges_and_center():
    assert LEFT.rect == (0, 0, 1920, 1080)
    assert LEFT.right == 1920
    assert LEFT.bottom == 1080
    assert LEFT.center == (960, 540)
    assert RIGHT.center == (3200, 720)

    negative = ScreenInfo("Negative", -1920, -120, 1920, 1080)
    assert negative.right == 0
    assert negative.bottom == 960
    assert negative.center == (-960, 420)


def test_layout_lookup_helpers():
    layout = _side_by_side()
    assert layout.by_name("Right") == RIGHT
    assert layout.by_name("Missing") is None
    assert layout.by_name(None) is None
    assert layout.contains("Left")
    assert not layout.contains("Missing")
    assert layout.rects() == ((0, 0, 1920, 1080), (1920, 0, 2560, 1440))


class _FakeGeometry:
    def __init__(self, x, y, width, height):
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._width

    def height(self):
        return self._height


class _FakeScreen:
    def __init__(self, name, geometry, dpr):
        self._name = name
        self._geometry = geometry
        self._dpr = dpr

    def name(self):
        return self._name

    def availableGeometry(self):
        return self._geometry

    def devicePixelRatio(self):
        return self._dpr


class _FakeApp:
    def __init__(self, screens, primary):
        self._screens = screens
        self._primary = primary

    def screens(self):
        return list(self._screens)

    def primaryScreen(self):
        return self._primary


def test_snapshot_from_qt_reads_logical_geometry():
    left = _FakeScreen("Left", _FakeGeometry(0, 0, 1920, 1080), 1.25)
    right = _FakeScreen("Right", _FakeGeometry(1920, -200, 2560, 1440), 1.0)

    layout = snapshot_from_qt(_FakeApp([left, right], right))

    assert layout == ScreenLayout(
        (
            ScreenInfo("Left", 0, 0, 1920, 1080, 1.25),
            ScreenInfo("Right", 1920, -200, 2560, 1440, 1.0),
        ),
        "Right",
    )


def test_snapshot_from_qt_without_screens():
    assert snapshot_from_qt(_FakeApp([], None)) == ScreenLayout((), "")


@pytest.mark.parametrize("factory", ALL_LAYOUTS)
def test_clamp_rect_keeps_window_inside_each_screen(factory):
    layout = factory()
    for screen in layout.screens:
        inside = (screen.x + 10, screen.y + 10, WIDTH, HEIGHT)
        assert clamp_rect(inside, screen) == inside

        beyond_left_top = (screen.x - 500, screen.y - 500, WIDTH, HEIGHT)
        assert clamp_rect(beyond_left_top, screen) == (screen.x, screen.y, WIDTH, HEIGHT)

        beyond_right_bottom = (screen.right + 500, screen.bottom + 500, WIDTH, HEIGHT)
        assert clamp_rect(beyond_right_bottom, screen) == (screen.right - WIDTH, screen.bottom - HEIGHT, WIDTH, HEIGHT)

        oversized = (screen.x - 100, screen.y - 100, screen.width + 100, screen.height + 100)
        assert clamp_rect(oversized, screen) == (screen.x, screen.y, screen.width + 100, screen.height + 100)


def test_clamp_rect_on_negative_origin_screens():
    layout = _negative_primary()
    main = layout.by_name("Main")
    assert (main.x, main.y) == (-1920, -120)

    clamped = clamp_rect((-5000, -5000, WIDTH, HEIGHT), main)
    assert clamped == (-1920, -120, WIDTH, HEIGHT)
    assert main.x <= clamped[0] and clamped[0] + WIDTH <= main.right
    assert main.y <= clamped[1] and clamped[1] + HEIGHT <= main.bottom

    upper = ScreenInfo("Upper", 0, -1440, 1920, 1080)
    assert clamp_rect((0, -5000, WIDTH, HEIGHT), upper) == (0, -1440, WIDTH, HEIGHT)


def test_screen_for_rect_picks_largest_overlap():
    layout = _side_by_side()
    assert screen_for_rect((100, 100, WIDTH, HEIGHT), layout) == LEFT
    assert screen_for_rect((2200, 100, WIDTH, HEIGHT), layout) == RIGHT
    assert screen_for_rect((1800, 100, WIDTH, HEIGHT), layout) == RIGHT


def test_screen_for_rect_tie_breaks_by_primary_then_name():
    assert screen_for_rect((1720, 500, 400, 200), _side_by_side()) == LEFT

    three = _three_way_tie()
    assert screen_for_rect((900, 100, 200, 100), three).name == "Alpha"


def test_screen_for_rect_falls_back_to_nearest_in_desktop_hole():
    layout = _offset_with_hole()

    assert screen_for_rect((2000, 800, WIDTH, 200), layout) == LEFT
    assert screen_for_rect((3000, 900, 100, 100), layout).name == "Upper"
    assert screen_for_rect((5000, 3000, 100, 100), _side_by_side()) == RIGHT


def test_screen_for_rect_nearest_tie_breaks_by_name():
    three = _three_way_tie()
    assert screen_for_rect((995, 1200, 10, 10), three).name == "Alpha"


def test_screen_for_rect_empty_layout():
    assert screen_for_rect((0, 0, WIDTH, HEIGHT), ScreenLayout((), "")) is None


def test_nearest_screen_uses_distance_and_excludes():
    layout = _offset_with_hole()
    hole_rect = (2000, 800, WIDTH, 200)

    assert nearest_screen(hole_rect, layout) == LEFT
    assert nearest_screen(hole_rect, layout, exclude=("Left",)).name == "Upper"
    assert nearest_screen(hole_rect, layout, exclude=("Left", "Upper")) is None
    assert nearest_screen((100, 100, WIDTH, HEIGHT), layout) == LEFT


def test_nearest_screen_ties_break_by_name():
    assert nearest_screen((995, 1200, 10, 10), _three_way_tie()).name == "Alpha"


def test_restore_by_name_uses_ratios():
    state = _state(screen_name="Right", rx=1.0, ry=1.0)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (3840, 1080, "Right")


def test_restore_screen_name_wins_over_position():
    state = _state(screen_name="Left", rx=0.0, ry=0.0, pos_x=2500, pos_y=100)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (0, 0, "Left")


def test_restore_by_absolute_position():
    state = _state(pos_x=2200, pos_y=100)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (2200, 100, "Right")


def test_restore_by_ratios_without_absolute_position():
    state = _state(screen_name="Right", rx=0.25, ry=0.5)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (2400, 540, "Right")


def test_restore_partial_state_fills_missing_axis_from_corner():
    state = _state(screen_name="Right", rx=0.25)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (2400, 1056, "Right")


def test_restore_missing_screen_falls_back_to_primary():
    state = _state(screen_name="Gone", rx=0.0, ry=0.0)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (0, 0, "Left")


def test_restore_all_missing_uses_bottom_right_margin():
    state = _state()
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (1256, 696, "Left")


def test_restore_position_outside_every_screen_is_clamped_onto_primary():
    state = _state(pos_x=5000, pos_y=2000)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (1280, 720, "Left")


def test_restore_accepts_mapping_state():
    state = {"screen_name": "Right", "rx": 0.5, "ry": 0.0}
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (2880, 0, "Right")


def test_restore_empty_layout():
    assert restore_position(_state(), ScreenLayout((), ""), WIDTH, HEIGHT) == (0, 0, "")


def test_position_ratio_round_trip():
    screen = RIGHT
    x, y = 2400, 540

    rx, ry = position_ratio(x, y, WIDTH, HEIGHT, screen)

    assert (rx, ry) == (0.25, 0.5)
    state = _state(screen_name=screen.name, rx=rx, ry=ry)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (x, y, "Right")


def test_position_ratio_corners_round_trip():
    screen = RIGHT
    for x, y, expected in (
        (screen.x, screen.y, (0.0, 0.0)),
        (screen.right - WIDTH, screen.bottom - HEIGHT, (1.0, 1.0)),
    ):
        ratios = position_ratio(x, y, WIDTH, HEIGHT, screen)
        assert ratios == expected
        state = _state(screen_name=screen.name, rx=ratios[0], ry=ratios[1])
        assert restore_position(state, _side_by_side(), WIDTH, HEIGHT) == (x, y, "Right")


def test_position_ratio_clamps_and_guards_oversized_windows():
    screen = RIGHT
    assert position_ratio(screen.x - 500, screen.bottom, WIDTH, HEIGHT, screen) == (0.0, 1.0)
    assert position_ratio(screen.right, screen.y - 500, WIDTH, HEIGHT, screen) == (1.0, 0.0)
    assert position_ratio(0, 0, screen.width, screen.height, screen) == (0.0, 0.0)
    assert position_ratio(0, 0, screen.width + 1, screen.height + 1, screen) == (0.0, 0.0)


def test_adopt_keeps_body_on_the_screen_under_it():
    layout = _side_by_side()
    assert adopt_position(2200, 100, WIDTH, HEIGHT, layout, "Left") == (2200, 100, "Right")
    assert adopt_position(100, 100, WIDTH, HEIGHT, layout, "Right") == (100, 100, "Left")


def test_adopt_chooses_majority_screen_and_clamps():
    layout = _side_by_side()
    assert adopt_position(1800, 100, WIDTH, HEIGHT, layout, "Left") == (1920, 100, "Right")


def test_adopt_clamps_body_hanging_off_the_edge():
    layout = _side_by_side()
    assert adopt_position(4000, 1200, WIDTH, HEIGHT, layout, "Right") == (3840, 1080, "Right")


def test_adopt_in_desktop_hole_keeps_current_screen():
    layout = _offset_with_hole()
    assert adopt_position(2000, 800, WIDTH, 200, layout, "Upper") == (2000, 440, "Upper")


def test_adopt_in_desktop_hole_falls_back_to_nearest_screen():
    layout = _offset_with_hole()
    assert adopt_position(2000, 800, WIDTH, 200, layout, "Gone") == (1280, 800, "Left")


def test_adopt_empty_layout():
    assert adopt_position(50, 60, WIDTH, HEIGHT, ScreenLayout((), ""), "Right") == (50, 60, "Right")


def test_migrate_layout_moves_pet_from_removed_screen_to_primary():
    previous = _side_by_side()
    current = ScreenLayout((LEFT,), "Left")
    state = _state(screen_name="Right", rx=0.5, ry=0.5)

    assert migrate_layout(previous, current, state, WIDTH, HEIGHT) == (640, 360, "Left")


def test_migrate_layout_keeps_existing_screen():
    previous = ScreenLayout((LEFT,), "Left")
    current = _side_by_side()
    state = _state(screen_name="Right", rx=0.5, ry=0.5)

    assert migrate_layout(previous, current, state, WIDTH, HEIGHT) is None


def test_migrate_layout_uses_saved_position_when_its_screen_is_gone():
    previous = ScreenLayout((LEFT,), "Left")
    current = _side_by_side()
    state = _state(screen_name="Gone", pos_x=2200, pos_y=100)

    assert migrate_layout(previous, current, state, WIDTH, HEIGHT) == (2200, 100, "Right")


def test_migrate_layout_without_saved_screen_is_a_noop():
    assert migrate_layout(_side_by_side(), _side_by_side(), _state(), WIDTH, HEIGHT) is None


def test_migrate_layout_with_empty_current_layout():
    state = _state(screen_name="Right")
    assert migrate_layout(_side_by_side(), ScreenLayout((), ""), state, WIDTH, HEIGHT) is None


BODY = body_local_rect((212, 60, 428, 330), 0.72)


def test_restore_body_ratio_puts_the_body_on_the_screen_corner():
    state = _state(screen_name="Right", body_rx=0.0, body_ry=0.0)
    x, y, name = restore_position(state, _side_by_side(), WIDTH, HEIGHT, body_local=BODY)
    assert name == "Right"
    assert (x, y) == (RIGHT.x - BODY[0], RIGHT.y - BODY[1])
    assert (x + BODY[0], y + BODY[1]) == (RIGHT.x, RIGHT.y)

    state = _state(screen_name="Right", body_rx=1.0, body_ry=1.0)
    x, y, _ = restore_position(state, _side_by_side(), WIDTH, HEIGHT, body_local=BODY)
    assert (x + BODY[0] + BODY[2], y + BODY[1] + BODY[3]) == (RIGHT.right, RIGHT.bottom)


def test_restore_legacy_ratio_still_uses_the_window_formula():
    state = _state(screen_name="Right", rx=0.0, ry=0.0)
    assert restore_position(state, _side_by_side(), WIDTH, HEIGHT, body_local=BODY) == (1920, 0, "Right")


def test_migrate_layout_passes_body_local_to_restore():
    current = ScreenLayout((LEFT,), "Left")
    state = _state(screen_name="Right", body_rx=0.5, body_ry=0.5)
    x, y, name = migrate_layout(
        _side_by_side(), current, state, WIDTH, HEIGHT, body_local=BODY
    )
    assert name == "Left"
    assert (x, y) == (729, 400)


def test_adopt_position_clamps_the_body_not_the_canvas():
    assert adopt_position(
        4600, 1400, WIDTH, HEIGHT, _side_by_side(), "Right", body_local=BODY
    ) == (4171, 1203, "Right")


def test_dpr_does_not_change_logical_geometry():
    base = _side_by_side()
    scaled = ScreenLayout(
        (replace(LEFT, dpr=2.0), replace(RIGHT, dpr=1.5)),
        "Left",
    )
    state = _state(screen_name="Right", rx=0.25, ry=0.75)
    rect = (2200, 100, WIDTH, HEIGHT)

    assert scaled.rects() == base.rects()
    assert screen_for_rect(rect, scaled).rect == screen_for_rect(rect, base).rect
    assert screen_for_rect(rect, scaled).name == screen_for_rect(rect, base).name
    assert nearest_screen(rect, scaled).rect == nearest_screen(rect, base).rect
    assert nearest_screen(rect, scaled).name == nearest_screen(rect, base).name
    assert clamp_rect(rect, scaled.by_name("Right")) == clamp_rect(rect, base.by_name("Right"))
    assert restore_position(state, scaled, WIDTH, HEIGHT) == restore_position(state, base, WIDTH, HEIGHT)
    assert position_ratio(2200, 100, WIDTH, HEIGHT, scaled.by_name("Right")) == position_ratio(
        2200, 100, WIDTH, HEIGHT, base.by_name("Right")
    )
