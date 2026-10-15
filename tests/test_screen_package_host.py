# -*- coding: utf-8 -*-
"""官方识屏包·宿主核：验签装载、上下文绑定、运行时协调与识屏→聊天联动。

全部走真链：``build_screen_package`` 真打包 → ``official_package_verifier`` 真验签 →
``FeaturePackageLoader`` 从验签字节导入 → ``bind_screen_context`` 真端口绑定。
凭据是内存后端假货，呈现是 FakePresentation 假货；截图/网络在本文件不出现。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import bind_screen_context, register_screen_presentation
from pet.plugins.feature_host import FeatureHost
from tests.screen_package_fakes import (
    OWNER,
    FakePresentation,
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
    return build_package(tmp_path_factory.mktemp("screen-pkg") / "built")


@pytest.fixture
def loaded(built):
    loader, descriptor, handle = load_host(built)
    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture
def bound(tmp_path, monkeypatch):
    """官方宿主绑定 + 内存凭据后端 + 假呈现提供方。"""
    from pet.credentials import CredentialVaultPort

    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    vault = CredentialVaultPort(OWNER, "test-instance", backend=MemoryVault())
    host = FeatureHost()
    fake = FakePresentation()
    register_screen_presentation(lambda: fake)
    raw = bind_screen_context(Config(base=tmp_path), vault=vault, authorized=lambda: host.enabled(OWNER), host=host)
    try:
        yield host, raw, fake, vault
    finally:
        register_screen_presentation(None)


def _provide(host, handle, *, enabled=True):
    from pet.plugins.feature_host import FeatureDefinition

    definition = handle.factory()
    assert isinstance(definition, FeatureDefinition)
    host.provide(definition, enabled=enabled)
    return definition


# --------------------------------------------------------------- 装载与声明


def test_package_loads_through_the_verified_chain(built):
    _loader, _descriptor, handle = load_host(built)
    try:
        definition = handle.factory()
        assert definition.owner == OWNER
        assert definition.mount_contract == "mod/v1"
        assert [item.id for item in definition.menus] == ["look_screen", "proactive_screen"]
        assert callable(definition.settings_factory) and callable(definition.runtime_factory)
        assert callable(definition.manual_factory) and callable(definition.policy_factory)
        assert definition.policy_factory({"dwell_seconds": 1})["dwell_seconds"] == 15  # clamp 生效
        assert_not_frozen_source_leak()
    finally:
        handle.close()


def test_pure_policy_and_hashing_modules_work_inside_the_package(loaded):
    policy = import_pkg(loaded, "common.policy")
    eff = policy.effective_proactive_config({"preset": "quiet", "enabled": 1})
    assert eff["enabled"] is True and eff["dwell_seconds"] == 90
    assert policy.effective_proactive_config({"preset": "bogus"})["preset"] == "balanced"
    models = import_pkg(loaded, "common.models")
    profile = models.VisionProfile("shared", models.DEFAULT_BASE_URL, models.DEFAULT_MODEL)
    assert profile.endpoint.startswith("https://")
    settings = models.VisionSettings.default()
    assert settings.bindings == {"automatic": "shared", "manual": "shared"}
    hashing = import_pkg(loaded, "common.hashing")
    assert hashing.hamming_distance(0, 0) == 0 and hashing.hamming_distance(0, 0xFFFF) == 16


def test_runtime_factory_rejects_an_unbound_context(loaded, bound):
    host, raw, _fake, _vault = bound
    definition = _provide(host, loaded)
    with pytest.raises(TypeError):
        definition.runtime_factory(Config(base=raw.configuration.read_namespace() and None or None))


# --------------------------------------------------------------- 运行时协调


def test_runtime_mounts_commands_and_stays_idle_without_configuration(loaded, bound, tmp_path):
    host, raw, fake, _vault = bound
    definition = _provide(host, loaded)
    context = host.bind_context(raw)
    runtime = definition.runtime_factory(context, worker_mode="in_process")
    try:
        assert type(runtime).__module__.startswith("_pet_official_screen_")
        assert set(runtime.commands) == {"look", "automatic"}
        assert runtime.watcher.is_running() is False  # 默认配置关：不起定时器
        # 手动看看屏幕：未配置视觉 → 气泡提示，不发请求
        runtime.commands["look"]()
        assert any("填写并保存视觉 API Key" in text for text, _ms in fake.bubbles)
    finally:
        runtime.close()
        dispose_qobject(runtime)


def test_automatic_command_stages_and_flushes_preferences(loaded, bound, tmp_path):
    host, raw, _fake, _vault = bound
    definition = _provide(host, loaded)
    context = host.bind_context(raw)
    runtime = definition.runtime_factory(context, worker_mode="in_process")
    try:
        runtime.commands["automatic"]("enabled", True)
        runtime.commands["automatic"]("dwell_seconds", 30)
        from pet.config import Config as _Config

        saved = _Config(base=tmp_path).dir / "feature-data" / OWNER / "preferences.json"
        import json

        data = json.loads(saved.read_text(encoding="utf-8"))
        assert data["enabled"] is True and data["dwell_seconds"] == 30
        # 授权字段集之外的键被偏好端口拒掉
        runtime.commands["automatic"]("api_key", "nope")
        data = json.loads(saved.read_text(encoding="utf-8"))
        assert "api_key" not in data
    finally:
        runtime.close()
        dispose_qobject(runtime)


def test_disable_stops_execution_and_enable_resumes(loaded, bound):
    host, raw, _fake, _vault = bound
    definition = _provide(host, loaded)
    context = host.bind_context(raw)
    runtime = definition.runtime_factory(context, worker_mode="in_process")
    try:
        assert host.enabled(OWNER) is True
        host.disable(OWNER)
        assert runtime.context.execution_enabled() is False
        host.enable(OWNER)
        assert runtime.context.execution_enabled() is True
    finally:
        runtime.close()
        dispose_qobject(runtime)


# --------------------------------------------------------------- 识屏→聊天联动


def test_automatic_reply_syncs_into_the_chat_surface(loaded, bound):
    """主动识屏的答复经 sync_text → 呈现提供方 on_look_synced（= 内置聊天面入口）。"""
    host, raw, fake, vault = bound
    definition = _provide(host, loaded)
    context = host.bind_context(raw)
    runtime = definition.runtime_factory(context, worker_mode="in_process")
    try:
        runtime.context.vision.save_profile(
            import_pkg(loaded, "common.models").VisionProfile("shared", "https://visual.invalid", "vision-model"),
            modes=["automatic", "manual"],
            secret="TEST-KEY",
            expected_revision=runtime.context.vision.revision(),
        )
        watcher = runtime.watcher
        watcher.apply_config()  # 刷新 vision revision 缓存
        # 进程内完成路径：一代、当前 revision、非空答复 → 气泡 + 限流记账 + 聊天同步
        generation = watcher._generation
        revision = watcher._vision_revision
        watcher._deliver_in_process_result((generation, revision, "你在看代码呢", "code.exe", "写代码"))
        app.processEvents()
        assert fake.bubbles and fake.bubbles[-1][0] == "你在看代码呢"
        assert fake.synced[-1][1] == "你在看代码呢"
        assert fake.synced[-1][0].startswith("[主动识屏] 前台进程：code.exe")
        # 陪伴记忆只记进程与活动分类，不落标题
        latest = runtime.context.memory.read()["entries"][0]
        assert latest["process"] == "code.exe" and latest["activity"] == "写代码" and "title" not in latest
    finally:
        runtime.close()
        dispose_qobject(runtime)


def test_a_stale_generation_reply_never_reaches_the_chat_surface(loaded, bound):
    host, raw, fake, _vault = bound
    definition = _provide(host, loaded)
    context = host.bind_context(raw)
    runtime = definition.runtime_factory(context, worker_mode="in_process")
    try:
        watcher = runtime.watcher
        watcher._deliver_in_process_result((watcher._generation + 1, watcher._vision_revision, "迟到答复", "x.exe", "上网"))
        app.processEvents()
        assert fake.synced == [] and fake.bubbles == []
    finally:
        runtime.close()
        dispose_qobject(runtime)
