"""前台应用信息：给识屏请求附一条低成本的上下文。

只读 ``GetForegroundWindow`` 的进程名、标题与窗口矩形，不抓取窗口内容、不落盘。
非 Windows 或读取失败时返回空串/``None``——调用方按「没有参考信息」处理，绝不
因此阻断截图。窗口矩形优先 DWM 的 ``EXTENDED_FRAME_BOUNDS``（不含投影边框），
失败才退回 ``GetWindowRect``；UWP 的幽灵窗口（cloaked）一律当成没有窗口。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
from pathlib import Path

logger = logging.getLogger("petcore.platform.foreground")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14


def _window_rect(hwnd) -> tuple[int, int, int, int] | None:
    """``(x, y, w, h)`` 屏幕坐标；DWM 取不到就退回 ``GetWindowRect``。"""
    rect = ctypes.wintypes.RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmGetWindowAttribute.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        result = dwmapi.DwmGetWindowAttribute(
            hwnd,
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return (
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
    except (AttributeError, OSError, TypeError, ValueError):
        logger.debug("dwm frame bounds failed", exc_info=True)
    try:
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
    except (AttributeError, OSError, TypeError, ValueError):
        logger.debug("GetWindowRect failed", exc_info=True)
    return None


def _is_cloaked(hwnd) -> bool:
    """UWP 应用停下后窗口仍「可见」但被 DWM 隐藏，抓图会拿到别的内容。"""
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmGetWindowAttribute.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        cloaked = ctypes.c_uint(0)
        result = dwmapi.DwmGetWindowAttribute(
            hwnd,
            _DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return result == 0 and bool(cloaked.value)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def idle_seconds() -> float:
    """距离最后一次键鼠输入的秒数；平台不支持或读取失败返回 0（= 不判定闲置）。"""
    if sys.platform != "win32":
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        elapsed = int(ctypes.windll.kernel32.GetTickCount()) - int(info.dwTime)
        return max(0.0, elapsed / 1000.0)
    except (AttributeError, OSError, TypeError, ValueError):
        logger.debug("idle query failed", exc_info=True)
        return 0.0


def foreground_window_info() -> dict | None:
    """``{pid, process, title, hwnd, rect}``；窗口不可见/最小化/cloaked 或平台
    不支持时返回 ``None``。"""
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
        if _is_cloaked(hwnd):
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
        return {
            "pid": int(pid.value),
            "process": process,
            "title": title,
            "hwnd": int(hwnd),
            "rect": _window_rect(hwnd),
        }
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
