"""进程级全局快捷键（Windows RegisterHotKey）。

支持多条并存：每条有独立的 Win32 id 与回调（显示/隐藏、AI 对话、看看屏幕、
截图提问）。``apply()`` 的默认命名保持旧行为（单条 toggle_pet），其余功能用
``name=`` 注册，互不覆盖。
"""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer

from . import hotkey_spec

logger = logging.getLogger("petcore.platform.hotkeys")

WM_HOTKEY = 0x0312
_HOTKEY_BASE = 0xA5D1
DEFAULT_NAME = "toggle_pet"


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
        self._entries: dict[str, dict] = {}
        self._next_id = _HOTKEY_BASE

    @property
    def supported(self) -> bool:
        return self._supported

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def active_text(self) -> str:
        entry = self._entries.get(DEFAULT_NAME)
        return str(entry["text"]) if entry is not None else ""

    def active_texts(self) -> dict[str, str]:
        return {name: str(entry["text"]) for name, entry in self._entries.items()}

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

    def apply(
        self,
        text: str,
        callback: Callable[[], None],
        *,
        name: str = DEFAULT_NAME,
    ) -> tuple[bool, str]:
        name = str(name or DEFAULT_NAME)
        self.clear(name)
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
        hotkey_id = self._next_id
        try:
            ok = bool(
                user32.RegisterHotKey(
                    None,
                    hotkey_id,
                    modifiers | hotkey_spec.MOD_NOREPEAT,
                    vk,
                )
            )
        except Exception as exc:
            return False, f"注册失败：{exc}"
        if not ok:
            return False, "注册失败：这个组合键可能已被其他程序占用"
        self._next_id += 1
        self._entries[name] = {"id": hotkey_id, "text": normalized, "callback": callback}
        logger.info("全局快捷键已生效：%s -> %s", normalized, name)
        return True, ""

    def clear(self, name: str | None = None) -> None:
        names = list(self._entries) if name is None else [str(name)]
        if not names:
            return
        user32 = self._user32
        if user32 is None:
            try:
                user32 = ctypes.windll.user32
            except Exception:
                user32 = None
        for entry_name in names:
            entry = self._entries.pop(entry_name, None)
            if entry is None:
                continue
            if user32 is not None:
                try:
                    user32.UnregisterHotKey(None, int(entry["id"]))
                except Exception:
                    logger.debug("注销全局快捷键失败", exc_info=True)

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message != WM_HOTKEY:
                return False, 0
            wanted = int(msg.wParam)
            for entry in self._entries.values():
                if int(entry["id"]) != wanted:
                    continue
                callback = entry["callback"]
                if callback is not None:
                    QTimer.singleShot(0, callback)
                return True, 0
            return False, 0
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
