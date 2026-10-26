from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.content.legacy import load_character
from petcore.engine.enums import GraphType
from petcore.ui.pet_window import PetWindow


class FakeHost:
    def __init__(self, character):
        self._character = character

    def characters(self):
        return [self._character]

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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_move_facing_matches_target_direction(app, tmp_path: Path) -> None:
    character = load_character("shenshen", frameseq_mode="off")
    assert character is not None
    config = Config(tmp_path)
    window = PetWindow(config, tmp_path, FakeHost(character))
    window.start(character)
    try:
        move = next(spec for spec in window.catalog.specs_for(GraphType.MOVE) if spec.locate != "in_place")
        window._play_spec(move, "move")
        plan = window._move_plan
        assert plan is not None
        assert plan["frames_per_loop"] > 0
        assert plan["curve"] is not None
        assert len(plan["curve"]) == plan["frames_per_loop"]
        direction = 1 if plan["target_x"] > plan["start_x"] else -1
        assert window.state.facing == ("right" if direction > 0 else "left")
        # 素材原生朝左：只有 facing=="right" 才镜像，否则朝向和位移会反着来。
        assert window._mirrored() is (direction > 0)
        assert abs(plan["target_x"] - plan["start_x"]) <= 240 * window.state.scale + 3
        window._cancel_move_plan()
    finally:
        window.shutdown()


def test_cold_meta_walk_advances_by_wall_clock(app, tmp_path: Path) -> None:
    """冷 meta（clip 只有一帧）时位移必须按墙钟推进，而不是首帧即到终点（AUD-33）。"""
    import time

    character = load_character("shenshen", frameseq_mode="off")
    config = Config(tmp_path)
    window = PetWindow(config, tmp_path, FakeHost(character))
    window.start(character)
    try:
        plan = {
            "spec": "walk",
            "start_x": 100.0,
            "start_y": 100.0,
            "target_x": 300.0,
            "target_y": 100.0,
            "loops": 1,
            "frames_per_loop": 1,
            "total_frames": 1,
            "curve": None,
            "duration": 0.4,
            "started_at": time.monotonic(),
        }
        window._move_plan = plan
        time.sleep(0.2)
        window._tick_move()
        assert 100 < window.x() < 300, "冷 meta 下应走一半而不是瞬移"
        window._cancel_move_plan()
    finally:
        window.shutdown()


def test_move_watchdog_finishes_a_stalled_plan(app, tmp_path: Path) -> None:
    """帧回调断流时由看门狗收口：不许永久停在走动姿态（AUD-33）。"""
    import time

    character = load_character("shenshen", frameseq_mode="off")
    config = Config(tmp_path)
    window = PetWindow(config, tmp_path, FakeHost(character))
    window.start(character)
    try:
        plan = {
            "spec": "walk",
            "start_x": 100.0,
            "start_y": 100.0,
            "target_x": 260.0,
            "target_y": 100.0,
            "loops": 1,
            "frames_per_loop": 8,
            "total_frames": 8,
            "curve": None,
            "duration": 0.05,
            "started_at": time.monotonic() - 5.0,
        }
        window._move_plan = plan
        window._tick_move()
        assert window._move_plan is None, "超时后必须收口"
    finally:
        window.shutdown()
