# -*- coding: utf-8 -*-
"""owner 作用域的服务路由（``pet/plugins/services.py``）：GUI 线程内的有界调用面。

蓝本 = DLC 分支的 ``tests/test_feature_text_service.py``。这一层是"一个 owner
（功能包）想调另一个 owner 的能力"的唯一通道：宿主授予 route 与服务名，接收方
自己做业务校验。本仓库的消费者是 AI 对话包的 ``ExternalTurnReceiver``
（识屏包 → 聊天包的文本结果投递）。

用例全是纯逻辑（零 Qt、零时序、零网络）——"边界"在这里是可判定的数据形状与
线程归属，不需要真事件循环。
"""

from __future__ import annotations

import threading

import pytest

from pet.plugins.services import (
    ServiceClient,
    ServiceRegistry,
    ServiceRequest,
    ServiceResult,
    ServiceRoute,
)

SCREEN = "official.screen-understanding"
AI = "official.ai-chat"


def _route(character: str = "shenshen") -> ServiceRoute:
    return ServiceRoute("window-1", "primary", character)


def _registry() -> ServiceRegistry:
    registry = ServiceRegistry()
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: ServiceResult("accepted"))
    return registry


def _client(registry: ServiceRegistry, *, allowed=("chat.external-turn/v1",), owner=SCREEN, authorized=lambda: True) -> ServiceClient:
    return registry.bind(owner, _route(), allowed=set(allowed), authorized=authorized)


# --------------------------------------------------------------- 调用面


def test_a_granted_route_reaches_the_receiver():
    registry = _registry()
    seen: list[ServiceRequest] = []

    def handler(request):
        seen.append(request)
        return ServiceResult("handled")

    registry.register(AI, "chat.answer", _route(), handler).dispose()
    registry.register(AI, "chat.answer", _route(), handler)
    result = _client(registry, allowed=("chat.answer",)).call("chat.answer", {"result_id": "r1"})
    assert result.status == "handled"
    assert seen == [ServiceRequest(SCREEN, _route(), {"result_id": "r1"})]


def test_a_service_outside_the_grant_is_denied():
    registry = _registry()
    result = _client(registry, allowed=("another.service",)).call("chat.external-turn/v1", {})
    assert result.status == "denied"


def test_an_empty_owner_is_denied():
    registry = _registry()
    client = _client(registry, owner="")
    assert client.call("chat.external-turn/v1", {}).status == "denied"


def test_revoked_authority_denies_without_calling_the_receiver():
    registry = ServiceRegistry()
    alive = {"yes": False}
    calls: list[str] = []
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: calls.append("called") or ServiceResult("accepted"))
    client = _client(registry, authorized=lambda: alive["yes"])
    assert client.call("chat.external-turn/v1", {}).status == "denied"
    assert calls == []
    alive["yes"] = True
    assert client.call("chat.external-turn/v1", {}).status == "accepted"


def test_a_route_that_was_never_bound_is_unavailable():
    registry = _registry()
    client = registry.bind(SCREEN, ServiceRoute("window-2", "primary", "shenshen"), allowed={"chat.external-turn/v1"}, authorized=lambda: True)
    assert client.call("chat.external-turn/v1", {}).status == "unavailable"


def test_a_disposed_client_no_longer_calls_anything():
    registry = ServiceRegistry()
    calls: list[str] = []
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: calls.append("called") or ServiceResult("accepted"))
    client = _client(registry)
    client.dispose()
    assert client.call("chat.external-turn/v1", {}).status == "denied"
    assert calls == []


# --------------------------------------------------------------- 接收方收口


def test_disposing_a_handle_only_removes_its_own_receiver():
    registry = ServiceRegistry()
    calls: list[str] = []
    first = registry.register(AI, "chat.external-turn/v1", _route(), lambda request: ServiceResult("first"))
    second = registry.register(AI, "chat.swap", _route(), lambda request: calls.append("second") or ServiceResult("second"))
    first.dispose()
    client = registry.bind(SCREEN, _route(), allowed={"chat.external-turn/v1", "chat.swap"}, authorized=lambda: True)
    assert client.call("chat.external-turn/v1", {}).status == "unavailable"
    assert client.call("chat.swap", {}).status == "second"
    assert calls == ["second"]
    second.dispose()
    assert client.call("chat.swap", {}).status == "unavailable"


