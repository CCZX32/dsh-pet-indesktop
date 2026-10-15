# -*- coding: utf-8 -*-
"""官方 AI 对话包·宿主核：验签装载、配置适配器、会话存储、运行时与识屏联动。

全部走真链：``build_ai_chat_package`` 真打包 → ``official_package_verifier`` 真验签 →
``FeaturePackageLoader`` 从验签字节导入 → ``bind_ai_context`` 真端口绑定。
凭据是内存后端假货，桌宠呈现面是 FakePetView 假货；**网络请求在本文件不出现**
（没有配 Key 的 provider 只会走到"没配 Key"那条拒绝路径）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtWidgets import QApplication

from pet.credentials import CredentialError, CredentialVaultPort
from pet.feature_host_bindings import bind_ai_context
from pet.official_features import AI_FEATURE_ID
from pet.plugins.feature_host import FeatureHost
from tests.ai_package_fakes import (
    OWNER,
    FakePetView,
    MemoryVault,
    assert_not_frozen_source_leak,
    build_package,
    dispose_qobject,
    import_pkg,
    load_host,
)

app = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return build_package(tmp_path_factory.mktemp("ai-pkg") / "built")


@pytest.fixture
def bound(built, tmp_path, monkeypatch):
    """验签装载 + 官方宿主绑定 + 内存凭据后端。

    ``bind_context`` 只在 owner **已 provide** 之后才给上下文（宿主的授权次序），
    所以装载、provide、绑定三步都收在这个夹具里。
    """
    from pet.config import Config

    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    handle = load_host(built)[2]
    # 会话写盘的开关是**进程级**的（包模块按验签代次缓存，跨用例复用同一份 module）：
    # 上一个用例收口时的 ``close_all_writers`` 会把它永久关掉，所以每个用例先复位。
    writers(handle).reset_writers_for_tests()
    vault = CredentialVaultPort(OWNER, "test-instance", backend=MemoryVault())
    host = FeatureHost()
    raw = bind_ai_context(Config(base=tmp_path), vault=vault, authorized=lambda: host.enabled(OWNER), host=host)
    try:
        host.provide(handle.factory(), enabled=True)
        yield host, host.bind_context(raw), vault, handle
    finally:
        try:
            host.remove(OWNER)
        finally:
            writers(handle).reset_writers_for_tests()
            handle.close()


def writers(handle):
    return import_pkg(handle, "host.chat.session_store")


# --------------------------------------------------------------- 装载与声明


def test_package_loads_through_the_verified_chain(built):
    _loader, descriptor, handle = load_host(built)
    try:
        assert descriptor.id == OWNER
        assert descriptor.execution_kind == "host-only"
        assert descriptor.version == "1.0.0"
    finally:
        handle.close()


def test_the_factory_declares_owner_menus_runtime_and_settings(bound):
    _host, _context, _vault, handle = bound
    definition = handle.factory()
    assert definition.owner == OWNER
    assert [contribution.id for contribution in definition.menus] == ["chat", "quick_chat"]
    assert {contribution.command for contribution in definition.menus} == {"chat", "quick_chat"}
    assert callable(definition.runtime_factory) and callable(definition.settings_factory)
    # host-only：不许请求 Worker，也不许走包外进程
    assert definition.worker_launch_factory is None
    assert definition.allow_in_process is True
    # mod/v1 挂载契约是本仓库 GenericModMounts 的入场券
    assert definition.mount_contract == "mod/v1"


def test_the_factory_refuses_a_foreign_owner_context(bound):
    _host, _context, _vault, handle = bound
    definition = handle.factory()
    with pytest.raises(TypeError):
        definition.settings_factory(object())


def test_the_definition_never_pulls_qt_into_a_headless_probe(bound):
    """``create_host`` 只造声明：不 import 窗口/服务/网络实现。

    探针与构建门都会跑这一句，它们不该为了问"包的 owner 是谁"把整只聊天 UI 图
    拉进进程。
    """
    _host, _context, _vault, handle = bound
    before = set(__import__("sys").modules)
    handle.factory()
    after = set(__import__("sys").modules)
    added = {name for name in after - before if name.startswith(handle.namespace)}
    assert added == set(), added


def test_the_load_chain_never_pollutes_sys_path(built):
    assert_not_frozen_source_leak()


# --------------------------------------------------------------- 配置适配器


def test_configuration_reads_and_commits_its_own_namespace(bound):
    _host, context, _vault, handle = bound
    config_module = import_pkg(handle, "host.config")
    config = config_module.AiConfiguration(context)
    assert config.get("chat_ui_style", "modern") == "modern"
    config.set("chat_ui_style", "classic")
    assert config.save() is True
    assert context.configuration.read_namespace()["ui"]["chat_ui_style"] == "classic"


def test_configuration_refuses_fields_outside_the_ui_grant(bound):
    _host, context, _vault, handle = bound
    config = import_pkg(handle, "host.config").AiConfiguration(context)
    with pytest.raises(PermissionError):
        config.get("api_key")
    with pytest.raises(PermissionError):
        config.set("providers", {})


def test_a_stale_commit_is_refused_by_the_namespace_cas(bound):
    """乐观并发：别人先写了一步，旧 revision 的提交必须被拒（不是静默覆盖）。"""
    _host, context, _vault, handle = bound
    module = import_pkg(handle, "host.config")
    config = module.AiConfiguration(context)
    stale = config._revision
    other = module.AiConfiguration(context)
    other.set("chat_ui_style", "classic")
    assert other.save() is True
    config.set("chat_ui_style", "modern")
    with pytest.raises(Exception) as excinfo:
        context.configuration.commit_namespace(config._staged, expected_revision=stale)
    assert "configuration_changed" in str(getattr(excinfo.value, "code", "") or excinfo.value)


def test_the_provider_secret_goes_through_the_credential_vault(bound):
    """API Key 只经凭据库：配置命名空间里出现明文 key 一律拒绝。"""
    _host, context, vault, handle = bound
    module = import_pkg(handle, "host.config")
    models = import_pkg(handle, "host.chat.models")
    config = module.AiConfiguration(context)
    provider = models.ProviderConfig("openai-main", api_key_ref="")
    ref = config.save_provider_secret(provider, "sk-test")
    assert ref
    assert "sk-test" not in json.dumps(context.configuration.read_namespace(), ensure_ascii=False)

    settings = models.ChatSettings.from_dict(
        {
            "active_provider": "openai-main",
            "providers": {"openai-main": {"api_key": "sk-plain"}},
        }
    )
    with pytest.raises(CredentialError):
        config.set_chat_settings(settings)


def test_the_legacy_secret_reader_is_refused_not_silently_used(bound):
    _host, context, _vault, handle = bound
    config = import_pkg(handle, "host.config").AiConfiguration(context)
    with pytest.raises(CredentialError):
        config.require_execution() if context.execution_authorized() is False else context.legacy_secret_reader("provider/openai-main")


# --------------------------------------------------------------- 会话存储


def test_sessions_land_under_the_packages_own_root(bound, tmp_path):
    _host, context, _vault, handle = bound
    store_module = writers(handle)
    models = import_pkg(handle, "host.chat.models")
    store = store_module.SessionStore(context.user_data.root, context.user_data.instance_id)
    assert store.root == context.user_data.root / "sessions"
    session = store.create("shenshen", "openai-main", "你是桌宠")
    session.messages.append(models.ChatMessage("user", "你好"))
    assert store.save(session) is True
    assert store.flush() is True
    loaded_back = store.load(session.session_id, "shenshen")
    assert loaded_back is not None and loaded_back.messages[0].content == "你好"
    # 真落盘在**包自己的**目录下（不是 app 配置树，也不是内置聊天的 sessions）
    assert (store.root / "shenshen" / f"{session.session_id}.json").is_file()
    assert store.root.is_relative_to(context.user_data.root)


# --------------------------------------------------------------- 运行时


def test_the_runtime_pauses_resumes_and_closes_idempotently(bound):
    _host, context, _vault, handle = bound
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        assert set(runtime.commands) == {"chat", "quick_chat"}
        runtime.start()
        assert runtime.runtime.accepting is True
        runtime.stop()
        assert runtime.runtime.accepting is False
        runtime.start()
        assert runtime.runtime.accepting is True
    finally:
        dispose_qobject(runtime)
    runtime.close()
    runtime.close()  # 幂等
    assert runtime.runtime.accepting is False


def test_the_runtime_refuses_windows_before_execution_is_authorized(bound):
    _host, context, _vault, handle = bound
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        runtime.stop()
        assert runtime.chat() is None  # 未授权 → 不开窗，不抛
    finally:
        dispose_qobject(runtime)


def test_every_window_kind_the_package_offers_can_actually_open(bound):
    """四种窗口各自构造一遍：包内 UI 是移植过来的，不能只验"import 得过"。

    上游 ``create_window`` 支持 modern / classic / quick / island 四种；本仓库的
    拓扑适配（配置适配器、主题取美术的路径、pet 形呈现面）任何一处接错，
    都只会在这里露出来——菜单只走 modern 那一条。
    """
    from pet.ai_bindings import register_ai_pet_view

    _host, context, _vault, handle = bound
    register_ai_pet_view(lambda: FakePetView())
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        for kind in ("modern", "classic", "quick", "island"):
            window = runtime.runtime.create_window(kind, view=mount_module._pet_view())
            assert window is not None, kind
            assert type(window).__module__.startswith("_pet_official_ai_chat_"), kind
            window.close()
    finally:
        register_ai_pet_view(None)
        dispose_qobject(runtime)


def test_the_package_builds_its_file_interpret_controller(bound):
    """拖文件解读控制器：包侧能建起来，且消费的是 Core 的 ``AiFileView``。"""
    from pet.ai_bindings import AiFileView, register_ai_pet_view

    _host, context, _vault, handle = bound
    fake = FakePetView()
    register_ai_pet_view(lambda: fake)
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        controller = runtime.runtime.create_file_interpreter(mount_module._pet_view())
        assert controller is not None
        assert isinstance(controller._win, AiFileView)
        assert controller._win.cfg is runtime.runtime.config
        controller.suspend_execution()
    finally:
        register_ai_pet_view(None)
        dispose_qobject(runtime)


def test_the_package_settings_dialog_opens_against_its_own_config(bound):
    """设置对话框（经典那套）也能在包的配置适配器上开起来。"""
    _host, context, _vault, handle = bound
    config = import_pkg(handle, "host.config").AiConfiguration(context)
    dialog_module = import_pkg(handle, "host.chat.settings_dialog")
    name = next(name for name in dir(dialog_module) if name.endswith("Dialog") and not name.startswith("_"))
    dialog = getattr(dialog_module, name)(config)
    try:
        assert getattr(dialog, "config", config) is config
    finally:
        dialog.close()
        dialog.deleteLater()


def test_the_package_island_chat_speaks_the_island_bubble_contract(bound):
    """岛对话气泡：包侧那一半要能与 Core 的岛段同形（文本 + 样式）。

    本片只验包内这一半（Core 侧的岛段接线不在片内）；这里钉的是"它读的配置键
    与样式预设仍然存在"，避免适配时把 `self_talk_bubble_style` 这类键读废。
    """
    _host, context, _vault, handle = bound
    config = import_pkg(handle, "host.config").AiConfiguration(context)
    island = import_pkg(handle, "host.island_chat")
    bubble = island.IslandChatBubble(config)
    try:
        assert bubble.isVisible() is False  # 未 show 前创建成功即通过
    finally:
        bubble.close()
        bubble.deleteLater()


def test_closing_the_runtime_leaves_the_core_exit_gate_clean(bound):
    """关掉的包不许继续占着 Core 的退出闸门（停用/卸载后立刻不再挡退出）。

    这是本仓库补的一处收口：上游只靠闸门轮询 ``drain_status`` 回收，于是
    "关掉之后、下一次退出事件之前"那段窗口里登记的是一份已死的参与者——每装一次
    包多一份，全都要等一次真 Quit 才清掉。这里钉住"显式退订"。
    """
    from pet.async_exit import application_exit_gate

    _host, context, _vault, handle = bound
    gate = application_exit_gate(QApplication.instance())
    before = dict(gate.blockers)
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        assert len(gate.blockers) == len(before) + 1
    finally:
        runtime.close()
    assert gate.blockers == tuple(before.values())


def test_the_runtime_refuses_execution_without_the_lifecycle_ports(bound):
    """没有 ``bind_execution``/``execution_authorized`` 的裸上下文 → 拒绝构造。

    这是"包不许自授权"的那条线：拿不到宿主注入的执行转换就不许起来。
    """
    from dataclasses import replace
    from tempfile import mkdtemp

    from pet.config import Config

    _host, _context, _vault, handle = bound
    raw = bind_ai_context(Config(base=mkdtemp()), vault=CredentialVaultPort(OWNER, "t", backend=MemoryVault()))
    runtime_module = import_pkg(handle, "host.runtime")
    with pytest.raises(PermissionError):
        runtime_module.AiRuntime(replace(raw, execution_authorized=None))
    with pytest.raises(PermissionError):
        runtime_module.AiRuntime(replace(raw, bind_execution=None))


# --------------------------------------------------------------- 识屏↔聊天联动


def _screen_request(handle, bound, *, payload, result_id="r1", route=None):
    services = import_pkg(handle, "host.chat.external_turns")
    from pet.plugins.services import ServiceRequest, ServiceRoute

    return services, ServiceRequest("official.screen-understanding", route or ServiceRoute("window-1", "primary", "shenshen"), dict(payload))


def test_an_external_turn_from_the_screen_package_lands_in_the_package_store(bound):
    """联动面：识屏包投一条结构化结果 → 写进**聊天包自己的**会话存储。"""
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    models = import_pkg(handle, "host.chat.models")
    store_module = writers(handle)
    from pet.plugins.services import ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context),
        route,
        lambda: None,
        authorized=lambda: True,
    )
    result = receiver.receive(
        __import__("pet.plugins.services", fromlist=["ServiceRequest"]).ServiceRequest(
            "official.screen-understanding",
            route,
            {"result_id": "r1", "kind": "manual", "user_text": "屏幕上是代码", "reply": "你在写代码呀"},
        )
    )
    assert result.status == "accepted"
    store = store_module.SessionStore(context.user_data.root, context.user_data.instance_id)
    sessions = store.list("shenshen")
    assert sessions, "包侧没有落盘会话"
    roles = [(message.role, message.content) for message in sessions[0].messages]
    assert ("user", "屏幕上是代码") in roles
    assert ("assistant", "你在写代码呀") in roles
    writers(handle).close_all_writers()
    del models


def test_an_external_turn_is_denied_for_a_foreign_owner_or_route(bound):
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    from pet.plugins.services import ServiceRequest, ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context), route, lambda: None, authorized=lambda: True
    )
    payload = {"result_id": "r1", "kind": "manual", "user_text": "q", "reply": "a"}
    assert receiver.receive(ServiceRequest("demo.impostor", route, payload)).status == "denied"
    other_route = ServiceRoute("window-1", "primary", "someone-else")
    assert receiver.receive(ServiceRequest("official.screen-understanding", other_route, payload)).status == "denied"


def test_a_malformed_external_turn_is_invalid(bound):
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    from pet.plugins.services import ServiceRequest, ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context), route, lambda: None, authorized=lambda: True
    )
    good = {"result_id": "r1", "kind": "manual", "user_text": "q", "reply": "a"}
    for bad in (
        {**good, "kind": "spontaneous"},  # 未登记的种类
        {**good, "reply": "   "},  # 空答复
        {**good, "result_id": ""},  # 空回执号
        {**good, "extra": "x"},  # 多字段
        {k: (1 if k == "result_id" else v) for k, v in good.items()},  # 非字符串
    ):
        assert receiver.receive(ServiceRequest("official.screen-understanding", route, bad)).status == "invalid", bad


def test_a_replayed_external_turn_is_duplicate_not_a_second_pair(bound):
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    store_module = writers(handle)
    from pet.plugins.services import ServiceRequest, ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context), route, lambda: None, authorized=lambda: True
    )
    payload = {"result_id": "same", "kind": "automatic", "user_text": "q", "reply": "a"}
    assert receiver.receive(ServiceRequest("official.screen-understanding", route, payload)).status == "accepted"
    # 同一回执号再来一次：不生成第二对消息
    assert receiver.receive(ServiceRequest("official.screen-understanding", route, payload)).status == "duplicate"
    store = store_module.SessionStore(context.user_data.root, context.user_data.instance_id)
    sessions = store.list("shenshen")
    user_messages = [message for item in sessions for message in item.messages if message.role == "user"]
    assert len(user_messages) == 1
    writers(handle).close_all_writers()


def test_an_external_turn_is_refused_when_the_receiver_is_not_authorized(bound):
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    from pet.plugins.services import ServiceRequest, ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context), route, lambda: None, authorized=lambda: False
    )
    payload = {"result_id": "r1", "kind": "manual", "user_text": "q", "reply": "a"}
    assert receiver.receive(ServiceRequest("official.screen-understanding", route, payload)).status == "denied"


def test_the_service_route_hands_the_payload_to_the_package_receiver(bound):
    """端到端：``ServiceRegistry`` 上的调用真落到包里的接收方（载荷被摘离且有界）。"""
    _host, context, _vault, handle = bound
    external = import_pkg(handle, "host.chat.external_turns")
    store_module = writers(handle)
    from pet.plugins.services import ServiceRegistry, ServiceRoute

    route = ServiceRoute("window-1", "primary", "shenshen")
    receiver = external.ExternalTurnReceiver(
        import_pkg(handle, "host.config").AiConfiguration(context), route, lambda: None, authorized=lambda: True
    )
    registry = ServiceRegistry()
    service_handle = registry.register(OWNER, external.SERVICE_ID, route, receiver.receive)
    client = registry.bind("official.screen-understanding", route, allowed={external.SERVICE_ID}, authorized=lambda: True)
    try:
        assert client.call(external.SERVICE_ID, {"result_id": "r1", "kind": "manual", "user_text": "q", "reply": "a"}).status == "accepted"
        assert client.call(external.SERVICE_ID, {"result_id": "r2"}).status == "invalid"
    finally:
        service_handle.dispose()
        writers(handle).close_all_writers()


def test_the_runtime_exposes_an_external_receiver(bound):
    """运行时的 ``create_external_receiver`` 是识屏联动在包侧的正门。"""
    _host, context, _vault, handle = bound
    mount_module = import_pkg(handle, "host.runtime_mount")
    from pet.plugins.services import ServiceRoute

    runtime = mount_module.AiPackageRuntime(context)
    try:
        receiver = runtime.runtime.create_external_receiver(ServiceRoute("window-1", "primary", "shenshen"), lambda: None)
        assert callable(receiver.receive)
    finally:
        dispose_qobject(runtime)


def test_fake_pet_view_is_what_the_windows_receive(bound):
    """包开窗时拿到的是受限呈现面（``AiPetView``），不是桌宠本体。"""
    from pet.ai_bindings import AiPetView, register_ai_pet_view

    _host, context, _vault, handle = bound
    fake = FakePetView()
    register_ai_pet_view(lambda: fake)
    mount_module = import_pkg(handle, "host.runtime_mount")
    runtime = mount_module.AiPackageRuntime(context)
    try:
        window = runtime.chat()
        assert window is not None
        view = window.pet_link.pet_window
        assert isinstance(view, AiPetView)
        assert view._live() is fake
    finally:
        register_ai_pet_view(None)
        dispose_qobject(runtime)


def test_ai_feature_id_is_the_only_owner_this_package_answers_to(bound):
    assert OWNER == AI_FEATURE_ID == "official.ai-chat"