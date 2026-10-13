# -*- coding: utf-8 -*-
"""「快速识屏」框选覆盖层：铺满目标屏、画冻结帧、拖框、Esc/Enter。

视觉契约（"真截屏体验"就靠这三笔）：

- 底图 = 冻结帧（用户看到的是静止画面，不是身后的实时桌面）；
- 非选区压暗 ``DIM_ALPHA``，选区内保持原样；
- 选区描 1px 边框（``BORDER_COLOR``），提示"这块会被截走"。

交互契约：

- 左键拖拽出选区，反向拖拽照常（归一化交给 ``normalize_drag``）；
- ``Esc`` 取消（``selection_cancelled("esc")``）、``Enter`` 确认
  （``selection_confirmed(SelectionRect)``）；
- **没有框住任何东西时 Enter 无效**：空选区进下游纯属浪费，在这里就挡住。
  比 ``MIN_SELECTION_SIDE`` 更小的拖拽**等于没框**——1~2 px 的抖动（按下时手滑）
  在旧口径下会换来"确认成功"，然后下游拿着几个像素去识别，用户看到的是
  "没有识别到文字"：一次完整会话白跑，还查不出为什么。所以门槛卡在交互层。
- **记住上次选区**：同一块屏（尺寸相同）上再次框选时，上次确认过的那块预先
  画出来并可直接 Enter 复用（"盯着同一个小区域反复截"是高频用法）。跨屏不共用
  ——尺寸变了旧坐标就没有意义；取消不算记住，没确认过的东西不该被当成默认值。

本片覆盖层是**独占**的：它铺满整屏并置顶，期间不处理"鼠标穿透到非选区"的
需求（那是后续片；先保证"框选期间点不到别的"这个可预期的行为）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QWidget

from .session import SelectionRect, normalize_drag

log = logging.getLogger("dsh-pet-standalone")

__all__ = ["DIM_ALPHA", "BORDER_COLOR", "MIN_SELECTION_SIDE", "SelectionMemory",
           "SelectionOverlay", "shared_selection_memory"]

#: 非选区压暗强度（0-255）。定 110 的依据：白底 (255) 压到约 145，选中区
#: 与未选中区的差异一眼可辨，又不至于看不清底下内容该不该框。
DIM_ALPHA = 110
BORDER_COLOR = QColor(64, 176, 255)
BORDER_WIDTH = 1

#: 选区的最小边长（逻辑像素）。8 的依据：截 8×8 一块进去，OCR 必然什么都读不出来
#: （连一个字符都放不下），所以它只可能是误触；而真正想框小图标/小按钮的用户，
#: 拖到 8 px 以上不需要刻意努力（4K 屏上 8 逻辑像素也远小于任何可读文本块）。
MIN_SELECTION_SIDE = 8


class SelectionMemory:
    """上次确认过的选区（按屏幕尺寸分槽），跨覆盖层实例存活。

    覆盖层是**每次采集现造**的对象（``controller`` 的 ``overlay_factory``），
    所以"记住上次"这件事只能存在它外面。按逻辑宽高分槽而不是只存一份：多屏
    环境下两块尺寸不同的屏各自记各的，换屏时不会把另一块屏的坐标套过来。

    只提供"取/记/清"三件事，不碰 Qt（纯数据），因此可以在没有事件循环的地方
    直接单测。
    """

    def __init__(self) -> None:
        self._by_screen: dict[tuple[int, int], SelectionRect] = {}

    def get(self, size: tuple[int, int]) -> SelectionRect | None:
        """取该尺寸屏幕的上次选区（没记过返回 None）。返回副本，调用方改不脏内部。"""
        found = self._by_screen.get((int(size[0]), int(size[1])))
        if not isinstance(found, SelectionRect):
            return None
        return SelectionRect(found.x, found.y, found.width, found.height)

    def remember(self, size: tuple[int, int], selection: SelectionRect) -> None:
        if not isinstance(selection, SelectionRect) or selection.is_empty:
            return
        self._by_screen[(int(size[0]), int(size[1]))] = SelectionRect(
            selection.x, selection.y, selection.width, selection.height)

    def clear(self) -> None:
        self._by_screen.clear()


_SHARED_MEMORY = SelectionMemory()


def shared_selection_memory() -> SelectionMemory:
    """进程内共享的选区记忆（真实运行时的那一份；测试可注入自己的实例）。"""
    return _SHARED_MEMORY


class SelectionOverlay(QWidget):
    """整屏框选层。

    ``frame`` 是冻结帧（裸设备像素，见 ``pixels.grab_screen_image``），
    ``screen`` 是目标 ``QScreen``；两者都可注入，offscreen 下用假对象即可测
    （本类只用它们的 ``geometry()`` / ``devicePixelRatio()``）。``memory`` 是
    "上次选区"的存放处（默认走进程内共享的那一份），测试注入自己的实例即可隔离。
    """

    selection_confirmed = Signal(object)   # SelectionRect
    selection_cancelled = Signal(str)      # 取消理由

    def __init__(self, frame: QImage | None = None, screen=None, parent=None,
                 *, memory: SelectionMemory | None = None) -> None:
        super().__init__(parent)
        self._frame = frame
        self._screen = screen if screen is not None else QGuiApplication.primaryScreen()
        self._memory = memory if memory is not None else _SHARED_MEMORY
        self._anchor: QPoint | None = None
        self._selection: SelectionRect | None = None
        self._dragging = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self._apply_screen_geometry()
        # 预选上次确认的那块（同尺寸屏幕才会命中，见 SelectionMemory）。刻意放在
        # 几何就位之后：校验"还在屏内"要用到本层自己的尺寸。
        self._selection = self._remembered()

    # ------------------------------------------------------------ 只读视图

    @property
    def screen_device_pixel_ratio(self) -> float:
        """目标屏的 DPR（裁剪时换算逻辑坐标用）。"""
        dpr = getattr(self._screen, "devicePixelRatio", None)
        return float(dpr()) if callable(dpr) else 1.0

    def current_selection(self) -> SelectionRect | None:
        return self._selection

    def _remembered(self) -> SelectionRect | None:
        """该尺寸屏幕上的上次选区；不在屏内（换分辨率/显示器后）就当没记过。

        跨屏共用同一个槽位的说明：键只有尺寸，所以两块**分辨率相同**的屏共用一份
        记忆。无害——覆盖层坐标是屏内局部坐标（``event.position()`` 相对本层），
        同一块面积在哪块屏上都成立；反倒是"按屏幕对象记"会在热插拔/换主屏后全部
        失效。越界（换分辨率后旧坐标落在屏外）则一律不作数，绝不偷偷挪到屏内。
        """
        size = self._screen_size()
        found = self._memory.get(size)
        if found is None or not self._usable(found):
            return None
        width, height = size
        if (found.x < 0 or found.y < 0
                or found.x + found.width > width or found.y + found.height > height):
            return None
        return found

    @staticmethod
    def _usable(selection: SelectionRect | None) -> bool:
        """能不能进下游：非空 **且** 两个方向都不小于 ``MIN_SELECTION_SIDE``。"""
        if not isinstance(selection, SelectionRect) or selection.is_empty:
            return False
        return (selection.width >= MIN_SELECTION_SIDE
                and selection.height >= MIN_SELECTION_SIDE)

    # ---------------------------------------------------------------- 生命周期

    def _apply_screen_geometry(self) -> None:
        if self._screen is None:
            return
        self.setGeometry(QRect(self._screen.geometry()))

    def _screen_size(self) -> tuple[int, int]:
        size = self.geometry().size()
        return size.width(), size.height()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 键鼠都要吃：无激活窗口的覆盖层收不到 Esc/Enter。
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._dragging = False
        self._anchor = None
        super().closeEvent(event)

    # ---------------------------------------------------------------- 鼠标

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._dragging = True
        self._anchor = QPoint(round(event.position().x()), round(event.position().y()))
        self._selection = None
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._dragging or self._anchor is None:
            return
        self._selection = self._normalize(
            self._anchor.x(), self._anchor.y(),
            round(event.position().x()), round(event.position().y()))
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        if self._anchor is not None:
            self._selection = self._normalize(
                self._anchor.x(), self._anchor.y(),
                round(event.position().x()), round(event.position().y()))
        self._anchor = None
        # 拖到太小（含原地点击）等于**没框住东西**：把选区清成 None，让画面
        # 如实显示"还没选"，Enter 自然也就无效（见 keyPressEvent）。保留一个
        # 1 px 的亮框反而在骗用户"选好了"。
        if not self._usable(self._selection):
            self._selection = None
        self.update()

    def _normalize(self, x0: int, y0: int, x1: int, y1: int) -> SelectionRect:
        """一次拖拽的起止点 → 钳制在屏内的选区（拖拽中途的预览也走它）。"""
        return normalize_drag(x0, y0, x1, y1, bounds=self._screen_size())

    # ---------------------------------------------------------------- 键盘

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.selection_cancelled.emit("esc")
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            selection = self._selection
            if not self._usable(selection):
                # 空/过小的选区不确认：留在覆盖层上等用户真的框一下或按 Esc。
                log.debug("快速识屏：空选区或过小选区忽略 Enter")
                return
            self._memory.remember(self._screen_size(), selection)
            self.selection_confirmed.emit(selection)
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        area = self.rect()
        if self._frame is not None and not self._frame.isNull():
            painter.drawImage(area, self._frame)

        selection = self._selection
        if selection is None or selection.is_empty:
            painter.fillRect(area, QColor(0, 0, 0, DIM_ALPHA))
            painter.end()
            return

        hole = QRect(selection.x, selection.y, selection.width, selection.height)
        # 四个边条拼出"除选区外"的遮罩：比 QPainterPath 相减少一次抗锯齿接缝，
        # 也保证选区内像素逐位不改（截图裁的是底图，肉眼看到的也必须是原样）。
        for strip in (
            QRect(area.x(), area.y(), area.width(), hole.y() - area.y()),
            QRect(area.x(), hole.bottom() + 1, area.width(),
                  area.bottom() - hole.bottom()),
            QRect(area.x(), hole.y(), hole.x() - area.x(), hole.height()),
            QRect(hole.right() + 1, hole.y(),
                  area.right() - hole.right(), hole.height()),
        ):
            if strip.width() > 0 and strip.height() > 0:
                painter.fillRect(strip, QColor(0, 0, 0, DIM_ALPHA))
        painter.setPen(BORDER_COLOR)
        for _ in range(BORDER_WIDTH):
            painter.drawRect(hole.adjusted(0, 0, -1, -1))
        painter.end()
