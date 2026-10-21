from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.config import Config
from petcore.content.legacy import load_character
from petcore.contracts.content import CharacterSpec
from petcore.platform.screens import ScreenInfo, ScreenLayout
from petcore.ui.menu import install_core_menu
from petcore.ui.menu_model import MenuModel
from petcore.ui.pet_window import PetWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeHost:
    def __init__(self, characters: list[CharacterSpec]):
        self._characters = characters
        self.menu_model = MenuModel()
        self.opened: list[str] = []

    def characters(self):
        return list(self._characters)

    def build_menu(self, parent=None):
        return self.menu_model.build(parent)

    def open_settings(self):
        self.opened.append("settings")

    def reload_mods(self):
        self.opened.append("reload")

    def open_data_dir(self):
        self.opened.append("data")

    def show_about(self):
        self.opened.append("about")

    def quit_app(self):
        self.opened.append("quit")


def _fallback() -> CharacterSpec:
    return CharacterSpec(
        id="fallback",
        name="Fallback",
        root=Path("."),
        media_kind="none",
        animations=(),
    )


def _window(tmp_path: Path, character: CharacterSpec) -> tuple[PetWindow, FakeHost, Config]:
    config = Config(tmp_path)
    config.set("character", character.id)
    config.save()
    host = FakeHost([character])
    window = PetWindow(config, tmp_path, host)
    install_core_menu(host.menu_model, window)
    return window, host, config


def test_fallback_window_shows_animated_frame(qapp, tmp_path) -> None:
    window, _host, _config = _window(tmp_path, _fallback())
    window.start(_fallback())
    QTest.qWait(300)
    assert window.isVisible()
    assert window._pixmap is not None
    assert window.width() > 0 and window.height() > 0
    window.shutdown()


def test_scale_switch_persists_and_resizes(qapp, tmp_path) -> None:
    window, _host, config = _window(tmp_path, _fallback())
    window.start(_fallback())
    window.set_scale(0.85)
    QTest.qWait(50)
    assert config.get("scale") == pytest.approx(0.85)
    assert window.width() == round(640 * 0.85)
    window.set_scale(0.5)
    assert config.get("scale") == pytest.approx(0.5)
    window.shutdown()


def test_hide_and_show_round_trip(qapp, tmp_path) -> None:
    window, _host, _config = _window(tmp_path, _fallback())
    window.start(_fallback())
    window.toggle_hidden()
    assert not window.isVisible()
    window.toggle_hidden()
    assert window.isVisible()
    window.shutdown()


def test_click_through_toggle_updates_config(qapp, tmp_path) -> None:
    window, _host, config = _window(tmp_path, _fallback())
    window.start(_fallback())
    window.toggle_click_through()
    assert config.get("click_through") is True
    window.toggle_click_through()
    assert config.get("click_through") is False
    window.shutdown()


@pytest.mark.skipif(
    not (paths.legacy_characters_root() / "shenshen" / "videos").is_dir(),
    reason="legacy character assets not present",
)
def _body_character() -> CharacterSpec:
    return CharacterSpec(
        id="body",
        name="Body",
        root=Path("."),
        media_kind="none",
        animations=(),
        body_box=(212, 60, 428, 330),
    )


def test_body_box_clamps_to_the_visible_body_not_the_canvas(qapp, tmp_path) -> None:
    character = _body_character()
    window, _host, config = _window(tmp_path, character)
    window.start(character)
    config.set("screen_name", "Only")
    window._layout = ScreenLayout((ScreenInfo("Only", 0, 0, 1920, 1080),), "Only")
    try:
        assert window.body_local_rect() == (153, 43, 156, 194)
        left = window._clamp_position(-9999, -9999)
        right = window._clamp_position(9999, 9999)
        assert left == (-153, -43)
        assert right == (1611, 843)
        assert left[0] + 153 == 0
        assert right[0] + 153 + 156 == 1920
    finally:
        window.shutdown()


def test_corner_falls_back_to_the_old_window_margin_without_body_box(qapp, tmp_path) -> None:
    character = _fallback()
    window, _host, _config = _window(tmp_path, character)
    window.start(character)
    try:
        screen = ScreenInfo("Only", 0, 0, 1280, 752)
        x, y = window._corner_position(screen)
        assert (x, y) == (1280 - window.width() - 24, 752 - window.height() - 24)
    finally:
        window.shutdown()


def test_corner_uses_the_visible_body(qapp, tmp_path) -> None:
    character = _body_character()
    window, _host, _config = _window(tmp_path, character)
    window.start(character)
    try:
        screen = ScreenInfo("Only", 0, 0, 1920, 1080)
        x, y = window._corner_position(screen)
        assert (x, y) == (1587, 843)
        assert x + 153 + 156 == 1896
        assert y + 43 + 194 == 1080
    finally:
        window.shutdown()


def test_legacy_character_plays_webm(qapp, tmp_path) -> None:
    character = load_character("shenshen", frameseq_mode="off")
    assert character is not None
    window, _host, _config = _window(tmp_path, character)
    window.start(character)
    for _ in range(100):
        if window._image is not None:
            break
        QTest.qWait(50)
    assert window._clip is not None
    assert window._image is not None
    window.shutdown()
