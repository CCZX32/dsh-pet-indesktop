# -*- coding: utf-8 -*-
"""节日提醒插件本体：把 FestivalReminderService 接到 Phase 2 的受限端口。

本模块在工厂被调用时才导入 ``pet.festival_service``（连同节日文案表约 2.95MB）；
注册清单走轻量的 :mod:`.manifest`，所以关闭节日提醒时不会为插件付这份导入成本。
"""

from __future__ import annotations

from types import SimpleNamespace

from ....festival_service import FestivalReminderService
from ...events import CoreEvent
from ...ports import CommandHandle
from .manifest import FESTIVAL_PLUGIN_ID


class _FestivalHost:
    """Expose AppShell's legacy presentation seams while owning the plugin config.

    ``FestivalReminderService`` already has the quiet-mode / sprite-in-flight /
    fallback-to-notification semantics; re-implementing them inside
    ``PresentationPort`` for the coexistence step would fork that policy. The
    adapter keeps the exact old path and only replaces ``config``.
    """

    def __init__(self, app, config) -> None:
        self._app = app
        self.config = config

    def __getattr__(self, name):
        return getattr(self._app, name)


class FestivalReminderPlugin:
    """把 FestivalReminderService 接到 Phase 2 的受限服务端口。"""

    def __init__(self, context) -> None:
        self.context = context
        host_app = getattr(context, "host_app", None)
        if host_app is not None:
            # Coexistence path: keep the old AppShell bubble/audio policy.
            host = _FestivalHost(host_app, context.config)
            presentation = None
            audio = None
        else:
            # Port-only path used by standalone tests and future Core wiring.
            host = SimpleNamespace(config=context.config)
            presentation = context.presentation
            audio = context.presentation.speak
        self.service = FestivalReminderService(
            host,
            scheduler=context.scheduler,
            presentation=presentation,
            audio=audio,
            config_source=context.config,
        )
        self._config_subscription = None
        self._command_handles: list[CommandHandle] = []

    def start(self) -> None:
        self.service.start()
        self._config_subscription = self.context.events.subscribe(
            "core.config.changed",
            self._on_config_changed,
        )
        self._command_handles = [
            self.context.commands.register("remind_now", self.remind_now),
            self.context.commands.register("toggle", self.toggle),
        ]

    def stop(self) -> None:
        self.service.stop()
        self._config_subscription = None
        self._command_handles = []

    def apply_config(self) -> None:
        self.service.apply_config()

    def remind_now(self) -> None:
        self.service.remind_now()

    def toggle(self) -> None:
        enabled = not bool(self.context.config.get("enabled", False))
        self.context.config.set("enabled", enabled)
        self.context.config.save()
        self.context.events.publish(
            CoreEvent.now(
                "core.config.changed",
                self.context.plugin_id,
                {"plugin_id": self.context.plugin_id, "key": "enabled"},
            )
        )

    def _on_config_changed(self, _event) -> None:
        self.apply_config()

    def __getattr__(self, name):
        # AppShell 旧 facade 与现有测试继续拿到 _on_tick/should_speak_at 等服务方法。
        return getattr(self.service, name)


__all__ = ["FESTIVAL_PLUGIN_ID", "FestivalReminderPlugin"]
