"""多气泡序列：PetWindow 的定时器推进与 presentation 端口的行为。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.app import _PresentationAdapter
from petcore.ui.pet_window import PetWindow


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.pets = None
        self.tray = None

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
    return CharacterSpec(
        id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=()
    )


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    config = Config(tmp_path)
    instance = PetWindow(config, tmp_path, FakeHost([fallback()]))
    instance.start(fallback())
    instance.move(200, 420)
    yield instance
    instance.shutdown()


def test_sequence_advances_and_a_new_say_cancels_it(app, window) -> None:
    shown: list[str] = []
    assert window.say_sequence(
        [("one", "一", 800), ("two", "二", 800), ("three", "三", 800)],
        gap_ms=0,
        on_show=shown.append,
    )

    assert window.bubble.full_text() == "one"
    assert window.bubble.subtitle_text() == "一"
    QTest.qWait(900)
    assert window.bubble.full_text() == "two"
    assert shown[:2] == ["one", "two"]

    window.say("打断")
    QTest.qWait(900)
    assert window.bubble.full_text() == "打断"
    assert shown == ["one", "two"], "新的 say() 必须取消剩余条目"


def test_hiding_the_pet_cancels_the_sequence(app, window) -> None:
    assert window.say_sequence([("a", "", 800), ("b", "", 800)], gap_ms=0)
    window.set_visible(False)
    assert window._say_sequence_items == deque_empty()
    QTest.qWait(900)
    assert window.bubble.isVisible() is False
    window.set_visible(True)


def deque_empty():
    from collections import deque

    return deque()


def test_image_cancels_the_sequence(app, window, tmp_path: Path) -> None:
    from PySide6.QtGui import QColor, QImage

    image_path = tmp_path / "pic.png"
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor("#30a0ff"))
    assert image.save(str(image_path))

    assert window.say_sequence([("a", "", 800), ("b", "", 800)], gap_ms=0)
    assert window.show_image(image_path, "图", 800)
    assert window._say_sequence_items == deque_empty()


class FakeIsland:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def add_message(self, text: str) -> None:
        self.messages.append(text)


class FakeQuiet:
    def __init__(self, active: bool) -> None:
        self.active = active

    def quiet_active(self) -> bool:
        return self.active


class FakeWindow:
    def __init__(self) -> None:
        self.lines: list = []
        self.calls: list[str] = []

    def isVisible(self) -> bool:
        return True

    def say(self, text, duration_ms=4000, *, subtitle=""):
        self.calls.append(text)
        return True

    def say_sequence(self, lines, *, on_show=None):
        self.lines = list(lines)
        for text, _subtitle, _duration in lines:
            if on_show is not None:
                on_show(text)
        return True


def test_presentation_adapter_forwards_lines_and_island_messages() -> None:
    window = FakeWindow()
    island = FakeIsland()
    host = SimpleNamespace(
        _active_window=window,
        window=window,
        pets=None,
        quiet=FakeQuiet(False),
        settings_dialog=None,
        island=island,
    )
    adapter = _PresentationAdapter(host)

    assert adapter.say_sequence([("a", "甲", 900), (" b ", "乙", 1200)]) is True
    assert window.lines == [("a", "甲", 900), ("b", "乙", 1200)]
    assert island.messages == ["a", "b"]


def test_presentation_adapter_respects_quiet_unless_forced() -> None:
    window = FakeWindow()
    host = SimpleNamespace(
        _active_window=window,
        window=window,
        pets=None,
        quiet=FakeQuiet(True),
        settings_dialog=None,
        island=None,
    )
    adapter = _PresentationAdapter(host)

    assert adapter.say_sequence([("a", "", 900)]) is False
    assert window.lines == []
    assert adapter.say_sequence([("a", "", 900)], force=True) is True
    assert window.lines == [("a", "", 900)]
