"""Core 聊天窗口与 ChatPort：流式、输入约定、按宠隔离、会话落盘。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.ui.chat import ChatController


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeHost:
    def __init__(self, root: Path) -> None:
        self.config = Config(root)
        self.pets = None


@pytest.fixture()
def controller(app, tmp_path: Path):
    host = FakeHost(tmp_path)
    control = ChatController(host, tmp_path)
    yield control
    for (_owner, slot), state in control.states().items():
        state.window.close()


def _enter(window, *, shift: bool = False) -> None:
    modifier = (
        Qt.KeyboardModifier.ShiftModifier
        if shift
        else Qt.KeyboardModifier.NoModifier
    )
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, modifier, chr(13) if shift else ""
    )
    window.input.keyPressEvent(event)


def test_open_and_stream_render_markdown(controller) -> None:
    assert controller.open("ai.chat", pet_slot=0, title="测试对话") is True
    window = controller.window_for("ai.chat")
    assert window is not None and window.isVisible()
    assert window.windowTitle() == "测试对话"

    controller.append("ai.chat", "user", "在吗")
    controller.token("ai.chat", "**你")
    controller.token("ai.chat", "好**")
    controller.done("ai.chat", "**你好**")

    assert window.is_streaming() is False
    text = window.transcript.toPlainText()
    assert "在吗" in text
    assert "你好" in text
    assert window.stop_button.isHidden()
    assert window.send_button.isEnabled()


def test_enter_submits_and_shift_enter_keeps_newline(controller) -> None:
    controller.open("ai.chat", pet_slot=0)
    window = controller.window_for("ai.chat")
    received: list[tuple[str, int]] = []
    controller.on_submit("ai.chat", lambda text, slot: received.append((text, slot)))

    window.input.setPlainText("第一行")
    _enter(window, shift=True)
    assert "\n" in window.input.toPlainText()
    assert received == []

    _enter(window)
    assert received == [("第一行", 0)]
    assert window.input.toPlainText() == ""


def test_stop_button_tracks_streaming_state(controller) -> None:
    controller.open("ai.chat", pet_slot=0)
    window = controller.window_for("ai.chat")
    controller.token("ai.chat", "半")
    assert window.is_streaming() is True
    assert window.stop_button.isVisible() is True
    controller.done("ai.chat", "半句")
    assert window.stop_button.isVisible() is False


def test_each_pet_slot_gets_its_own_window_and_session(controller) -> None:
    controller.open("ai.chat", pet_slot=0)
    controller.open("ai.chat", pet_slot=1)
    main = controller.window_for("ai.chat", 0)
    child = controller.window_for("ai.chat", 1)
    assert main is not None and child is not None and main is not child

    controller.append("ai.chat", "user", "主宠的话", pet_slot=0)
    controller.append("ai.chat", "user", "子宠的话", pet_slot=1)
    assert "主宠的话" in controller.history("ai.chat", pet_slot=0)[-1]["content"]
    assert "子宠的话" in controller.history("ai.chat", pet_slot=1)[-1]["content"]

    files = list(Path(controller.root).rglob("*.json"))
    assert files, "会话必须落盘"
    assert any("sessions-slot-1" in str(path) for path in files)


def test_clear_starts_a_new_session(controller) -> None:
    controller.open("ai.chat", pet_slot=0)
    window = controller.window_for("ai.chat")
    controller.append("ai.chat", "user", "旧消息")
    first = controller.states()[("ai.chat", 0)].session.session_id
    window.clear_button.click()
    second = controller.states()[("ai.chat", 0)].session.session_id
    assert first != second
    assert controller.history("ai.chat") == []


def test_error_is_shown_and_clears_the_pending_bubble(controller) -> None:
    controller.open("ai.chat", pet_slot=0)
    window = controller.window_for("ai.chat")
    controller.append("ai.chat", "user", "问题")
    controller.token("ai.chat", "半句")
    controller.error("ai.chat", "network", "网络不可达")
    assert "网络不可达" in window.status_label.text()
    assert window.is_streaming() is False
    assert controller.history("ai.chat")[-1]["role"] == "user"
