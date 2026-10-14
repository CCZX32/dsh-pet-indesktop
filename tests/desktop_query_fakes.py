# -*- coding: utf-8 -*-
"""pet.desktop_query 的确定性 WinAPI 边界；不导入 Qt 与识屏实现。

移植自上游 DLC 分支 同名文件，裁掉本仓库尚未落地的
consumer 探针（``with_watch_queries``）那一半；结构体尺寸断言一律对着
``pet.desktop_query`` 自己的固定宽度 ABI 类型（wintypes 别名宽度随宿主平台
漂移，见 hdr_capture 教训）。
"""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

from pet import desktop_query as query


class WinCall:
    """ctypes-like callable: signature attributes remain assignable."""

    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


class WindowApi:
    def __init__(self):
        self.hwnd = 0x123456789
        self.hproc = 0x234567891
        self.pid = 1234
        self.visible = True
        self.iconic = False
        self.cloaked = False
        self.rect = (-20, 30, 780, 630)
        self.raw_rect = (-25, 25, 785, 635)
        self.dwm_result = 0
        self.rect_ok = True
        self.image_ok = True
        self.closed = []
        self.user32 = SimpleNamespace(
            GetForegroundWindow=WinCall(lambda: self.hwnd),
            IsWindowVisible=WinCall(lambda hwnd: self.visible),
            IsIconic=WinCall(lambda hwnd: self.iconic),
            GetWindowRect=WinCall(self.get_rect),
            GetWindowTextLengthW=WinCall(lambda hwnd: len("  fixture title  ")),
            GetWindowTextW=WinCall(self.get_title),
            GetWindowThreadProcessId=WinCall(self.get_pid),
        )
        self.kernel32 = SimpleNamespace(
            OpenProcess=WinCall(lambda *args: self.hproc),
            QueryFullProcessImageNameW=WinCall(self.get_image),
            CloseHandle=WinCall(lambda handle: self.closed.append(handle) or 1),
        )
        self.dwmapi = SimpleNamespace(DwmGetWindowAttribute=WinCall(self.get_attribute))
        self.dlls = SimpleNamespace(user32=self.user32, kernel32=self.kernel32, dwmapi=self.dwmapi)

    @staticmethod
    def put_rect(pointer, values):
        rect = ctypes.cast(pointer, ctypes.POINTER(query.WindowRect)).contents
        rect.left, rect.top, rect.right, rect.bottom = values

    def get_rect(self, hwnd, pointer):
        self.put_rect(pointer, self.raw_rect)
        return self.rect_ok

    def get_attribute(self, hwnd, attribute, pointer, size):
        if attribute == 14:
            assert size == ctypes.sizeof(ctypes.c_int32)
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int32)).contents.value = int(self.cloaked)
        elif attribute == 9:
            assert size == ctypes.sizeof(query.WindowRect)
            self.put_rect(pointer, self.rect)
        else:
            raise AssertionError("unexpected DWM attribute")
        return self.dwm_result

    def get_title(self, hwnd, buffer, size):
        buffer.value = "  fixture title  "
        return len(buffer.value)

    def get_pid(self, hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value = self.pid
        return 1

    def get_image(self, handle, flags, buffer, size):
        buffer.value = "/fixture/editor.exe"
        ctypes.cast(size, ctypes.POINTER(ctypes.c_ulong)).contents.value = len(buffer.value)
        return self.image_ok
