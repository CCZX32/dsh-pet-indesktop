# -*- coding: utf-8 -*-
"""Phase 2 内核移植：CoreEventBus 的契约测试（纯 Python、GUI 线程同步语义）。

以上游 Phase 2 内核分支的 ``pet/plugins/events.py`` 为参考实现，钉住
owner 隔离、派发快照、错误回调与 ``clear_owner`` 这四条既定语义。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pet.plugins.events import CoreEvent, CoreEventBus, ScopedEventBus
from pet.plugins.feature_host import FeatureDefinition, FeatureHost


def _boom(event):
    del event
    raise RuntimeError("callback failed")


# ----------------------------------------------------------------- CoreEvent

def test_event_now_uses_a_timezone_aware_timestamp():
    event = CoreEvent.now("core.app.started", "core")
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timezone.utc.utcoffset(datetime.now(timezone.utc))


def test_a_naive_timestamp_is_normalized_to_utc():
    event = CoreEvent(type="test.event", source="unit", timestamp=datetime(2026, 1, 1), payload={})
    assert event.timestamp.tzinfo is timezone.utc


def test_event_type_and_source_must_be_non_empty_strings():
    with pytest.raises(ValueError):
        CoreEvent.now("", "unit")
    with pytest.raises(ValueError):
        CoreEvent.now("   ", "unit")
    with pytest.raises(ValueError):
        CoreEvent.now("test.event", "")
    with pytest.raises(ValueError):
        CoreEvent.now("test.event", "  ")


def test_event_payload_must_be_a_json_serializable_dict():
    with pytest.raises(TypeError):
        CoreEvent(type="test.event", source="unit", timestamp=datetime.now(timezone.utc), payload="not-a-dict")
    with pytest.raises(TypeError):
        CoreEvent.now("test.event", "unit", {"value": object()})


# ------------------------------------------------------------- subscribe 校验

def test_subscribe_validates_event_type_owner_and_callback():
    bus = CoreEventBus()
    with pytest.raises(ValueError):
        bus.subscribe("", lambda event: None, owner="owner")
    with pytest.raises(ValueError):
        bus.subscribe("test.event", lambda event: None, owner=" ")
    with pytest.raises(TypeError):
        bus.subscribe("test.event", "not-callable", owner="owner")


def test_publish_accepts_only_core_events():
    bus = CoreEventBus()
    with pytest.raises(TypeError):
        bus.publish("test.event")


# ----------------------------------------------------------------- 派发语义

def test_publish_filters_by_event_type_and_supports_the_wildcard():
    bus = CoreEventBus()
    seen = []
    bus.subscribe("test.event", lambda event: seen.append(("typed", event.type)), owner="a")
    bus.subscribe("*", lambda event: seen.append(("wild", event.type)), owner="b")
    bus.publish(CoreEvent.now("test.event", "unit"))
    bus.publish(CoreEvent.now("other.event", "unit"))
    assert seen == [("typed", "test.event"), ("wild", "test.event"), ("wild", "other.event")]


def test_unsubscribe_accepts_the_subscription_or_its_token():
    bus = CoreEventBus()
    seen = []
    first = bus.subscribe("test.event", lambda event: seen.append(1), owner="a")
    second = bus.subscribe("test.event", lambda event: seen.append(2), owner="b")
    bus.unsubscribe(first)
    bus.unsubscribe(second.token)
    bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == []
    bus.unsubscribe(first)  # 幂等：重复退订不炸


def test_publish_dispatches_over_a_snapshot_of_the_subscriptions():
    bus = CoreEventBus()
    seen = []

    def first(event):
        del event
        seen.append("first")
        bus.subscribe("test.event", lambda _event: seen.append("late"), owner="late")

    bus.subscribe("test.event", first, owner="first")
    bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == ["first"]  # 派发中新增的订阅不进当次派发
    bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == ["first", "first", "late"]


def test_unsubscribing_during_dispatch_skips_the_removed_callback():
    bus = CoreEventBus()
    seen = []
    holder = {}

    def first(event):
        del event
        seen.append("first")
        bus.unsubscribe(holder["second"])

    bus.subscribe("test.event", first, owner="first")
    holder["second"] = bus.subscribe("test.event", lambda event: seen.append("second"), owner="second")
    bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == ["first"]


# ------------------------------------------------------------- 错误隔离

def test_a_faulting_callback_is_removed_and_the_error_handler_is_called():
    bus = CoreEventBus()
    captured = []
    bus.set_error_handler(lambda subscription, event, exc: captured.append((subscription.owner, event.type, str(exc))))
    bus.subscribe("test.event", _boom, owner="bad")
    bus.publish(CoreEvent.now("test.event", "unit"))
    assert captured == [("bad", "test.event", "callback failed")]
    assert bus.subscriptions(owner="bad") == ()


def test_a_faulting_callback_does_not_block_other_subscribers(caplog):
    bus = CoreEventBus()
    seen = []
    bus.subscribe("test.event", _boom, owner="bad")
    bus.subscribe("test.event", lambda event: seen.append(event.type), owner="good")
    with caplog.at_level("ERROR", logger="pet.plugins.events"):
        bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == ["test.event"]
    assert bus.subscriptions(owner="bad") == ()
    assert len(bus.subscriptions(owner="good")) == 1
    assert "插件事件回调失败" in caplog.text


def test_an_error_handler_that_raises_does_not_break_dispatch(caplog):
    bus = CoreEventBus()

    def bad_handler(subscription, event, exc):
        del subscription, event, exc
        raise RuntimeError("handler failed")

    bus.set_error_handler(bad_handler)
    seen = []
    bus.subscribe("test.event", _boom, owner="bad")
    bus.subscribe("test.event", lambda event: seen.append(event.type), owner="good")
    with caplog.at_level("ERROR", logger="pet.plugins.events"):
        bus.publish(CoreEvent.now("test.event", "unit"))
    assert seen == ["test.event"]
    assert "处理插件事件回调错误失败" in caplog.text


# ------------------------------------------------------------- owner 隔离

def test_clear_owner_only_clears_that_owner():
    bus = CoreEventBus()
    bus.subscribe("test.event", lambda event: None, owner="a")
    bus.subscribe("test.event", lambda event: None, owner="b")
    bus.clear_owner("a")
    assert bus.subscriptions(owner="a") == ()
    assert len(bus.subscriptions(owner="b")) == 1
    assert len(bus.subscriptions()) == 2 - 1


def test_scoped_event_bus_is_bound_to_its_owner():
    bus = CoreEventBus()
    scoped = ScopedEventBus(bus, "a")
    subscription = scoped.subscribe("test.event", lambda event: None)
    assert subscription.owner == "a"
    assert len(bus.subscriptions(owner="a")) == 1
    scoped.unsubscribe(subscription)
    assert bus.subscriptions(owner="a") == ()


def test_scoped_event_bus_publishes_through_the_shared_bus():
    bus = CoreEventBus()
    seen = []
    ScopedEventBus(bus, "listener").subscribe("test.event", lambda event: seen.append(event.source))
    ScopedEventBus(bus, "speaker").publish(CoreEvent.now("test.event", "speaker"))
    assert seen == ["speaker"]


# ==================================================================
# FeatureHost 生命周期接线：订阅清理、故障隔离、生命周期事件
# ==================================================================

OWNER = "sample.feature"


def _definition(owner=OWNER, *, runtime_factory=None):
    return FeatureDefinition(
        owner,
        (),
        lambda *_args, **_kwargs: None,
        runtime_factory=runtime_factory,
    )


def _host_with_owner(*, enabled=True):
    host = FeatureHost()
    host.provide(_definition(), enabled=enabled)
    return host


def test_a_host_shares_an_injected_bus():
    bus = CoreEventBus()
    host = FeatureHost(events=bus)
    assert host.events is bus


def test_the_event_bus_facade_requires_a_configurable_owner():
    host = FeatureHost()
    with pytest.raises(PermissionError):
        host.event_bus(OWNER)
    host.provide(_definition(), enabled=False)
    assert isinstance(host.event_bus(OWNER), ScopedEventBus)


def test_disable_fault_and_remove_each_clear_the_owners_subscriptions():
    transitions = (
        lambda host: host.disable(OWNER),
        lambda host: host.fault(OWNER, "boom"),
        lambda host: host.remove(OWNER),
    )
    for transition in transitions:
        host = _host_with_owner()
        host.event_bus(OWNER).subscribe("test.event", lambda event: None)
        assert len(host.events.subscriptions(owner=OWNER)) == 1
        transition(host)
        assert host.events.subscriptions(owner=OWNER) == ()


def test_fault_and_remove_clear_subscriptions_even_when_already_disabled():
    transitions = (
        lambda host: host.fault(OWNER, "boom"),
        lambda host: host.remove(OWNER),
    )
    for transition in transitions:
        host = _host_with_owner(enabled=False)
        host.event_bus(OWNER).subscribe("test.event", lambda event: None)
        transition(host)
        assert host.events.subscriptions(owner=OWNER) == ()


def test_an_event_callback_failure_faults_the_owner():
    host = _host_with_owner()
    host.event_bus(OWNER).subscribe("test.event", _boom)
    host.events.publish(CoreEvent.now("test.event", "core.test"))
    assert host.state(OWNER) == "fault"
    assert host.diagnostics()[OWNER] == "event_callback_failed"
    assert host.events.subscriptions(owner=OWNER) == ()


def test_a_faulting_callback_from_an_unknown_owner_is_only_logged(caplog):
    host = _host_with_owner()
    host.events.subscribe("test.event", _boom, owner="core.test")
    with caplog.at_level("WARNING", logger="pet.plugins.feature_host"):
        host.events.publish(CoreEvent.now("test.event", "core.test"))
    assert host.state(OWNER) == "enabled"
    assert host.diagnostics() == {}


def test_lifecycle_changes_are_published_on_the_bus():
    host = FeatureHost()
    seen = []
    host.events.subscribe("feature.lifecycle.changed", seen.append, owner="core.test")
    host.provide(_definition(), enabled=False)
    host.enable(OWNER)
    host.disable(OWNER)
    assert [(event.payload["owner"], event.payload["state"]) for event in seen] == [(OWNER, "enabled"), (OWNER, "disabled")]
    assert all(event.source == "core.feature_host" for event in seen)