def test_disposing_a_handle_twice_is_harmless():
    """句柄作废是幂等的：收口路径（卸载 / 退出）可能重复调。"""
    registry = ServiceRegistry()
    handle = registry.register(AI, "chat.external-turn/v1", _route(), lambda request: ServiceResult("kept"))
    handle.dispose()
    handle.dispose()
    assert _client(registry).call("chat.external-turn/v1", {}).status == "unavailable"


def test_dispose_owner_removes_every_receiver_of_that_owner():
    registry = _registry()
    registry.register(AI, "chat.second", _route(), lambda request: ServiceResult("second"))
    registry.register(SCREEN, "screen.third", _route(), lambda request: ServiceResult("third"))
    registry.dispose_owner(AI)
    client = _client(registry, allowed=("chat.external-turn/v1", "chat.second", "screen.third"))
    assert client.call("chat.external-turn/v1", {}).status == "unavailable"
    assert client.call("chat.second", {}).status == "unavailable"
    assert client.call("screen.third", {}).status == "third"


def test_registering_the_same_key_twice_is_rejected():
    registry = _registry()
    with pytest.raises(ValueError):
        registry.register(AI, "chat.external-turn/v1", _route(), lambda request: ServiceResult("again"))


def test_an_empty_service_name_is_rejected():
    registry = ServiceRegistry()
    with pytest.raises(ValueError):
        registry.register(AI, "", _route(), lambda request: ServiceResult("x"))


# --------------------------------------------------------------- 载荷边界


def test_the_payload_is_detached_from_the_caller():
    registry = ServiceRegistry()
    seen: list[dict] = []
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: seen.append(request.payload) or ServiceResult("ok"))
    payload = {"nested": {"value": 1}}
    assert _client(registry).call("chat.external-turn/v1", payload).status == "ok"
    payload["nested"]["value"] = 2
    assert seen == [{"nested": {"value": 1}}]


def test_a_payload_that_is_not_json_is_invalid_not_an_exception():
    registry = _registry()
    client = _client(registry)
    assert client.call("chat.external-turn/v1", {"bad": object()}).status == "invalid"
    assert client.call("chat.external-turn/v1", {"bad": float("nan")}).status == "invalid"


def test_an_oversized_payload_is_invalid():
    registry = _registry()
    client = _client(registry)
    assert client.call("chat.external-turn/v1", {"text": "x" * (ServiceRegistry.MAX_PAYLOAD_BYTES + 1)}).status == "invalid"


def test_a_payload_at_the_limit_is_still_accepted():
    registry = _registry()
    overhead = len('{"text": ""}')
    client = _client(registry)
    result = client.call("chat.external-turn/v1", {"text": "x" * (ServiceRegistry.MAX_PAYLOAD_BYTES - overhead)})
    assert result.status == "accepted"


# --------------------------------------------------------------- 故障隔离


def test_a_raising_receiver_becomes_fault_not_an_exception():
    registry = ServiceRegistry()
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: (_ for _ in ()).throw(RuntimeError("接收方炸了")))
    assert _client(registry).call("chat.external-turn/v1", {}).status == "fault"


def test_a_receiver_returning_the_wrong_shape_becomes_fault():
    registry = ServiceRegistry()
    registry.register(AI, "chat.external-turn/v1", _route(), lambda request: "不是 ServiceResult")
    assert _client(registry).call("chat.external-turn/v1", {}).status == "fault"


# --------------------------------------------------------------- 线程归属


def test_a_call_from_another_thread_is_refused():
    """路由是 GUI 线程的：跨线程调用显式报错，不静默排队。"""
    registry = _registry()
    client = _client(registry)
    errors: list[BaseException] = []

    def target():
        try:
            client.call("chat.external-turn/v1", {})
        except BaseException as exc:  # noqa: BLE001 - 用例断言的就是"抛出来"
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(30)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "service_thread_mismatch" in str(errors[0])


def test_registering_from_another_thread_is_refused():
    registry = _registry()
    errors: list[BaseException] = []

    def target():
        try:
            registry.register(AI, "chat.other", _route(), lambda request: ServiceResult("x"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(30)
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)


def test_disposing_from_another_thread_is_refused():
    registry = _registry()
    handle = registry.register(AI, "chat.other", _route(), lambda request: ServiceResult("x"))
    errors: list[BaseException] = []

    def target():
        try:
            handle.dispose()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(30)
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
