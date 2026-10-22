"""前台应用信息：给识屏请求附一条低成本的上下文。

只读 ``GetForegroundWindow`` 的进程名与标题，不抓取窗口内容、不落盘。非 Windows
或读取失败时返回空串——调用方按「没有参考信息」处理，绝不因此阻断截图。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
from pathlib import Path

logger = logging.getLogger("petcore.platform.foreground")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def foreground_window_info() -> dict | None:
    """``{pid, process, title}``；窗口不可见/最小化或平台不支持时返回 ``None``。"""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowTextW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_ulong,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None

        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()

        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = ""
        if pid.value:
            handle = kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
            )
            if handle:
                try:
                    name = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    if kernel32.QueryFullProcessImageNameW(
                        handle, 0, name, ctypes.byref(size)
                    ):
                        process = Path(name.value).name
                finally:
                    kernel32.CloseHandle(handle)
        return {"pid": int(pid.value), "process": process, "title": title}
    except (AttributeError, OSError, TypeError, RuntimeError, ValueError):
        logger.debug("foreground window lookup failed", exc_info=True)
        return None


def foreground_app_info() -> str:
    """「进程名 | 窗口标题」；拿不到返回空串。"""
    info = foreground_window_info()
    if not info:
        return ""
    parts = [str(item) for item in (info.get("process"), info.get("title")) if item]
    return " | ".join(parts)
