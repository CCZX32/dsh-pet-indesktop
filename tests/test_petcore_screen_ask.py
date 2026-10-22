"""petcore 截图框选覆盖层 + 截图提问窗口/控制器（offscreen、确定性）。

覆盖三块：

1. 品牌图标抽取（10% 鲸蛙彩蛋）与标题栏固定 DS logo；
2. ``ScreenAskWindow`` 的会话重置、发送、等待态与消息渲染；
3. ``ScreenAskController`` 的后台回调、历史口径、失败与「没有扩展接管」；
4. ``select_region`` 的 DPR 裁剪、确认/取消与覆盖层几何。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petcore.contracts.screen import ScreenCapture, ScreenSelectionCancelled
from petcore.ui.screen import ScreenAskController, ScreenAskWindow, select_region
from petcore.ui.screen.ask_window import DEFAULT_QUESTION
from petcore.ui.screen.brand_icons import (
    JINGWA_LOADING_CHANCE,
    load_ds_whale,
    load_jingwa,
    pick_loading_icon,
)
from petcore.ui.screen.overlay import SelectionOverlay
from petcore.ui.screen.selection import (
    MIN_SELECTION_SIDE,
    SelectionRect,
    normalize_drag,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------- 工具


def _image(width: int = 60, height: int = 40, color: int = 0xFF336699) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(color)
    return image


def _png(width: int = 60, height: int = 40) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = _image(width, height)
    assert image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def _capture(width: int = 60, height: int = 40) -> ScreenCapture:
    return ScreenCapture(
        png=_png(width, height), width=width, height=height, screen_name="fake"
    )


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
    QApplication.processEvents()
    return bool(predicate())


def _key(widget, key: Qt.Key) -> None:
    widget.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "")
    )


def _mouse(
    kind: QEvent.Type, x: float, y: float, button: Qt.MouseButton, buttons: Qt.MouseButton
) -> QMouseEvent:
    position = QPointF(x, y)
    return QMouseEvent(
        kind,
        position,
        position,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


class FakeScreen:
    """覆盖层与 select_region 只用 geometry/DPR/name。"""

    def __init__(
        self, width: int = 200, height: int = 120, dpr: float = 1.0, name: str = "fake-screen"
    ) -> None:
        self._width, self._height = width, height
        self._dpr, self._name = dpr, name

    def geometry(self) -> QRect:
        return QRect(0, 0, self._width, self._height)

    def devicePixelRatio(self) -> float:  # noqa: N802 - Qt API
        return self._dpr

    def name(self) -> str:
        return self._name


class FakeOverlay(QObject):
    """立即给出结果的覆盖层替身（``select_region`` 的注入缝）。"""

    accepted = Signal(object)
    cancelled = Signal(str)

    def __init__(self, frame, screen, *, rect=None, cancel_reason: str = "") -> None:
        super().__init__()
        self.frame = frame
        self.screen = screen
        self.rect = rect
        self.cancel_reason = cancel_reason
        self.shown = False
        self.closed = False

    def show(self) -> None:
        self.shown = True
        if self.cancel_reason:
            self.cancelled.emit(self.cancel_reason)
        else:
            self.accepted.emit(self.rect)

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------- 品牌图标


def test_pick_loading_icon_rolls_the_ten_percent_jingwa(app, monkeypatch) -> None:
    if load_jingwa().isNull() or load_ds_whale().isNull():
        pytest.skip("品牌素材缺席")
    monkeypatch.setattr(
        "petcore.ui.screen.brand_icons.random.random",
        lambda: JINGWA_LOADING_CHANCE / 2,
    )
    assert pick_loading_icon().toImage() == load_jingwa().toImage()


def test_pick_loading_icon_defaults_to_the_whale(app, monkeypatch) -> None:
    if load_jingwa().isNull() or load_ds_whale().isNull():
        pytest.skip("品牌素材缺席")
    monkeypatch.setattr(
        "petcore.ui.screen.brand_icons.random.random", lambda: JINGWA_LOADING_CHANCE + 0.4
    )
    assert pick_loading_icon().toImage() == load_ds_whale().toImage()


def test_window_header_uses_the_whale_logo(app) -> None:
    if load_ds_whale().isNull():
        pytest.skip("品牌素材缺席")
    window = ScreenAskWindow()
    try:
        scaled = window._title_scaled
        assert scaled is not None and not scaled.isNull()
        assert window._title.pixmap() is not None
    finally:
        window.close()


# --------------------------------------------------------------------- 窗口


def test_start_sets_chip_and_resets_messages(app) -> None:
    window = ScreenAskWindow()
    try:
        window.append_user("旧消息")
        window.start(_capture())
        assert window.isVisible()
        assert not window.thumbnail().isNull()
        assert window.messages() == []
        assert window.is_waiting() is False
        assert window.input.isEnabled() and window._send_button.isEnabled()
    finally:
        window.close()


def test_enter_and_send_button_emit_submitted(app) -> None:
    window = ScreenAskWindow()
    window.start(_capture())
    seen: list[str] = []
    window.submitted.connect(seen.append)
    try:
        window.input.setText("这是什么")
        _key(window.input, Qt.Key.Key_Return)
        assert seen == ["这是什么"]
        assert window.input.text() == ""

        window._send_button.click()
        assert seen[-1] == DEFAULT_QUESTION
    finally:
        window.close()


def test_waiting_disables_input_and_shows_the_picked_icon(app, monkeypatch) -> None:
    window = ScreenAskWindow()
    window.start(_capture())
    monkeypatch.setattr(
        "petcore.ui.screen.ask_window.pick_loading_icon", load_jingwa
    )
    try:
        window.begin_waiting()
        assert window.is_waiting()
        assert not window.input.isEnabled()
        assert not window._send_button.isEnabled()
        assert window.loading_icon().toImage() == load_jingwa().toImage()
        assert window._fish.isVisible() or not window._fish.isHidden()

        window.append_assistant("答案")
        assert window.messages()[-1] == {"role": "assistant", "content": "答案"}

        window.end_waiting("发送失败：超时")
        assert window.is_waiting() is False
        assert window.input.isEnabled()
        assert "发送失败：超时" in window._status.text()
        assert window._status.isVisibleTo(window)
    finally:
        window.close()


# --------------------------------------------------------------------- 控制器


def test_controller_submits_in_background_and_appends_reply(app) -> None:
    controller = ScreenAskController(None)
    main_thread = threading.get_ident()
    calls: list[tuple] = []

    def callback(question, png, history, slot):
        calls.append((question, png, history, slot, threading.get_ident()))
        return "回答一"

    controller.on_ask("ai.chat", callback)
    capture = _capture()
    assert controller.open("ai.chat", capture, pet_slot=0) is True
    window = controller.window_for("ai.chat", 0)
    assert window is not None and window.isVisible()
    assert controller.is_open("ai.chat", pet_slot=0)

    appended: list[int] = []
    original = window.append_assistant

    def spy(text: str) -> None:
        appended.append(threading.get_ident())
        original(text)

    window.append_assistant = spy
    try:
        window.input.setText("第一问")
        assert window.send_current() is True
        assert _wait_until(lambda: not window.is_waiting())
    finally:
        window.append_assistant = original
        window.close()

    assert len(calls) == 1
    question, png, history, slot, thread_id = calls[0]
    assert question == "第一问"
    assert png == capture.png
    assert history == []
    assert slot == 0
    assert thread_id != main_thread
    assert appended == [main_thread]
    assert controller.history("ai.chat") == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "回答一"},
    ]


def test_controller_second_turn_receives_completed_history(app) -> None:
    controller = ScreenAskController(None)
    seen: list[list[dict]] = []

    def callback(question, png, history, slot):
        seen.append(history)
        return f"答：{question}"

    controller.on_ask("ai.chat", callback)
    controller.open("ai.chat", _capture(), pet_slot=0)
    window = controller.window_for("ai.chat")
    try:
        window.input.setText("一")
        window.send_current()
        assert _wait_until(lambda: not window.is_waiting())

        window.input.setText("二")
        window.send_current()
        assert _wait_until(lambda: not window.is_waiting())
    finally:
        window.close()

    assert seen[0] == []
    assert seen[1] == [
        {"role": "user", "content": "一"},
        {"role": "assistant", "content": "答：一"},
    ]
    assert len(controller.history("ai.chat")) == 4


def test_controller_failure_shows_error_without_fake_reply(app) -> None:
    controller = ScreenAskController(None)

    def boom(question, png, history, slot):
        raise RuntimeError("上游 502")

    controller.on_ask("ai.chat", boom)
    controller.open("ai.chat", _capture(), pet_slot=0)
    window = controller.window_for("ai.chat")
    try:
        window.send_current()
        assert _wait_until(lambda: not window.is_waiting())
        assert "发送失败" in window._status.text()
        assert "上游 502" in window._status.text()
        assert controller.history("ai.chat") == []
        assert all(item["role"] != "assistant" for item in window.messages())
    finally:
        window.close()


def test_controller_without_handler_reports_a_visible_error(app) -> None:
    controller = ScreenAskController(None)
    controller.open("ai.chat", _capture(), pet_slot=0)
    window = controller.window_for("ai.chat")
    try:
        window.send_current()
        assert window.is_waiting() is False
        assert "没有扩展接管截图提问" in window._status.text()
        assert window._status.isVisibleTo(window)
        assert controller.history("ai.chat") == []
    finally:
        window.close()


def test_close_hides_the_window_but_keeps_history(app, tmp_path: Path) -> None:
    # 截图问答历史只在内存：即使给了数据根，也不允许写任何问答文件。
    controller = ScreenAskController(None, tmp_path)
    controller.on_ask("ai.chat", lambda question, png, history, slot: "答")
    controller.open("ai.chat", _capture(), pet_slot=0)
    window = controller.window_for("ai.chat")
    window.input.setText("问")
    window.send_current()
    assert _wait_until(lambda: not window.is_waiting())

    controller.close("ai.chat", pet_slot=0)
    assert controller.is_open("ai.chat", pet_slot=0) is False
    assert len(controller.history("ai.chat")) == 2

    controller.open("ai.chat", _capture(), pet_slot=0)
    try:
        # 新采集 = 新会话：历史与消息列表都从零开始。
        assert controller.history("ai.chat") == []
        assert window.messages() == []
        assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
    finally:
        window.close()


# --------------------------------------------------------------------- 框选：几何


def test_normalize_drag_reverse_and_bounds() -> None:
    assert normalize_drag(10, 10, 20, 20) == SelectionRect(10, 10, 10, 10)
    assert normalize_drag(20, 20, 10, 10) == SelectionRect(10, 10, 10, 10)
    assert normalize_drag(-5, -5, 10, 10, bounds=(8, 8)) == SelectionRect(0, 0, 8, 8)
    assert normalize_drag(0, 0, 0, 0).is_empty
    assert MIN_SELECTION_SIDE == 8


# --------------------------------------------------------------------- 框选：覆盖层


def test_overlay_drag_arms_selection_and_enter_confirms(app) -> None:
    overlay = SelectionOverlay(_image(200, 120), FakeScreen())
    accepted: list[SelectionRect] = []
    overlay.accepted.connect(accepted.append)
    try:
        overlay.mousePressEvent(
            _mouse(
                QEvent.Type.MouseButtonPress,
                50,
                45,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
        )
        overlay.mouseMoveEvent(
            _mouse(
                QEvent.Type.MouseMove,
                20,
                20,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
            )
        )
        overlay.mouseReleaseEvent(
            _mouse(
                QEvent.Type.MouseButtonRelease,
                20,
                20,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            )
        )
        assert overlay.current_selection() == SelectionRect(20, 20, 30, 25)
        assert not overlay.action_bar().isHidden()

        _key(overlay, Qt.Key.Key_Return)
        assert accepted == [SelectionRect(20, 20, 30, 25)]
    finally:
        overlay.close()


def test_overlay_ignores_a_tiny_drag_and_escape_cancels(app) -> None:
    overlay = SelectionOverlay(_image(200, 120), FakeScreen())
    cancelled: list[str] = []
    overlay.cancelled.connect(cancelled.append)
    try:
        overlay.mousePressEvent(
            _mouse(
                QEvent.Type.MouseButtonPress,
                10,
                10,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
        )
        overlay.mouseReleaseEvent(
            _mouse(
                QEvent.Type.MouseButtonRelease,
                13,
                13,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            )
        )
        assert overlay.current_selection() is None
        assert overlay.action_bar().isHidden()
        assert overlay.confirm() is False

        _key(overlay, Qt.Key.Key_Escape)
        assert cancelled == ["esc"]
    finally:
        overlay.close()


def test_overlay_double_click_inside_selection_confirms(app) -> None:
    overlay = SelectionOverlay(_image(200, 120), FakeScreen())
    accepted: list[SelectionRect] = []
    overlay.accepted.connect(accepted.append)
    try:
        overlay.select_rect(SelectionRect(20, 20, 30, 25))
        overlay.mouseDoubleClickEvent(
            _mouse(
                QEvent.Type.MouseButtonDblClick,
                30,
                30,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
        )
        assert accepted == [SelectionRect(20, 20, 30, 25)]
    finally:
        overlay.close()


def test_overlay_action_bar_buttons_confirm_and_cancel(app) -> None:
    overlay = SelectionOverlay(_image(200, 120), FakeScreen())
    accepted: list[SelectionRect] = []
    cancelled: list[str] = []
    overlay.accepted.connect(accepted.append)
    overlay.cancelled.connect(cancelled.append)
    try:
        overlay.select_rect(SelectionRect(20, 20, 30, 25))
        overlay.action_bar().ask_button.click()
        assert accepted == [SelectionRect(20, 20, 30, 25)]

        overlay.select_rect(SelectionRect(20, 20, 30, 25))
        overlay.action_bar().cancel_button.click()
        assert cancelled == ["toolbar"]
    finally:
        overlay.close()


def test_overlay_external_close_cancels_instead_of_hanging(app) -> None:
    overlay = SelectionOverlay(_image(200, 120), FakeScreen())
    cancelled: list[str] = []
    overlay.cancelled.connect(cancelled.append)
    overlay.show()
    overlay.close()
    assert cancelled == ["closed"]


def test_overlay_paints_no_dim_before_and_dim_after_selection(app) -> None:
    frame = _image(200, 120, color=0xFF808080)
    overlay = SelectionOverlay(frame, FakeScreen(200, 120))
    overlay.resize(200, 120)
    try:
        plain = overlay.grab().toImage()
        assert plain.pixelColor(190, 5).red() == 0x80  # 未框选不压暗

        overlay.select_rect(SelectionRect(10, 60, 40, 30))
        painted = overlay.grab().toImage()
        assert painted.pixelColor(20, 75).red() == 0x80  # 选区内像素原样
        assert painted.pixelColor(190, 5).red() < 0x80   # 选区外压暗
    finally:
        overlay.close()


# --------------------------------------------------------------------- 框选：链路


def test_select_region_real_overlay_confirms_through_the_event_loop(app) -> None:
    from PySide6.QtCore import QTimer

    made: list[SelectionOverlay] = []

    def factory(image, target):
        overlay = SelectionOverlay(image, target)
        QTimer.singleShot(
            0,
            lambda: (
                overlay.select_rect(SelectionRect(10, 10, 20, 10)),
                overlay.confirm(),
            ),
        )
        made.append(overlay)
        return overlay

    capture = select_region(
        screen=FakeScreen(200, 120),
        grab=lambda target: (_image(200, 120), target),
        overlay_factory=factory,
    )
    assert (capture.width, capture.height) == (20, 10)
    assert made and made[0].isVisible() is False


def test_select_region_crops_by_dpr_and_closes_overlay(app) -> None:
    frame = _image(400, 240)
    frame.setDevicePixelRatio(2.0)
    screen = FakeScreen(200, 120, dpr=2.0)
    made: list[FakeOverlay] = []

    def factory(image, target):
        overlay = FakeOverlay(
            image, target, rect=SelectionRect(10, 6, 30, 20)
        )
        made.append(overlay)
        return overlay

    capture = select_region(
        screen=screen,
        grab=lambda target: (frame, target),
        overlay_factory=factory,
    )
    assert made and made[0].shown is True and made[0].closed is True
    assert (capture.width, capture.height) == (60, 40)  # 物理像素
    assert capture.screen_name == "fake-screen"
    assert capture.png.startswith(b"\x89PNG")


def test_select_region_forwards_a_bare_image_from_injected_grab(app) -> None:
    frame = _image(200, 120)
    screen = FakeScreen(200, 120)

    def factory(image, target):
        return FakeOverlay(image, target, rect=SelectionRect(0, 0, 20, 10))

    capture = select_region(
        screen=screen, grab=lambda target: frame, overlay_factory=factory
    )
    assert (capture.width, capture.height) == (20, 10)


def test_select_region_cancel_raises_and_closes_overlay(app) -> None:
    made: list[FakeOverlay] = []

    def factory(image, target):
        overlay = FakeOverlay(image, target, cancel_reason="esc")
        made.append(overlay)
        return overlay

    with pytest.raises(ScreenSelectionCancelled):
        select_region(
            screen=FakeScreen(),
            grab=lambda target: _image(200, 120),
            overlay_factory=factory,
        )
    assert made and made[0].closed is True


def test_select_region_too_small_selection_is_cancelled(app) -> None:
    def factory(image, target):
        return FakeOverlay(image, target, rect=SelectionRect(4, 4, 2, 2))

    with pytest.raises(ScreenSelectionCancelled):
        select_region(
            screen=FakeScreen(),
            grab=lambda target: _image(200, 120),
            overlay_factory=factory,
        )
