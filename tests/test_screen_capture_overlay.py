# -*- coding: utf-8 -*-
"""「快速识屏」P0 框选覆盖层（真实 QWidget，offscreen）。

覆盖层是本片唯一的交互面，三条契约：
1. 铺满目标屏且无边框置顶（否则冻结帧与真实屏幕错位）；
2. 拖框 → 归一化选区；Esc 取消、Enter 确认；**没框住任何东西时 Enter 无效**
   （空选区进 OCR 是纯浪费，必须在这里挡住）；
3. 冻结帧画成底图，非选区压暗、选区保持原样——这是"真截屏体验"的视觉契约，
   用真实 render() 采样像素验证，不看描述。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet.screen_capture.overlay import (  # noqa: E402
    DIM_ALPHA,
    MIN_SELECTION_SIDE,
    SelectionMemory,
    SelectionOverlay,
)

from pet.screen_capture.session import SelectionRect  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _fresh_shared_memory(monkeypatch):
    """每个用例一份干净的「上次选区」进程级记忆。

    记忆是跨覆盖层实例的进程状态（这正是它的用处），用例之间若不隔离，"上一个
    用例确认过一块"会变成"下一个用例一开局就预选着"——本文件里大量断言
    ``current_selection() is None`` 的用例会因此莫名其妙地红。隔离的是**进程级
    那一份**，用例自己注入 ``SelectionMemory()`` 的路径不受影响。
    """
    from pet.screen_capture import overlay as overlay_mod

    monkeypatch.setattr(overlay_mod, "_SHARED_MEMORY", overlay_mod.SelectionMemory())


class _FakeScreen:
    """只暴露覆盖层真正使用的两个读口（几何 + DPR），避免依赖真屏幕尺寸。"""

    def __init__(self, width: int = 200, height: int = 120, dpr: float = 1.0) -> None:
        self._rect = QRect(0, 0, width, height)
        self._dpr = dpr

    def geometry(self) -> QRect:  # noqa: D102
        return QRect(self._rect)

    def devicePixelRatio(self) -> float:  # noqa: N802 - 对齐 Qt 命名
        return self._dpr


def _drag(overlay, start, end, *, button=Qt.MouseButton.LeftButton):
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(*start), QPointF(*start),
                        button, button, Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(*end), QPointF(*end),
                       Qt.MouseButton.NoButton, button, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(*end), QPointF(*end),
                          button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    overlay.mousePressEvent(press)
    overlay.mouseMoveEvent(move)
    overlay.mouseReleaseEvent(release)


def _key(overlay, key):
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


# ------------------------------------------------------------------ 覆盖整屏


def test_overlay_fills_the_target_screen_and_is_frameless_on_top(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen(320, 240))

    assert overlay.geometry() == QRect(0, 0, 320, 240)
    flags = overlay.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    overlay.close()


def test_overlay_keeps_focus_for_keyboard(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())
    assert overlay.focusPolicy() != Qt.FocusPolicy.NoFocus
    overlay.close()


# -------------------------------------------------------------------- 框选


def test_drag_produces_normalized_selection(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (150, 100), (60, 40))

    assert overlay.current_selection() == SelectionRect(60, 40, 90, 60)
    _key(overlay, Qt.Key.Key_Return)

    assert confirmed == [SelectionRect(60, 40, 90, 60)]
    overlay.close()


def test_drag_outside_screen_is_clamped(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen(200, 120))

    _drag(overlay, (10, 10), (500, 500))

    assert overlay.current_selection() == SelectionRect(10, 10, 190, 110)
    overlay.close()


def test_escape_cancels_and_never_confirms(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())
    confirmed, cancelled = [], []
    overlay.selection_confirmed.connect(confirmed.append)
    overlay.selection_cancelled.connect(cancelled.append)

    _drag(overlay, (10, 10), (60, 60))
    _key(overlay, Qt.Key.Key_Escape)

    assert cancelled == ["esc"]
    assert confirmed == []
    overlay.close()


def test_enter_without_selection_is_ignored(qapp):
    """空选区不许进下游：Enter 无效、覆盖层不关、不算取消。"""
    overlay = SelectionOverlay(screen=_FakeScreen())
    confirmed, cancelled = [], []
    overlay.selection_confirmed.connect(confirmed.append)
    overlay.selection_cancelled.connect(cancelled.append)

    _key(overlay, Qt.Key.Key_Return)

    assert confirmed == []
    assert cancelled == []
    assert overlay.current_selection() is None
    overlay.close()


def test_zero_size_drag_then_enter_is_ignored(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (50, 50), (50, 50))
    _key(overlay, Qt.Key.Key_Return)

    assert confirmed == []
    overlay.close()


def test_right_button_drag_does_not_select(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())

    _drag(overlay, (10, 10), (80, 80), button=Qt.MouseButton.RightButton)

    assert overlay.current_selection() is None
    overlay.close()


def test_new_drag_replaces_previous_selection(qapp):
    overlay = SelectionOverlay(screen=_FakeScreen())

    _drag(overlay, (10, 10), (60, 60))
    _drag(overlay, (100, 20), (150, 70))

    assert overlay.current_selection() == SelectionRect(100, 20, 50, 50)
    overlay.close()


def test_a_drag_below_the_minimum_size_is_not_a_selection(qapp):
    """1 px 级抖动不算选区：清成 None（画面如实显示"没选"），Enter 也不许确认。"""
    overlay = SelectionOverlay(screen=_FakeScreen(), memory=SelectionMemory())
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (50, 50), (52, 51))            # 2x1，两个方向都远小于门槛

    assert overlay.current_selection() is None
    _key(overlay, Qt.Key.Key_Return)
    assert confirmed == [], "过小选区进了下游就是一次白跑的会话"
    overlay.close()


def test_a_drag_at_the_minimum_size_is_accepted(qapp):
    """门槛的另一半：正好够大的拖拽必须照常确认（别把正常用小区域也挡掉）。"""
    overlay = SelectionOverlay(screen=_FakeScreen(), memory=SelectionMemory())
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (50, 50), (50 + MIN_SELECTION_SIDE, 50 + MIN_SELECTION_SIDE))
    _key(overlay, Qt.Key.Key_Return)

    assert confirmed == [SelectionRect(50, 50, MIN_SELECTION_SIDE, MIN_SELECTION_SIDE)]
    overlay.close()


def test_only_one_side_below_the_minimum_is_refused(qapp):
    """门槛是两个方向都要够：一条 100x2 的细缝进 OCR 一样读不出东西。"""
    overlay = SelectionOverlay(screen=_FakeScreen(), memory=SelectionMemory())
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (10, 10), (110, 12))
    _key(overlay, Qt.Key.Key_Return)

    assert overlay.current_selection() is None
    assert confirmed == []
    overlay.close()


# ---------------------------------------------------------------- 记住上次


def test_the_next_overlay_preselects_the_last_confirmed_area(qapp):
    """同一块屏上再次框选：上次确认的那块预选出来，Enter 直接复用。"""
    memory = SelectionMemory()

    first = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)
    _drag(first, (40, 20), (140, 80))
    _key(first, Qt.Key.Key_Return)
    first.close()

    second = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)
    assert second.current_selection() == SelectionRect(40, 20, 100, 60)

    confirmed = []
    second.selection_confirmed.connect(confirmed.append)
    _key(second, Qt.Key.Key_Return)
    assert confirmed == [SelectionRect(40, 20, 100, 60)], "预选的区域要能直接确认"
    second.close()


def test_the_preselection_is_actually_painted(qapp):
    """预选必须看得见：只是内部状态的话，用户不知道 Enter 会截哪一块。"""
    memory = SelectionMemory()
    memory.remember((200, 120), SelectionRect(40, 20, 100, 60))

    overlay = SelectionOverlay(frame=_frozen_frame(), screen=_FakeScreen(200, 120),
                               memory=memory)
    overlay.show()

    canvas = _render(overlay)

    dimmed_white = round(255 * (1 - DIM_ALPHA / 255))
    assert canvas.pixelColor(90, 50).red() >= 250                # 预选区内是原样的亮
    assert abs(canvas.pixelColor(10, 10).red() - dimmed_white) <= 6
    overlay.close()


def test_a_different_screen_size_does_not_reuse_the_old_selection(qapp):
    """换屏就作废：另一块屏的逻辑坐标套过来会框到完全不同的东西。"""
    memory = SelectionMemory()
    memory.remember((200, 120), SelectionRect(40, 20, 100, 60))

    overlay = SelectionOverlay(screen=_FakeScreen(400, 300), memory=memory)

    assert overlay.current_selection() is None
    overlay.close()


def test_a_selection_outside_the_screen_is_not_preselected(qapp):
    """换分辨率后旧坐标可能落在新屏外：越界的预选一律不作数。"""
    memory = SelectionMemory()
    memory.remember((200, 120), SelectionRect(500, 500, 100, 60))

    overlay = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)

    assert overlay.current_selection() is None
    overlay.close()


def test_cancelling_does_not_remember_anything(qapp):
    """没确认过的东西不该被当成默认值。"""
    memory = SelectionMemory()

    first = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)
    _drag(first, (40, 20), (140, 80))
    _key(first, Qt.Key.Key_Escape)
    first.close()

    second = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)
    assert second.current_selection() is None
    second.close()


def test_clicking_after_a_preselection_drops_it_instead_of_capturing_it(qapp):
    """预选之后随手点一下 = 开始新的一次框选：绝不许把旧区域当成"用户选好的"。"""
    memory = SelectionMemory()
    memory.remember((200, 120), SelectionRect(40, 20, 100, 60))
    overlay = SelectionOverlay(screen=_FakeScreen(200, 120), memory=memory)
    confirmed = []
    overlay.selection_confirmed.connect(confirmed.append)

    _drag(overlay, (10, 10), (12, 11))            # 误触
    _key(overlay, Qt.Key.Key_Return)

    assert overlay.current_selection() is None
    assert confirmed == []
    overlay.close()


def test_default_overlays_share_the_process_wide_memory(qapp):
    """不注入 memory 的默认路径必须真的共享那一份（否则"记住上次"等于没接上）。"""
    first = SelectionOverlay(screen=_FakeScreen(200, 120))
    _drag(first, (30, 30), (130, 90))
    _key(first, Qt.Key.Key_Return)
    first.close()

    second = SelectionOverlay(screen=_FakeScreen(200, 120))

    assert second.current_selection() == SelectionRect(30, 30, 100, 60)
    second.close()


def test_selection_memory_is_pure_and_copies(qapp):
    """记忆本身是纯数据：取出来的是副本，改它不会脏内部（也不要求 Qt）。"""
    memory = SelectionMemory()
    remembered = SelectionRect(10, 20, 30, 40)
    memory.remember((800, 600), remembered)

    got = memory.get((800, 600))
    assert got == remembered and got is not remembered
    assert memory.get((1024, 768)) is None

    memory.clear()
    assert memory.get((800, 600)) is None


# -------------------------------------------------------------------- 绘制


def _frozen_frame(width: int = 200, height: int = 120) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    return image


def _render(overlay, background: QColor | None = None) -> QImage:
    canvas = QImage(overlay.size(), QImage.Format.Format_RGB32)
    canvas.fill(background if background is not None else QColor(0, 0, 0))
    painter = QPainter(canvas)
    overlay.render(painter, QPoint(0, 0))
    painter.end()
    return canvas


def test_frozen_frame_is_shown_as_background(qapp):
    overlay = SelectionOverlay(frame=_frozen_frame(), screen=_FakeScreen())

    canvas = _render(overlay)

    # 白底图被压暗后仍是亮灰——不是黑屏（黑屏＝抓帧没接上）
    assert canvas.pixelColor(5, 5).red() > 100
    overlay.close()


def test_selection_area_stays_bright_while_the_rest_is_dimmed(qapp):
    overlay = SelectionOverlay(frame=_frozen_frame(), screen=_FakeScreen())
    overlay.show()
    _drag(overlay, (50, 30), (150, 90))

    canvas = _render(overlay)

    dimmed_white = round(255 * (1 - DIM_ALPHA / 255))
    inside = canvas.pixelColor(100, 60)
    outside = canvas.pixelColor(10, 10)
    assert inside.red() >= 250                       # 选区内保持原样
    assert abs(outside.red() - dimmed_white) <= 6    # 选区外按 DIM_ALPHA 压暗
    overlay.close()


def test_overlay_without_frozen_frame_still_paints_dim_mask(qapp):
    """抓帧失败的兜底形态：没有底图也得有可见的压暗遮罩。"""
    overlay = SelectionOverlay(screen=_FakeScreen())

    canvas = _render(overlay, background=QColor(255, 255, 255))

    assert canvas.pixelColor(10, 10).red() < 200
    overlay.close()
