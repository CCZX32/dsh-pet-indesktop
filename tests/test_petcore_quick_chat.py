"""快速对话气泡：点气泡开窗、提交/流式/落会话、去聊天窗、按宠隔离。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.ui.bubble import SpeechBubble
from petcore.ui.chat import ChatController, QuickChatController
from petcore.ui.pet_window import PetWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeHost:
    def __init__(self, root: Path) -> None:
        self.config = Config(root)
        self.root = root
        self.pets = None
        self.window = None
        self.chat = ChatController(self, root)
        self.quick_chat = QuickChatController(self)
        self.quick_opens: list[int] = []

    def open_quick_chat(self, slot: int = 0) -> bool:
        self.quick_opens.append(int(slot))
        return True

    # PetWindow 需要的宿主面
    def characters(self):
        return []

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

    def run_feature_command(self, *args, **kwargs):
        return False


@pytest.fixture()
def host(app, tmp_path: Path):
    instance = FakeHost(tmp_path)
    yield instance
    for state in instance.quick_chat._states.values():
        state.bubble.close()
    for state in instance.chat.states().values():
        if state.window is not None:
            state.window.deleteLater()


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(predicate())


def test_open_shows_the_bubble(host) -> None:
    assert host.quick_chat.open("ai.chat", pet_slot=0) is True
    bubble = host.quick_chat.bubble_for("ai.chat", 0)
    assert bubble is not None and bubble.isVisible()
    assert host.quick_chat.is_open("ai.chat") is True


def test_submit_streams_and_persists_to_the_shared_session(host) -> None:
    received: list[tuple[str, int]] = []
    host.quick_chat.on_submit("ai.chat", lambda text, slot: received.append((text, slot)))
    host.quick_chat.open("ai.chat", pet_slot=0)
    bubble = host.quick_chat.bubble_for("ai.chat", 0)
    assert bubble is not None

    bubble.input.setText("在吗")
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert received == [("在吗", 0)]
    assert _wait(lambda: host.chat.history("ai.chat")[-1]["content"] == "在吗")

    host.quick_chat.token("ai.chat", "你")
    host.quick_chat.token("ai.chat", "好")
    host.quick_chat.done("ai.chat", "你好", pet_slot=0)
    assert _wait(lambda: bubble.text() == "你好")
    assert bubble.is_streaming() is False

    history = host.chat.history("ai.chat")
    assert [item["content"] for item in history[-2:]] == ["在吗", "你好"]
    # 同一份会话：完整聊天窗打开时能看到这两条。
    host.chat.open("ai.chat", pet_slot=0)
    window = host.chat.window_for("ai.chat")
    assert window is not None
    assert "在吗" in window.transcript_text()
    assert "你好" in window.transcript_text()


def test_submit_without_handler_shows_an_error(host) -> None:
    host.quick_chat.open("ai.chat", pet_slot=0)
    bubble = host.quick_chat.bubble_for("ai.chat", 0)
    assert bubble is not None
    bubble.input.setText("在吗")
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert "没有接入" in bubble.text()


def test_error_and_status_are_visible(host) -> None:
    host.quick_chat.open("ai.chat", pet_slot=0)
    bubble = host.quick_chat.bubble_for("ai.chat", 0)
    assert bubble is not None
    host.quick_chat.status("ai.chat", "🔍 正在搜索：天气", pet_slot=0)
    assert _wait(lambda: "正在搜索" in bubble.hint.text())
    host.quick_chat.error("ai.chat", "network", "网络不可达", pet_slot=0)
    assert _wait(lambda: "网络不可达" in bubble.text())


def test_open_full_chat_hides_the_bubble(host) -> None:
    host.quick_chat.open("ai.chat", pet_slot=0)
    bubble = host.quick_chat.bubble_for("ai.chat", 0)
    assert bubble is not None
    host.quick_chat.open_full_chat("ai.chat", pet_slot=0)
    assert bubble.isVisible() is False
    window = host.chat.window_for("ai.chat")
    assert window is not None and window.isVisible()


def test_bubbles_are_isolated_per_pet(host) -> None:
    host.quick_chat.open("ai.chat", pet_slot=0)
    host.quick_chat.open("ai.chat", pet_slot=1)
    first = host.quick_chat.bubble_for("ai.chat", 0)
    second = host.quick_chat.bubble_for("ai.chat", 1)
    assert first is not None and second is not None and first is not second


def test_speech_bubble_emits_clicked(app) -> None:
    bubble = SpeechBubble()
    seen: list[bool] = []
    bubble.clicked.connect(lambda: seen.append(True))
    bubble.show_text("点我", bubble.rect(), 4000)
    bubble.show()
    try:
        QTest.mouseClick(bubble, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
        assert seen == [True]
    finally:
        bubble.close()


def test_pet_window_routes_the_bubble_click_to_the_host(app, host) -> None:
    from petcore.contracts.content import CharacterSpec

    spec = CharacterSpec(
        id="fallback",
        name="Fallback",
        root=Path("."),
        media_kind="none",
        animations=(),
    )
    window = PetWindow(host.config, host.root, host, slot=0)
    window.start(spec)
    try:
        window.bubble.clicked.emit()
        assert host.quick_opens == [0]
    finally:
        window.shutdown()
