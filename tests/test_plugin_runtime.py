# -*- coding: utf-8 -*-
"""Phase 2 进程内插件运行时：Registry / Context / 生命周期 / 配置命名空间。"""

from __future__ import annotations

import pytest

from pet.plugins.capabilities import CapabilityDenied, CapabilitySet
from pet.plugins.config import FESTIVAL_LEGACY_CONFIG_MAP, JsonConfig, PluginConfigStore
from pet.plugins.events import CoreEvent
from pet.plugins.manifest import PluginManifest, PluginManifestError, version_satisfies
from pet.plugins.ports import CommandRegistry, ContentProviderRegistry, PresentationPort
from pet.plugins.runtime import PluginRegistry


class _Config:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saved = 0

    def save(self):
        self.saved += 1
        return True


class _FakeHandle:
    def __init__(self):
        self.active = True

    def cancel(self):
        self.active = False

    def is_active(self):
        return self.active


class _FakeScheduler:
    def __init__(self):
        self.handles = {}
        self._on_error = None
        self._next = 1

    def set_error_handler(self, handler):
        self._on_error = handler

    def call_later(self, callback, delay_ms, *, owner="core"):
        del callback, delay_ms
        handle = _FakeHandle()
        self.handles[(owner, self._next)] = handle
        self._next += 1
        return handle

    def call_repeating(self, callback, interval_ms, *, owner="core"):
        return self.call_later(callback, interval_ms, owner=owner)

    def cancel_owner(self, owner):
        for (handle_owner, _), handle in self.handles.items():
            if handle_owner == owner:
                handle.cancel()

    def timer_count(self, owner=None):
        return sum(
            1
            for (handle_owner, _), handle in self.handles.items()
            if handle.active and (owner is None or handle_owner == owner)
        )


def _manifest(plugin_id, *, dependencies=(), capabilities=(), default_enabled=True):
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        kind="in_process",
        api_version="1",
        core_requires=">=5.0.0,<6.0.0",
        dependencies=tuple(dependencies),
        capabilities=tuple(capabilities),
        default_enabled=default_enabled,
    )


def _registry(config=None, *, legacy_config=None, scheduler=None, presentation=None):
    return PluginRegistry(
        config=config if config is not None else _Config(),
        legacy_config=legacy_config,
        scheduler=scheduler or _FakeScheduler(),
        presentation=presentation or PresentationPort(),
        commands=CommandRegistry(),
        content=ContentProviderRegistry(),
    )


def test_manifest_rejects_unknown_entrypoints_and_bad_ids():
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict(
            {
                "id": "Bad Id",
                "name": "x",
                "version": "1.0.0",
                "kind": "in_process",
                "api_version": "1",
            }
        )
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict(
            {
                "id": "test.entry",
                "name": "x",
                "version": "1.0.0",
                "kind": "in_process",
                "api_version": "1",
                "entrypoint": "run.py",
            }
        )


@pytest.mark.parametrize(
    "version, spec, expected",
    [
        ("5.0.0", ">=5.0.0,<6.0.0", True),
        ("6.0.0", ">=5.0.0,<6.0.0", False),
        ("5.2.1", "*", True),
        ("5.2.1", "", True),
    ],
)
def test_version_satisfies(version, spec, expected):
    assert version_satisfies(version, spec) is expected


def test_event_payload_must_be_json_serializable():
    with pytest.raises(TypeError):
        CoreEvent.now("test", "unit", {"value": object()})


def test_event_callback_fault_is_isolated_and_subscription_removed():
    registry = _registry()
    events = []

    class BadPlugin:
        def __init__(self, context):
            self.context = context

        def start(self):
            self.context.events.subscribe("test.event", self._on_event)

        def _on_event(self, event):
            del event
            raise RuntimeError("callback failed")

    registry.register_builtin(_manifest("test.bad"), BadPlugin, enabled=True)
    registry.start_all()
    assert registry.get("test.bad").state == "running"

    registry.events.subscribe("test.event", lambda event: events.append(event.type), owner="core.test")
    registry.publish_event("test.event", source="unit", payload={})

    assert events == ["test.event"]
    assert registry.get("test.bad").state == "fault"
    assert registry.events.subscriptions(owner="test.bad") == ()
    assert any(item.plugin_id == "test.bad" and item.stage == "event" for item in registry.diagnostics())


def test_a_factory_registered_after_discovery_is_picked_up():
    registry = _registry()
    registry.discover()

    class LatePlugin:
        pass

    registry.register_builtin(_manifest("test.late"), LatePlugin, enabled=True)

    assert registry.get("test.late").manifest.id == "test.late"
    assert not any(item.plugin_id == "test.late" and item.stage == "discovery" for item in registry.diagnostics())


