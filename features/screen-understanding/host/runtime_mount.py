# -*- coding: utf-8 -*-
"""mod/v1 挂载契约包装：把 watcher/manual 装进 GenericModMounts 的 Runtime 形状。

策略、配额、代次权威全在 :class:`.runtime.ProactiveScreenWatcher`；这里只做
命令面（``look`` / ``automatic``）与生命周期（start=resume / stop=pause /
close=dispose）的翻译。设置入口命令不直接碰 UI：经 owner 作用域事件总线发布
``feature.settings.open-requested``，由 Core 侧订阅者决定开哪个设置面。
"""

from __future__ import annotations

import logging

from . import current

_LOG = logging.getLogger(__name__)

#: 「打开设置…」菜单命令的事件类型（Core 侧订阅面；没有订阅者时是无害空转）。
SETTINGS_OPEN_EVENT = "feature.settings.open-requested"


class ScreenPackageRuntime:
    def __init__(self, context, *, worker_mode: str = "auto"):
        from .factory import runtime_context
        from .manual import ManualScreenHost
        from .runtime import ProactiveScreenWatcher

        self.host_context = context
        self.context = runtime_context(context)
        self.watcher = ProactiveScreenWatcher(self.context, worker_mode=worker_mode)
        self.manual = ManualScreenHost(self.context, self.watcher.request_manual_look, self.watcher.cancel_manual_look)
        self.commands = {"look": self.look, "automatic": self.automatic}
        self._closed = False
        current.set_current(self.context)

    # --------------------------------------------------------------- 命令面
    def look(self) -> None:
        if self._closed:
            return
        self.manual.start()

    def automatic(self, key=None, value=None) -> None:
        if self._closed:
            return
        if key in (None, "settings"):
            self._request_settings()
            return
        try:
            self.context.preferences.stage({str(key): value})
            self.context.preferences.flush()
        except (PermissionError, TypeError):
            _LOG.warning("主动识屏策略字段被拒绝: %s", key)
            return
        self.watcher.apply_config()

    def _request_settings(self) -> None:
        events = getattr(self.host_context, "events", None)
        if events is None:
            return
        try:
            from pet.plugins.events import CoreEvent

            events.publish(CoreEvent.now(SETTINGS_OPEN_EVENT, self.context_owner, {"owner": self.context_owner}))
        except Exception:
            _LOG.exception("识屏设置打开请求发布失败")

    @property
    def context_owner(self) -> str:
        return str(getattr(self.host_context, "owner", "official.screen-understanding"))

    # ------------------------------------------------------------- 生命周期
    def start(self) -> None:
        if not self._closed:
            self.watcher.resume()

    def stop(self) -> None:
        if not self._closed:
            self.watcher.pause()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        current.clear_current(self.context)
        self.manual.dispose()
        self.watcher.dispose()
