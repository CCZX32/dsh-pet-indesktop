# -*- coding: utf-8 -*-
"""节日提醒 in-process 插件：端口装配、启停、提醒与旧配置键映射。"""

from __future__ import annotations

import pytest

from pet.plugins.builtin.festival_reminder import FESTIVAL_MANIFEST, FESTIVAL_PLUGIN_ID, FestivalReminderPlugin
from pet.plugins.config import PluginConfigStore
from pet.plugins.ports import CommandRegistry, ContentProviderRegistry, PresentationPort
from pet.plugins.runtime import PluginRegistry


class _Config:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saved = 0

    def save(self):
        self.saved += 1
        return True


class _Handle:
    def __init__(self):
        self.active = True

    def cancel(self):
        self.active = False

    def is_active(self):
        return self.active


class _Scheduler:
    def __init__(self):
        self.calls = []
        self._on_error = None

    def set_error_handler(self, handler):
        self._on_error = handler

    def call_later(self, callback, delay_ms, *, owner="core"):
        handle = _Handle()
        self.calls.append((callback, delay_ms, owner, handle))
        return handle

    def call_repeating(self, callback, interval_ms, *, owner="core"):
        return self.call_later(callback, interval_ms, owner=owner)

    def cancel_owner(self, owner):
        for _callback, _delay, call_owner, handle in self.calls:
            if call_owner == owner:
                handle.cancel()

    def timer_count(self, owner=None):
        return sum(
            1 for _c, _d, call_owner, handle in self.calls
            if handle.active and (owner is None or call_owner == owner)
        )


class _Presentation:
    def __init__(self):
        self.bubbles = []
        self.notifications = []
        self.spoken = []

    def show_bubble(self, text, **kwargs):
        self.bubbles.append((text, kwargs))
        return True

    def notify(self, title, message, **kwargs):
        self.notifications.append((title, message, kwargs))
        return True

    def speak(self, text, **kwargs):
        self.spoken.append((text, kwargs))
        return True


def _registry(*, legacy_config=None, presentation=None):
    registry = PluginRegistry(
        config=_Config(),
        legacy_config=legacy_config if legacy_config is not None else _Config(),
        scheduler=_Scheduler(),
        presentation=presentation or _Presentation(),
        commands=CommandRegistry(),
        content=ContentProviderRegistry(),
    )
    registry.register_builtin(FESTIVAL_MANIFEST, FestivalReminderPlugin, enabled=True)
    return registry


def test_the_plugin_manages_the_festival_service_through_ports():
    presentation = _Presentation()
    registry = _registry(
        legacy_config=_Config(
            {
                "festival_reminder_enabled": True,
                "festival_reminder_cn": True,
                "festival_reminder_solar_terms": False,
                "festival_reminder_west": False,
                "festival_reminder_times": ["09:00"],
                "festival_reminder_speak": True,
            }
        ),
        presentation=presentation,
    )

    registry.start(FESTIVAL_PLUGIN_ID)

    record = registry.get(FESTIVAL_PLUGIN_ID)
    assert record is not None and record.state == "running"
    plugin = record.instance
    assert isinstance(plugin, FestivalReminderPlugin)
    assert plugin.service.is_running()
    assert registry.scheduler.timer_count(FESTIVAL_PLUGIN_ID) == 1

    plugin.remind_now()

    assert presentation.bubbles or presentation.notifications
    assert presentation.spoken, "speak=True 时语音端口必须收到文本"

    registry.stop(FESTIVAL_PLUGIN_ID)

    assert registry.get(FESTIVAL_PLUGIN_ID).state == "stopped"
    assert not plugin.service.is_running()
    assert registry.scheduler.timer_count(FESTIVAL_PLUGIN_ID) == 0


def test_toggle_writes_the_legacy_key_and_saves_both_books():
    legacy = _Config({"festival_reminder_enabled": False})
    registry = _registry(legacy_config=legacy)
    registry.start(FESTIVAL_PLUGIN_ID)
    plugin = registry.get_instance(FESTIVAL_PLUGIN_ID)

    plugin.toggle()

    assert legacy.data["festival_reminder_enabled"] is True
    assert legacy.saved == 1
    assert plugin.context.config.get("enabled") is True


def test_the_plugin_is_isolated_from_the_signed_feature_host():
    """Phase 2 的 in-process 插件不碰签名功能包的安装状态。"""
    registry = _registry()
    registry.start(FESTIVAL_PLUGIN_ID)
    record = registry.get(FESTIVAL_PLUGIN_ID)
    assert record.manifest.kind == "in_process"
    assert not hasattr(record.instance, "submit")
    assert not hasattr(record.instance, "service_root")


def test_stopping_the_registry_stops_the_service_timer():
    registry = _registry(legacy_config=_Config({"festival_reminder_enabled": True}))
    registry.start(FESTIVAL_PLUGIN_ID)
    plugin = registry.get_instance(FESTIVAL_PLUGIN_ID)

    registry.stop_all()

    assert not plugin.service.is_running()
    assert registry.scheduler.timer_count() == 0
