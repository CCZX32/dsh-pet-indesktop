"""P4 修复回归：朝向镜像、碰边反馈、多宠分离、落座、设置搜索/分页。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.engine import spawn as spawn_mod
from petcore.engine.edge import (
    EDGE_ENGAGE_TOLERANCE_PX,
    edge_side_at_rest,
    edge_snap_x,
)
from petcore.engine.physics import BOUNCE_TRIGGER_SPEED
from petcore.ui.effects import EffectController
from petcore.ui.motion import MotionController
from petcore.ui.pet_manager import PetManager
from petcore.ui.settings.tabs import SettingsTabContainer


class _Config:
    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 落座
def test_choose_spawn_position_prefers_the_right_side_when_it_fits() -> None:
    anchor = (100, 100, 120, 160)
    position = spawn_mod.choose_spawn_position(anchor, (120, 160), (0, 0, 1920, 1080))
    assert position == (100 + 120 + spawn_mod.GAP, 100)


def test_choose_spawn_position_falls_back_to_the_left_near_the_right_edge() -> None:
    anchor = (1700, 100, 120, 160)
    position = spawn_mod.choose_spawn_position(anchor, (120, 160), (0, 0, 1920, 1080))
    assert position[0] + 120 <= 1920
    assert position != (1844, 100)


def test_choose_spawn_position_skips_occupied_slots() -> None:
    anchor = (100, 100, 120, 160)
    occupied = [(244, 100, 120, 160)]
    position = spawn_mod.choose_spawn_position(anchor, (120, 160), (0, 0, 1920, 1080), occupied)
    assert position != (244, 100)


def test_choose_spawn_position_clamps_when_the_screen_is_full() -> None:
    anchor = (0, 0, 800, 600)
    position = spawn_mod.choose_spawn_position(anchor, (400, 300), (0, 0, 800, 600))
    assert 0 <= position[0] <= 400
    assert 0 <= position[1] <= 300


# ---------------------------------------------------------------- 碰边反馈
class _MotionWindow:
    def __init__(self):
        self.config = _Config({"drag_physics_enabled": True})
        self._x = 400
        self._y = 600
        self.bounces = 0
        self.moved = []
        self.probe_active = False
        self._layout = None
        self.effects = self

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return 320

    def height(self):
        return 180

    def body_local_rect(self):
        return (0, 0, 320, 180)

    def body_rect(self):
        return (self._x, self._y, 320, 180)

    def move(self, x, y):
        self._x, self._y = int(x), int(y)
        self.moved.append((self._x, self._y))

    def _on_motion_bounce(self):
        self.bounces += 1

    def update_throw_egg(self, *_args):
        return None


def test_every_ground_contact_triggers_a_bounce(app) -> None:
    window = _MotionWindow()
    motion = MotionController(window, clock=_Clock())
    motion._throw_bounds = lambda: (0.0, 0.0, 480.0, 700.0)
    motion.begin_throw(0.0, -900.0)
    now = motion._clock()
    for _ in range(200):
        now += 0.016
        motion._tick_throw(0.016, now)
        if window.bounces:
            break
    assert window.bounces == 1
    for _ in range(400):
        now += 0.016
        motion._tick_throw(0.016, now)
        if window.bounces >= 2:
            break
    assert window.bounces >= 2


def test_slow_drift_does_not_trigger_a_bounce(app) -> None:
    window = _MotionWindow()
    motion = MotionController(window, clock=_Clock())
    motion._throw_bounds = lambda: (0.0, 0.0, 480.0, 700.0)
    motion.begin_throw(0.0, 0.0)
    now = motion._clock()
    for _ in range(20):
        now += 0.016
        motion._tick_throw(0.016, now)
    assert BOUNCE_TRIGGER_SPEED > 0
    assert window.bounces == 0


# ---------------------------------------------------------------- 黄金回旋
class _EffectWindow:
    def __init__(self):
        self.config = _Config({"click_squash_enabled": True})
        self.updates = 0

    def width(self):
        return 320

    def height(self):
        return 180

    def update(self):
        self.updates += 1


def test_armed_spin_after_click_actually_ticks(app) -> None:
    controller = EffectController(_EffectWindow(), clock=_Clock())
    controller.arm_spin_after_click()
    controller.consume_click_finished()
    assert controller.spin_active is True
    assert controller._timer.isActive() is True
    controller.shutdown()


# ---------------------------------------------------------------- 贴边吸附
def test_engage_tolerance_accepts_a_landing_bounce_offset() -> None:
    bounds = (0, 0, 1280, 720)
    body = (18, 400, 120, 160)
    assert edge_side_at_rest(body, bounds) is None
    assert edge_side_at_rest(body, bounds, EDGE_ENGAGE_TOLERANCE_PX) == "left"


def test_edge_snap_x_flushes_the_body_to_each_side() -> None:
    bounds = (0, 0, 1280, 720)
    body_local = (100, 40, 120, 160)
    assert edge_snap_x("left", body_local, bounds) == -100
    assert edge_snap_x("right", body_local, bounds) == 1280 - 100 - 120


# ---------------------------------------------------------------- 多宠位置
def _fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


class _PetHost:
    def __init__(self, character):
        self.character = character
        self.pets = None
        self.config = None

    def characters(self):
        return [self.character]

    def character_for(self, _id):
        return self.character

    def build_menu(self, parent=None):
        return None

    def open_settings(self, initial_page=None):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        return None


def test_spawned_pet_stays_inside_the_screen(app, tmp_path: Path) -> None:
    character = _fallback()
    config = Config(tmp_path, {"character": "fallback", "scale": 0.5})
    host = _PetHost(character)
    host.config = config
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        primary = manager.create_primary(character)
        bounds = primary.probe_bounds()
        for _ in range(3):
            child = manager.spawn()
            assert child is not None
            bx, _by, bw, _bh = child.body_rect()
            assert bounds[0] <= bx
            assert bx + bw <= bounds[0] + bounds[2]
    finally:
        manager.shutdown()


def test_collision_separation_never_pushes_a_pet_off_screen(app, tmp_path: Path) -> None:
    character = _fallback()
    config = Config(tmp_path, {"character": "fallback", "scale": 0.5})
    host = _PetHost(character)
    host.config = config
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        primary = manager.create_primary(character)
        child = manager.spawn()
        assert child is not None
        bounds = primary.probe_bounds()
        right = bounds[0] + bounds[2]
        # 把两只叠在右边缘，强制分离后谁都不许出屏。
        bx, _by, bw, _bh = primary.body_local_rect()
        primary.move(int(right - bx - bw), primary.y())
        child.move(int(right - bw - bx - 40), child.y())
        for _ in range(30):
            manager._tick_collision()
            for window in (primary, child):
                cx, _cy, cw, _ch = window.body_rect()
                assert cx >= bounds[0]
                assert cx + cw <= right + 1
    finally:
        manager.shutdown()


# ---------------------------------------------------------------- 设置层
def test_tab_bar_scrolls_when_the_window_is_narrow(app) -> None:
    host = QWidget()
    host.resize(480, 200)
    from PySide6.QtWidgets import QVBoxLayout

    layout = QVBoxLayout(host)
    tabs = SettingsTabContainer(host)
    layout.addWidget(tabs)
    for index in range(8):
        tabs.addTab(f"tab{index}", f"分页 {index}", QLabel(f"page {index}"))
    host.show()
    app.processEvents()
    bar = tabs.tab_scroll.horizontalScrollBar()
    assert bar.maximum() > 0
    tabs.setCurrentIndex(7)
    app.processEvents()
    assert bar.value() > 0
    host.close()


def test_sound_player_reuses_a_prepared_effect(app, tmp_path: Path) -> None:
    from petcore.media.sound import SoundPlayer

    sample = tmp_path / "click.wav"
    sample.write_bytes(b"RIFF0000WAVE")
    player = SoundPlayer(0.5)
    assert player.prepare(sample) is True
    assert player.play(sample) is True
    assert player.play(sample) is True
    assert len(player._cache) == 1
    assert player.play(tmp_path / "missing.wav") is False
