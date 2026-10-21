from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.pet_manager import PetManager


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.pets = None
        self.tray = None
        self.quit_calls = 0

    def characters(self):
        return list(self._characters)

    def character_for(self, character_id):
        for character in self._characters:
            if character.id == character_id:
                return character
        return self._characters[0]

    def build_menu(self, parent=None):
        return None

    def open_settings(self, initial_page=None):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        self.quit_calls += 1


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pair(app, tmp_path: Path):
    config = Config(tmp_path)
    config.set("character", "fallback")
    # 碰撞音效会初始化音频后端：本文件只验位置/状态，不需要声音。
    config.set("collision_sound", False)
    # 0.4 缩放（256×144）让 800×800 的离屏屏上两只宠物能真正并排贴住。
    config.set("scale", 0.4)
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    primary = manager.create_primary(fallback())
    child = manager.spawn()
    assert child is not None
    yield manager, host, primary, child
    manager.shutdown()


class _FrameClip:
    """只回答帧号的最小 clip：``_advance_move_from_frame`` 只需要它。"""

    def __init__(self, frame: int) -> None:
        self.frame = int(frame)
        self.frame_count = 10
        self.duration_seconds = 1.0

    def current_frame_number(self) -> int:
        return self.frame

    def current_image(self):
        return None


def _install_walk(window, start_x: int, target_x: int) -> None:
    window.move(int(start_x), window.y())
    window._move_plan = {
        "spec": "walk",
        "start_x": float(start_x),
        "start_y": float(window.y()),
        "target_x": float(target_x),
        "target_y": float(window.y()),
        "loops": 1,
        "frames_per_loop": 10,
        "total_frames": 10,
        "curve": None,
    }
    window._move_loop = 0
    window._move_last_frame = 0
    window._action_kind = "move"


def _set_velocity_raw(window, vx: float) -> None:
    """只写内部速度：``set_velocity`` 本身就会切 thrown，这里要的是 normal 态速度。"""
    window.motion._vx = float(vx)
    window.motion._vy = 0.0


def test_walking_pet_pushes_standing_pet_and_keeps_walking(pair) -> None:
    manager, _host, primary, child = pair
    primary.move(100, 300)
    child.move(320, 300)
    _install_walk(primary, 100, 400)

    assert manager._collide_pair(primary, child) is True
    assert child.x() != 320, "站立宠应该被推开"
    assert primary._move_plan is not None, "走路计划不得因轻碰被取消"
    dx = primary.x() - 100
    assert primary._move_plan["start_x"] == pytest.approx(100 + dx, abs=1)
    assert primary._move_plan["target_x"] == pytest.approx(400 + dx, abs=1)

    moved_from = primary.x()
    primary._clip = _FrameClip(5)
    primary._advance_move_from_frame()
    assert primary.x() > moved_from, "碰撞后走路宠必须继续推进"


def test_two_walking_pets_never_enter_thrown(pair) -> None:
    manager, _host, primary, child = pair
    primary.move(100, 320)
    child.move(320, 320)
    _install_walk(primary, 100, 420)
    _install_walk(child, 320, 20)
    _set_velocity_raw(primary, 100.0)
    _set_velocity_raw(child, -100.0)

    assert manager._collide_pair(primary, child) is True
    assert primary.motion.thrown is False
    assert child.motion.thrown is False
    assert primary.motion.mode == "normal"
    assert child.motion.mode == "normal"
    assert primary._move_plan is not None
    assert child._move_plan is not None


def test_light_contact_separates_without_teleporting(pair) -> None:
    manager, _host, primary, child = pair
    primary.move(100, 300)
    child.move(320, 300)
    _install_walk(primary, 100, 400)
    before = child.x()

    manager._collide_pair(primary, child)
    assert 0 < child.x() - before <= 12, "单 tick 分离不得超过 MAX_SEPARATION"
    assert child.motion.thrown is False


def test_walking_pet_stops_at_probing_pet_without_cancelling_probe(pair) -> None:
    manager, _host, primary, child = pair
    primary.move(300, 300)
    child.move(544, 300)  # 0.4 缩放下贴右缘（800-256）
    _install_walk(primary, 300, 520)
    _set_velocity_raw(primary, 120.0)

    child._edge_probe._mode = "PEEKING"
    child._edge_probe._side = "right"
    child._edge_probe._restore_x = child.x()
    child_before = (child.x(), child.y())

    assert manager._collide_pair(primary, child) is True
    assert child.probe_active is True, "低速接触不得取消探头"
    assert primary._move_plan is None, "走路宠遇探头宠应回待机"
    assert (child.x(), child.y()) == child_before, "探头宠按无限质量处理，不该被推动"


def test_fast_hit_on_probing_pet_still_triggers_throw_egg(pair) -> None:
    manager, _host, primary, child = pair
    primary.move(300, 300)
    child.move(544, 300)
    _set_velocity_raw(primary, 480.0)

    child._edge_probe._mode = "PEEKING"
    child._edge_probe._side = "right"
    child._edge_probe._restore_x = child.x()

    manager._collide_pair(primary, child)
    assert child.effects.throw_egg_active is True
    assert child.probe_active is False


def test_child_quit_only_closes_itself(pair) -> None:
    manager, host, primary, child = pair
    assert manager.active_slots() == [0, 1]

    child.quit_from_menu()

    assert host.quit_calls == 0, "子宠退出不得关掉整个应用"
    assert manager.active_slots() == [0]
    assert manager.windows[0] is primary
    assert primary.bubble.label.text() == "已收回这只子宠。"


def test_primary_quit_quits_the_app(pair) -> None:
    manager, host, primary, _child = pair
    primary.quit_from_menu()
    assert host.quit_calls == 1
    assert manager.active_slots() == [0, 1], "主宠退出走应用退出，不单独关窗口"
