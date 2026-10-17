# -*- coding: utf-8 -*-
"""mod/v1 挂载契约包装：把包的 :class:`.runtime.AiRuntime` 装进 Runtime 形状。

策略与生命周期权威全在 :class:`.runtime.AiRuntime`（accepting / pause / resume /
close / drain）；这里只做命令面与生命周期三点的翻译：

* **命令面** ``chat`` / ``quick_chat`` —— 由包自己开自己的窗口（内置 AI 对话
  不动，两项并存）；窗口的 pet 形定位面（``visible_content_rect`` /
  ``icon_pixmap`` / ``add_position_listener``）经 Core 注册的进程级提供方
  **惰性解析**，没注册就退化成"不跟随桌宠"的安全默认；
* **start = resume / stop = pause** —— 宿主的启用态就是包的执行转换
  （``bind_execution``），窗口关没关不影响；
* **close** —— 关服务、放窗口、退订执行转换（幂等）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject

_LOG = logging.getLogger(__name__)


def _file_router():
    """Core 侧的拖文件路由器；独立包宿主没有它时返回 None。"""
    try:
        from pet.ai_bindings import file_interpret_router

        return file_interpret_router()
    except Exception:  # pragma: no cover - Core 面缺失时按"没有路由"降级
        return None


class _WindowCloseWatcher(QObject):
    """把包窗的 Close 事件翻译成"包窗不再打开"，不依赖 WA_DeleteOnClose。"""

    def __init__(self, owner, window) -> None:
        super().__init__(window)
        self._owner = owner
        self._window = window

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.Close:
            self._owner._on_package_window_closed(self._window)
        return False


def _pet_view():
    """Core 侧注册的桌宠呈现面（生产是 AppShell 的聊天窗宿主形态）。"""
    try:
        from pet.ai_bindings import ai_pet_view
    except Exception:  # pragma: no cover - Core 面缺失时按"没有桌宠"降级
        return None
    try:
        return ai_pet_view()
    except Exception:
        _LOG.exception("桌宠呈现面解析失败")
        return None


def _window_callbacks():
    """与呈现面同样惰性解析；独立包宿主没有 Core 呈现时允许无回调运行。"""
    try:
        from pet.ai_bindings import ai_window_callbacks

        return ai_window_callbacks()
    except (ImportError, AttributeError):
        return None, None


class AiPackageRuntime:
    def __init__(self, context):
        from .runtime import AiRuntime

        self.host_context = context
        self.runtime = AiRuntime(context)
        self.commands = {"chat": self.chat, "quick_chat": self.quick_chat}
        self._closed = False
        self._open_windows: dict[int, object] = {}
        self._file_controller = None

    # --------------------------------------------------------------- 命令面
    def chat(self):
        return self._show("modern")

    def quick_chat(self):
        return self._show("quick")

    def _show(self, kind: str):
        if self._closed or not self.runtime.accepting:
            return None
        notifier, auth_callback = _window_callbacks()
        window = self.runtime.create_window(
            kind, view=_pet_view(),
            notifier=self._notify if notifier is not None else None,
            auth_callback=self._open_settings if auth_callback is not None else None,
        )
        if window is not None:
            self._on_package_window_opened(window)
            window.show()
        return window

    # ------------------------------------------------------------ 文件解读路由
    def _on_package_window_opened(self, window) -> None:
        router = _file_router()
        if router is None:
            return
        key = id(window)
        if key in self._open_windows:
            return
        self._open_windows[key] = window
        watcher = _WindowCloseWatcher(self, window)
        window.installEventFilter(watcher)
        window._file_interpret_watcher = watcher
        router.set_package_offer(self.file_interpret_offer)
        if len(self._open_windows) == 1:
            router.package_window_opened()

    def _on_package_window_closed(self, window) -> None:
        router = _file_router()
        key = id(window)
        if self._open_windows.pop(key, None) is None:
            return
        if router is not None and not self._open_windows:
            router.package_window_closed()

    def file_interpret_offer(self, paths) -> None:
        """The package-side interpreter for a file dragged onto the pet."""
        if self._closed or not self.runtime.accepting:
            return
        if self._file_controller is None:
            try:
                self._file_controller = self.runtime.create_file_interpreter(_pet_view())
            except Exception:
                _LOG.exception("包文件解读器创建失败；本次不解读")
                return
        self._file_controller.offer(paths)

    def _open_settings(self):
        if self._closed or not self.runtime.accepting:
            return
        _notifier, callback = _window_callbacks()
        if callback is not None:
            callback()

    def _notify(self, title, message, *, on_click=None):
        if self._closed or not self.runtime.accepting:
            return
        notifier, _auth_callback = _window_callbacks()
        if notifier is None:
            return

        def activate():
            # 通知可能比包活得久；停用、卸载或退出后不再重新打开窗口。
            if not self._closed and self.runtime.accepting and on_click is not None:
                on_click()

        notifier(title, message, on_click=activate)

    # ------------------------------------------------------------- 生命周期
    def start(self) -> None:
        if not self._closed:
            self.runtime.resume()

    def stop(self) -> None:
        if not self._closed:
            self.runtime.pause()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        router = _file_router()
        if router is not None:
            router.set_package_offer(None)
        self._open_windows.clear()
        self._file_controller = None
        self.runtime.close()
