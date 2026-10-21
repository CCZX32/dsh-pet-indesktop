from __future__ import annotations

import ctypes
import logging
import os

from PySide6.QtCore import QObject, QRect, Qt, QTimer
from PySide6.QtGui import QCursor

logger = logging.getLogger("petcore.platform.win")

_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


def _user32():
    return ctypes.windll.user32


def set_click_through(hwnd: int, enabled: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        updated = style | _WS_EX_TRANSPARENT if enabled else style & ~_WS_EX_TRANSPARENT
        if updated == style:
            return True
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, updated)
        return True
    except Exception:
        logger.debug("set_click_through failed", exc_info=True)
        return False


def apply_tool_window(hwnd: int) -> None:
    if os.name != "nt":
        return
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
    except Exception:
        logger.debug("apply_tool_window failed", exc_info=True)


def apply_stream_window(hwnd: int) -> None:
    """直播捕获兼容：还原成普通顶层窗口（可被 OBS/直播姬枚举与捕获）。

    Qt 的 ``Tool`` 窗口带 ``WS_EX_TOOLWINDOW``（不进任务栏/Alt-Tab），部分捕获
    后端会直接跳过；``WS_EX_NOACTIVATE`` 还会让窗口拿不到激活态。这里两个都清掉。
    """
    if os.name != "nt":
        return
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        updated = style & ~(_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
        if updated != style:
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, updated)
    except Exception:
        logger.debug("apply_stream_window failed", exc_info=True)


def apply_click_through(window, enabled: bool) -> None:
    if os.name == "nt":
        set_click_through(int(window.winId()), enabled)
        return
    window.setWindowFlag(Qt.WindowType.WindowTransparentForInput, bool(enabled))
    if window.isVisible():
        window.show()


class PerPixelInputController(QObject):
    NORMAL_INTERVAL_MS = 10
    IDLE_INTERVAL_MS = 50

    def __init__(self, window, is_transparent, parent: QObject | None = None):
        super().__init__(parent or window)
        self._window = window
        self._is_transparent = is_transparent
        self._applied: bool | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.NORMAL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        if os.name != "nt":
            return
        window = self._window
        try:
            if not window.isVisible():
                self._apply(False)
                return
            position = QCursor.pos()
            local = window.mapFromGlobal(position)
            inside = QRect(0, 0, window.width(), window.height()).contains(local)
            dragging = bool(getattr(window, "dragging", False))
            interval = self.IDLE_INTERVAL_MS if dragging or not inside else self.NORMAL_INTERVAL_MS
            if self._timer.interval() != interval:
                self._timer.setInterval(interval)
            enabled = bool(getattr(window, "click_through", False))
            if not enabled and inside and not dragging:
                enabled = bool(self._is_transparent(local))
            self._apply(enabled)
        except (RuntimeError, AttributeError):
            logger.debug("per-pixel refresh failed", exc_info=True)

    def _apply(self, enabled: bool) -> None:
        if self._applied == enabled:
            return
        set_click_through(int(self._window.winId()), enabled)
        self._applied = enabled
