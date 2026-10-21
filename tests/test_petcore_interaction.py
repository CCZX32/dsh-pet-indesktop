from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.engine import physics
from petcore.engine.collision import CollisionBody, collide
from petcore.engine.feeding import ScanBudget, format_bytes, measure_paths, pick_eating_animation
from petcore.engine.spin import eased_progress, spin_angle
from petcore.engine.squash import squash_geometry
from petcore.ui.pet_window import PetWindow


class FakeHost:
    def __init__(self, characters):
        self._characters = characters

    def characters(self):
        return list(self._characters)

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


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    config = Config(tmp_path)
    instance = PetWindow(config, tmp_path, FakeHost([fallback()]))
    instance.start(fallback())
    yield instance
    instance.shutdown()


def test_squash_geometry_is_bottom_centered() -> None:
    x, y, width, height = squash_geometry(640, 360, 640, 360, 0.5)
    assert width > 640
    assert height < 360
    assert x + width // 2 == pytest.approx(320, abs=1)
    assert y + height == 360


def test_spring_and_release_velocity() -> None:
    velocity = physics.spring_velocity(0.0, 0.0, 100.0, 0.016)
    assert velocity > 0.0
    trail = [(0.0, 0.0, 0.0), (0.02, 10.0, 0.0), (0.04, 20.0, 0.0)]
    vx, vy = physics.estimate_release_velocity(trail, 0.04)
    assert vx > 0.0
    assert abs(vy) < 1e-6


def test_throw_bounces_and_rests() -> None:
    px, py, vx, vy, bounced = physics.throw_step(
        100.0, 350.0, 0.0, 0.0, 0.1, 0.0, 0.0, 640.0, 360.0
    )
    assert bounced is True
    assert py == 360.0
    assert not physics.is_at_rest(py, vx, vy, 360.0, bounced, math.hypot(vx, vy))
    assert physics.is_at_rest(360.0, 0.0, 0.0, 360.0, True, 0.0)


def test_slingshot_deformation_and_trajectory() -> None:
    sx, sy = physics.slingshot_deformation(100.0, 0.0, 0.5)
    assert sx > 1.0
    assert sy < 1.0
    points = physics.slingshot_trajectory(300.0, -100.0)
    assert len(points) == 12
    assert points[0] == (0.0, 0.0)


def test_spin_progress_is_monotonic() -> None:
    assert eased_progress(0.0, 700.0) == 0.0
    assert eased_progress(700.0, 700.0) == 1.0
    assert spin_angle(0.0) == 0.0
    assert spin_angle(1.0) == -360.0


def test_collision_separates_and_exchanges_velocity() -> None:
    a = CollisionBody(0, 0, 100, 100, vx=200.0, vy=0.0)
    b = CollisionBody(40, 0, 100, 100, vx=-200.0, vy=0.0)
    result = collide(a, b)
    assert result is not None
    assert result.depth > 0
    assert result.ax < result.bx
    assert result.impact_speed > 0


def test_dragging_body_is_infinite_mass() -> None:
    a = CollisionBody(0, 0, 100, 100, dragging=True)
    b = CollisionBody(40, 0, 100, 100)
    result = collide(a, b)
    assert result is not None
    assert result.ax == pytest.approx(a.x)
    assert result.bx > b.x


def test_feeding_budget_and_helpers(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "b.txt").write_text("y" * 20, encoding="utf-8")
    report = measure_paths([tmp_path])
    assert report.files == 2
    assert report.folders >= 1
    assert report.total_bytes >= 30
    assert format_bytes(2048) == "2.0 KB"
    assert pick_eating_animation(["吃Token", "idle"]) == "吃Token"
    budget = ScanBudget(file_limit=1)
    assert budget.account_file() is True
    assert budget.account_file() is False
    assert budget.truncated is True


def test_click_starts_squash_and_spin(window) -> None:
    window.config.set("golden_spin_on_click", True)
    window._on_click()
    assert window.effects.squash_active is True
    assert window.effects.spin_pending is True
    window.effects.start_spin(direct=True)
    assert window.effects.spin_active is True


def test_slingshot_enters_and_launches(window) -> None:
    window.dragging = True
    window.motion.begin_drag(window.x(), window.y())
    assert window.slingshot.maybe_enter(QPointF(100, 100), QPointF(100, 100)) is True
    window.slingshot.update(QPointF(20, 100))
    assert window.slingshot.distance() == pytest.approx(80.0)
    assert window.slingshot.launch() is True
    assert window.motion.thrown is True


def test_config_normalizes_interaction_keys(tmp_path: Path) -> None:
    config = Config(tmp_path, {"playback_speed": 9.0, "throw_strength": "nope", "active_pets": [9, 2, 2]})
    assert config.get("playback_speed") == 2.0
    assert config.get("throw_strength") == "standard"
    assert config.get("active_pets") == [0, 2, 9]