def test_dependencies_start_topologically_and_stop_in_reverse():
    order = []
    registry = _registry()

    class Plugin:
        def __init__(self, name):
            self.name = name

        def start(self):
            order.append(f"start:{self.name}")

        def stop(self):
            order.append(f"stop:{self.name}")

    registry.register_builtin(
        _manifest("test.child", dependencies=("test.base",)),
        lambda context: Plugin("child"),
        enabled=True,
    )
    registry.register_builtin(_manifest("test.base"), lambda context: Plugin("base"), enabled=True)

    registry.start_all()
    assert order[:2] == ["start:base", "start:child"]
    registry.stop_all()
    assert order[-2:] == ["stop:child", "stop:base"]


def test_a_failing_dependency_never_starts_its_dependent():
    started = []
    registry = _registry()

    class Broken:
        def start(self):
            raise RuntimeError("base unavailable")

    class Child:
        def start(self):
            started.append("child")

    registry.register_builtin(_manifest("test.base"), lambda context: Broken(), enabled=True)
    registry.register_builtin(
        _manifest("test.child", dependencies=("test.base",)),
        lambda context: Child(),
        enabled=True,
    )

    registry.start_all()

    assert started == []
    assert registry.get("test.base").state == "fault"
    assert registry.get("test.child").state == "fault"
    assert any(item.stage == "dependency" and item.plugin_id == "test.child" for item in registry.diagnostics())


def test_capability_denial_faults_only_the_plugin():
    registry = _registry()

    class Greedy:
        def __init__(self, context):
            self.context = context

        def start(self):
            self.context.presentation.show_bubble("hello")

    registry.register_builtin(_manifest("test.greedy"), Greedy, enabled=True)
    registry.start_all()

    record = registry.get("test.greedy")
    assert record.state == "fault"
    assert any(item.plugin_id == "test.greedy" and item.stage == "start" for item in registry.diagnostics())


def test_config_namespace_is_isolated_per_plugin():
    first = _Config()
    second = _Config()
    one = PluginConfigStore(first, "test.one")
    two = PluginConfigStore(second, "test.two")

    one.set("value", 1)
    two.set("value", 2)

    assert one.get("value") == 1
    assert two.get("value") == 2
    assert first.data["plugins"]["test.one"]["settings"]["value"] == 1
    assert second.data["plugins"]["test.two"]["settings"]["value"] == 2


def test_legacy_mapping_reads_and_mirrors_back_to_the_core_config():
    namespace = _Config()
    core = _Config({"festival_reminder_enabled": True, "unrelated": "keep"})
    store = PluginConfigStore(
        namespace,
        "official.festival-reminder",
        legacy_config=core,
        legacy_map=FESTIVAL_LEGACY_CONFIG_MAP,
    )

    assert store.get("enabled") is True
    assert store.get("festival_reminder_enabled") is True

    store.set("enabled", False)
    assert core.data["festival_reminder_enabled"] is False
    assert core.data["unrelated"] == "keep"


def test_legacy_changes_from_the_settings_page_flow_back_into_the_namespace():
    namespace = _Config()
    core = _Config({"festival_reminder_count": 2})
    store = PluginConfigStore(
        namespace,
        "official.festival-reminder",
        legacy_config=core,
        legacy_map=FESTIVAL_LEGACY_CONFIG_MAP,
    )
    assert store.get("count") == 2

    core.data["festival_reminder_count"] = 3
    assert store.get("count") == 3


def test_save_writes_both_books(tmp_path):
    namespace = JsonConfig(tmp_path / "plugins.json")
    core = _Config({"festival_reminder_enabled": False})
    store = PluginConfigStore(
        namespace,
        "official.festival-reminder",
        legacy_config=core,
        legacy_map=FESTIVAL_LEGACY_CONFIG_MAP,
    )

    store.set("enabled", True)
    assert store.save() is True
    assert core.saved == 1
    assert '"enabled": true' in (tmp_path / "plugins.json").read_text(encoding="utf-8")


def test_plugin_config_rejects_non_json_values():
    store = PluginConfigStore(_Config(), "test.json")
    with pytest.raises(ValueError):
        store.set("bad", object())


def test_a_plugin_without_settings_capability_cannot_write():
    store = PluginConfigStore(
        _Config(),
        "test.readonly",
        capabilities=CapabilitySet({"settings.read"}),
    )
    assert store.get("value") is None
    with pytest.raises(CapabilityDenied):
        store.set("value", 1)
