"""截图动作调度：按 priority 回退、原文传递、全部失败的可见原因。"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petcore.contracts.screen import ScreenCapture
from petcore.ui.screen import ScreenAskController


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _capture() -> ScreenCapture:
    return ScreenCapture(png=b"png-bytes", width=8, height=6, screen_name="fake")


def _wait(app, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture()
def controller(app, tmp_path: Path):
    control = ScreenAskController(None, tmp_path)
    yield control
    for state in control._states.values():
        state.window.close()


def test_action_handlers_run_in_priority_order_and_fall_through(app, controller) -> None:
    calls: list[tuple[str, str, str]] = []

    def local(action, text, png, slot):
        calls.append(("local", action, text))
        return ""

    def ai(action, text, png, slot):
        calls.append(("ai", action, text))
        return "AI 结果"

    controller.on_action("tool.ocr", local, priority=10, actions=("ocr",))
    controller.on_action("ai.chat", ai, priority=100, actions=("ocr", "translate"))

    assert controller.supports_action("ocr") is True
    assert controller.supports_action("translate") is True
    assert controller.supports_action("copy") is False

    assert controller.open_action("ai.chat", "ocr", _capture(), pet_slot=0) is True
    window = controller.window_for("ai.chat", 0)
    assert _wait(app, lambda: window is not None and not window.is_waiting())
    assert calls == [("local", "ocr", ""), ("ai", "ocr", "")]
    assert window is not None
    assert window.messages()[-1]["content"] == "AI 结果"
    assert window.windowTitle() == "截图提取文字"


def test_translate_receives_the_local_source_text(app, controller) -> None:
    seen: list[tuple[str, str]] = []

    def ai(action, text, png, slot):
        seen.append((action, text))
        return "译文"

    controller.on_action("ai.chat", ai, priority=100, actions=("translate",))
    assert controller.open_action("ai.chat", "translate", _capture(), text="原文") is True
    window = controller.window_for("ai.chat")
    assert _wait(app, lambda: window is not None and not window.is_waiting())
    assert seen == [("translate", "原文")]
    assert window is not None and window.messages()[-1]["content"] == "译文"
    assert window.windowTitle() == "截图翻译"


def test_no_handler_reports_a_visible_reason(app, controller) -> None:
    assert controller.open_action("ai.chat", "ocr", _capture()) is False
    window = controller.window_for("ai.chat")
    assert window is not None
    assert "没有可用的识别引擎" in window.status_text()


def test_all_handlers_empty_reports_a_visible_reason(app, controller) -> None:
    controller.on_action("tool.ocr", lambda *_args: "", priority=10, actions=("ocr",))
    assert controller.open_action("ai.chat", "ocr", _capture()) is True
    window = controller.window_for("ai.chat")
    assert _wait(app, lambda: window is not None and not window.is_waiting())
    assert window is not None
    assert "没有可用的识别引擎" in window.status_text()


def test_handler_exception_is_treated_as_no_text(app, controller) -> None:
    def broken(*_args):
        raise RuntimeError("boom")

    controller.on_action("tool.ocr", broken, priority=10, actions=("ocr",))
    controller.on_action("ai.chat", lambda *_a: "兜底文本", priority=100, actions=("ocr",))
    assert controller.open_action("ai.chat", "ocr", _capture()) is True
    window = controller.window_for("ai.chat")
    assert _wait(app, lambda: window is not None and not window.is_waiting())
    assert window is not None and window.messages()[-1]["content"] == "兜底文本"


def test_stale_action_reply_is_dropped(app, controller) -> None:
    controller.on_action("ai.chat", lambda *_a: "旧结果", actions=("ocr",))
    assert controller.open_action("ai.chat", "ocr", _capture()) is True
    window = controller.window_for("ai.chat")
    assert _wait(app, lambda: window is not None and not window.is_waiting())

    # 新一次动作让旧 generation 作废：迟到的结果不能再写进新会话。
    assert controller.open_action("ai.chat", "ocr", _capture()) is True
    window.clear_messages()
    state = controller._states[("ai.chat", 0)]
    controller._apply_action_reply("ai.chat", 0, state.generation - 1, "迟到结果")
    assert all(item["content"] != "迟到结果" for item in window.messages())
