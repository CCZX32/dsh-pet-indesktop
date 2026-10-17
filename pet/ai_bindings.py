# -*- coding: utf-8 -*-
"""Core 侧的 AI 呈现路由：聊天包拿到的桌宠形面，永远不是 PetWindow 本体。

Ported from the DLC branch ``pet/ai_bindings.py`` ——只搬**呈现面**那一半
（``AiPetView`` / ``AiFileView``）。上游同文件的另一半（``runtime_for_instance`` /
``view_for_instance`` / ``bind_ai_window`` / ``build_ai_menu``）在本仓库**不移植**，
理由是拓扑不同而不是没做：

* 上游那半把 Core 的 ``instance.open_chat`` 等回调经 ``host.attach`` 挂成包的
  菜单命令——前提是上游 Core 里已经没有内置聊天（聊天整包化）。本仓库内置 AI
  对话**不动**，包开的是自己的窗口，命令由包自己的 Runtime 提供
  （``features/ai-chat/host/runtime_mount.AiPackageRuntime.commands``）；
* 包消费**桌宠的呈现快照面**（在哪、头像、聊天状态、位置变动通知），另有
  通知与打开本包设置两条窄回调。它们按进程级提供方注册（与识屏包同一套做法，
  见 :func:`pet.feature_host_bindings.register_screen_presentation`），
  包在每次开窗时惰性解析。

面里给出去的只有"应用产出的值"：几何、头像位图、状态文本与位置订阅。没有截图、
没有全局 Config、没有任意调用——与上游同一份受限口径。
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRect
from PySide6.QtGui import QPixmap
from shiboken6 import isValid


@dataclass(frozen=True, slots=True)
class _PetViewRef:
    """一个**弱**引用；桌宠窗口销毁后呈现面自动降级为空值。"""

    target: Callable[[], object | None]

    def live(self):
        window = self.target()
        if window is None:
            return None
        if isinstance(window, QObject) and not isValid(window):
            return None
        return window


class AiPetView:
    """受限的桌宠呈现面：**不是**桌面查询端口，也不是 PetWindow。

    几何与头像是应用产出的值；位置订阅与聊天状态是仅有的两处变更面。
    """

    __slots__ = ("_ref",)

    def __init__(self, ref: _PetViewRef) -> None:
        self._ref = ref

    @classmethod
    def of(cls, window) -> AiPetView:
        return cls(_PetViewRef(weakref.ref(window)))

    def _live(self):
        return self._ref.live()

    def visible_content_rect(self) -> QRect:
        window = self._live()
        if window is None:
            return QRect()
        method = getattr(window, "visible_content_rect", None)
        return QRect(method()) if callable(method) else QRect(window.frameGeometry())

    def frameGeometry(self) -> QRect:  # noqa: N802 - 既有的呈现 ABI 命名
        window = self._live()
        if window is None:
            return QRect()
        method = getattr(window, "frameGeometry", None)
        return QRect(method()) if callable(method) else QRect()

    def icon_pixmap(self, size: int = 64) -> QPixmap:
        window = self._live()
        method = getattr(window, "icon_pixmap", None) if window is not None else None
        return QPixmap(method(size)) if callable(method) else QPixmap()

    def set_chat_status(self, state: str, text: str = "") -> None:
        window = self._live()
        method = getattr(window, "set_chat_status", None) if window is not None else None
        if callable(method):
            method(state, text)

    def add_position_listener(self, callback) -> None:
        window = self._live()
        method = getattr(window, "add_position_listener", None) if window is not None else None
        if callable(method):
            method(callback)

    def remove_position_listener(self, callback) -> None:
        window = self._live()
        method = getattr(window, "remove_position_listener", None) if window is not None else None
        if callable(method):
            method(callback)


class AiFileView(AiPetView):
    """拖文件解读的 Core 呈现面：多一个它要读的 ``cfg``（包的配置适配器）。

    上游同名的类就是"在 AiPetView 上补一个 cfg 与三条气泡/告警调用"；这里照做——
    控制器只消费 ``cfg`` / ``show_alert`` / ``resolve_alert`` / ``show_bubble`` 四项。
    """

    __slots__ = ("cfg",)

    def __init__(self, window, config) -> None:
        super().__init__(window._ref if isinstance(window, AiPetView) else _PetViewRef(weakref.ref(window)))
        self.cfg = config

    def show_alert(self, text, **options) -> None:
        window = self._live()
        method = getattr(window, "show_alert", None) if window is not None else None
        if callable(method):
            method(text, **options)

    def resolve_alert(self, identity) -> None:
        window = self._live()
        method = getattr(window, "resolve_alert", None) if window is not None else None
        if callable(method):
            method(identity)

    def show_bubble(self, text, *, duration_ms: int = 3200) -> None:
        window = self._live()
        method = getattr(window, "show_bubble", None) if window is not None else None
        if callable(method):
            method(text, duration_ms=duration_ms)


#: 进程级呈现提供方工厂（AppShell 注册；``None`` = 没有呈现面，安全降级）。
_AI_PET_VIEW: Callable[[], object] | None = None
_AI_WINDOW_CALLBACKS: tuple[Callable | None, Callable | None] = (None, None)
_FILE_INTERPRET_ROUTER = None


def register_ai_pet_view(factory: Callable[[], object] | None, *, notifier=None, auth_callback=None) -> None:
    """注册呈现工厂及窗口回调；``None`` 一并清除，退出后不保留 Core 引用。"""
    global _AI_PET_VIEW, _AI_WINDOW_CALLBACKS
    if any(value is not None and not callable(value) for value in (factory, notifier, auth_callback)):
        raise TypeError("AI presentation providers must be callable")
    _AI_PET_VIEW = factory
    _AI_WINDOW_CALLBACKS = (notifier, auth_callback) if factory is not None else (None, None)


def ai_window_callbacks() -> tuple[Callable | None, Callable | None]:
    """只给通知与固定 owner 的设置导航，不暴露 Core 配置或凭据。"""
    return _AI_WINDOW_CALLBACKS


def register_file_interpret_router(router) -> None:
    """Register the process-wide drag-file router (``None`` clears it on exit)."""
    global _FILE_INTERPRET_ROUTER
    _FILE_INTERPRET_ROUTER = router


def file_interpret_router():
    """The router Core installed, or ``None`` when the package runs standalone."""
    return _FILE_INTERPRET_ROUTER


def ai_pet_view() -> AiPetView | None:
    """解析当下的桌宠呈现面；没有提供方（或提供方已销毁）时返回 ``None``。"""
    factory = _AI_PET_VIEW
    if factory is None:
        return None
    try:
        window = factory()
    except Exception:
        return None
    if window is None:
        return None
    if isinstance(window, AiPetView):
        return window if window._live() is not None else None
    if isinstance(window, QObject) and not isValid(window):
        return None
    return AiPetView.of(window)
