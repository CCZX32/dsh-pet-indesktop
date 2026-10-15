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

_LOG = logging.getLogger(__name__)


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


class AiPackageRuntime:
    def __init__(self, context):
        from .runtime import AiRuntime

        self.host_context = context
        self.runtime = AiRuntime(context)
        self.commands = {"chat": self.chat, "quick_chat": self.quick_chat}
        self._closed = False

    # --------------------------------------------------------------- 命令面
    def chat(self) -> None:
        self._show("modern")

    def quick_chat(self) -> None:
        self._show("quick")

    def _show(self, kind: str):
        if self._closed or not self.runtime.accepting:
            return None
        window = self.runtime.create_window(kind, view=_pet_view())
        if window is not None:
            window.show()
        return window

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
        self.runtime.close()
