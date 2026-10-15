# -*- coding: utf-8 -*-
"""DLC 识屏包线·端口层：FeatureHostContext 的识屏扩展字段与窗口/偏好端口。

钉的是**形状与默认值**，不是行为（行为在 test_screen_host_binding.py）：
本地 MOD 路径（``bind_local_context``）一个字段都不许拿到——官方识屏绑定才注入。
"""

from __future__ import annotations

import inspect

from pet.feature_ports import (
    FeatureHostContext,
    FeaturePreferencesPort,
    FeatureWindowPorts,
    FeatureWindowState,
)


def test_host_context_exposes_screen_ports_with_none_defaults():
    context = FeatureHostContext(
        owner="demo.x",
        configuration=None,
        documents={},
        state_documents={},
    )
    assert context.credentials is None
    assert context.legacy_secret_reader is None
    assert context.preferences is None
    assert context.window is None


def test_window_state_is_a_frozen_value_snapshot():
    state = FeatureWindowState("window:1", "primary", "shenshen", "肥鱼", True, False, False)
    assert state.display_name == "肥鱼"
    assert state.visible is True and state.interacting is False and state.mouse_through is False
    for field in ("window_id", "instance_id", "character_id", "display_name", "visible", "interacting", "mouse_through"):
        assert field in FeatureWindowState.__dataclass_fields__


def test_window_ports_hold_only_callables():
    calls = []

    def snapshot():
        return FeatureWindowState("w", "i", "c", "n", False, False, False)

    ports = FeatureWindowPorts(
        snapshot=snapshot,
        agent_busy=lambda proc, title: False,
        show_bubble=lambda text, ms: calls.append((text, ms)),
        hold_bubble=lambda seconds: None,
        sync_text=lambda user, reply: calls.append((user, reply)),
        external_text=lambda rid, kind, user, reply: None,
        enabled=lambda: True,
        bind_lifecycle=lambda stop, resume, dispose: (lambda: None),
    )
    ports.show_bubble("hi", 100)
    ports.sync_text("q", "a")
    assert calls == [("hi", 100), ("q", "a")]
    assert ports.enabled() is True
    assert ports.snapshot().window_id == "w"


def test_preferences_port_is_a_protocol_with_read_stage_flush():
    assert inspect.isclass(FeaturePreferencesPort)
    for name in ("read", "stage", "flush"):
        assert callable(getattr(FeaturePreferencesPort, name, None)), name
