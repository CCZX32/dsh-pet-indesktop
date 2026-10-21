"""进程级全局快捷键（Windows RegisterHotKey）。"""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer

from . import hotkey_spec

logger = logging.getLogger("petcore.platform.hotkeys")

WM_HOTKEY = 0x0312
_HOTKEY_ID = 0xA5D1


def is_supported() -> bool:
    return os.name == "nt"


class GlobalHotkeyService(QObject, QAbstractNativeEventFilter):
    def __init__(self, app=None, *, user32=None, supported: bool | None = None) -> None:
        QObject.__init__(self, None)
        QAbstractNativeEventFilter.__init__(self)
        self._app = app if app is not None else QCoreApplication.instance()
        self._user32 = user32
        self._supported = is_supported() if supported is None else bool(supported)
        self._installed = False
        self._registered = False
        self._text = ""
        self._callback: Callable[[], None] | None = None

    @property
    def supported(self) -> bool:
        return self._supported

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def active_text(self) -> str:
        return self._text if self._registered else ""

    def install(self) -> bool:
        if self._installed:
            return True
        if not self._supported or self._app is None:
            return False
        try:
            self._app.installNativeEventFilter(self)
        except Exception:
            logger.warning("安装全局快捷键事件过滤器失败", exc_info=True)
            return False
        self._installed = True
        return True

    def uninstall(self) -> None:
        self.clear()
        if not self._installed:
            return
        self._installed = False
        if self._app is not None:
            try:
                self._app.removeNativeEventFilter(self)
            except Exception:
                logger.debug("摘除全局快捷键过滤器失败", exc_info=True)

    def apply(self, text: str, callback: Callable[[], None]) -> tuple[bool, str]:
        self.clear()
        self._callback = callback
        normalized = hotkey_spec.normalize(text)
        if not normalized:
            return True, ""
        if not self._supported:
            return False, "当前平台不支持全局快捷键"
        parsed = hotkey_spec.parse(normalized)
        if parsed is None:
            return False, "无法识别这个组合键"
        modifiers, vk = parsed
        user32 = self._user32
        if user32 is None:
            try:
                user32 = ctypes.windll.user32
            except Exception as exc:
                return False, f"无法加载 user32：{exc}"
        try:
            ok = bool(
                user32.RegisterHotKey(
                    None,
                    _HOTKEY_ID,
                    modifiers | hotkey_spec.MOD_NOREPEAT,
                    vk,
                )
            )
        except Exception as exc:
            return False, f"注册失败：{exc}"
        if not ok:
            return False, "注册失败：这个组合键可能已被其他程序占用"
        self._registered = True
        self._text = normalized
        logger.info("全局快捷键已生效：%s", normalized)
        return True, ""

    def clear(self) -> None:
        if not self._registered:
            return
        user32 = self._user32
        if user32 is None:
            try:
                user32 = ctypes.windll.user32
            except Exception:
                user32 = None
        if user32 is not None:
            try:
                user32.UnregisterHotKey(None, _HOTKEY_ID)
            except Exception:
                logger.debug("注销全局快捷键失败", exc_info=True)
        self._registered = False
        self._text = ""

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message != WM_HOTKEY or int(msg.wParam) != _HOTKEY_ID:
                return False, 0
            callback = self._callback
            if callback is not None:
                QTimer.singleShot(0, callback)
            return True, 0
        except Exception:
            logger.debug("处理全局快捷键消息失败", exc_info=True)
            return False, 0


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]
