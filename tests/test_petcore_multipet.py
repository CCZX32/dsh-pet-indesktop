from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.pet_manager import PetManager


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.pets = None

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
        return None


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_spawn_restore_and_close(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("character", "fallback")
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        primary = manager.create_primary(fallback())
        assert primary.slot == 0
        assert manager.active_slots() == [0]
        child = manager.spawn()
        assert child is not None
        assert child.slot == 1
        assert manager.active_slots() == [0, 1]
        assert paths.pet_config_path(tmp_path, 1).exists()
        assert child.config.get("character") == "fallback"
        assert config.get("active_pets") == [0, 1]
        assert manager.close_slot(1) is True
        assert manager.active_slots() == [0]
        assert config.get("active_pets") == [0]
    finally:
        manager.shutdown()


def test_spawn_stops_at_limit(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("active_pets", [0])
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        manager.create_primary(fallback())
        for _ in range(20):
            manager.spawn()
        assert len(manager.each()) == 16
        assert manager.spawn() is None
    finally:
        manager.shutdown()


def test_seed_config_inherits_and_overrides_size(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("spawn_inherit_size", False)
    config.set("spawn_scale", 1.25)
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        manager.create_primary(fallback())
        child = manager.spawn()
        assert child is not None
        assert child.config.get("scale") == pytest.approx(1.25)
        assert child.config.get("character") == "shenshen"
    finally:
        manager.shutdown()


def test_restore_reads_active_pets(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("active_pets", [0, 1])
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        manager.create_primary(fallback())
        manager.seed_config(1)
        manager.restore()
        assert manager.active_slots() == [0, 1]
    finally:
        manager.shutdown()


def test_collision_pair_separates_two_pets(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    host = FakeHost([fallback()])
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    try:
        primary = manager.create_primary(fallback())
        child = manager.spawn()
        assert child is not None
        child.move(primary.x() + 10, primary.y())
        before = (primary.x(), child.x())
        manager._collide_pair(primary, child)
        assert (primary.x(), child.x()) != before
    finally:
        manager.shutdown()
