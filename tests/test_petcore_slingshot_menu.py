from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.engine import physics
from petcore.ui.pet_window import PetWindow


class MenuStub:
    def __init__(self) -> None:
        self.executed = 0

    def exec(self, *_args) -> None:
        self.executed += 1


class FakeHost:
    def __init__(self) -> None:
        self.build_calls = 0
        self.menus: list[MenuStub] = []

    def characters(self):
        return []

    def character_for(self, character_id):
        return None

    def build_menu(self, parent=None):
        self.build_calls += 1
        menu = MenuStub()
        self.menus.append(menu)
        return menu

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


def _fallback() -> CharacterSpec:
    return CharacterSpec(
        id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=()
    )


def _window(tmp_path: Path) -> tuple[PetWindow, FakeHost]:
    config = Config(tmp_path)
    host = FakeHost()
    window = PetWindow(config, tmp_path, host)
    window._activate(_fallback())
    return window, host


def _press(window: PetWindow, button: Qt.MouseButton) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(event)


def _release_left(window: PetWindow) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseReleaseEvent(event)


def _context_menu(window: PetWindow) -> QContextMenuEvent:
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(10, 10), QPoint(10, 10)
    )
    window.contextMenuEvent(event)
    return event


def test_context_menu_is_suppressed_after_slingshot_launch(app, tmp_path: Path) -> None:
    window, host = _window(tmp_path)
    try:
        window.dragging = True
        _press(window, Qt.MouseButton.RightButton)
        assert window.slingshot.aiming is True

        window.slingshot.update(QPointF(10, 10 + physics.SLINGSHOT_MIN_DISTANCE + 60))
        _release_left(window)
        assert window.slingshot.aiming is False

        _context_menu(window)

        assert host.build_calls == 0
        assert window.slingshot.suppresses_context_menu() is True
    finally:
        window.shutdown()


def test_plain_right_click_still_builds_the_menu(app, tmp_path: Path) -> None:
    window, host = _window(tmp_path)
    try:
        assert window.slingshot.suppresses_context_menu() is False

        _context_menu(window)

        assert host.build_calls == 1
        assert host.menus[0].executed == 1
    finally:
        window.shutdown()


def test_right_click_while_aiming_cancels_without_menu(app, tmp_path: Path) -> None:
    window, host = _window(tmp_path)
    try:
        window.dragging = True
        _press(window, Qt.MouseButton.RightButton)
        assert window.slingshot.aiming is True

        _context_menu(window)

        assert host.build_calls == 0
        assert window.slingshot.aiming is False
    finally:
        window.shutdown()
