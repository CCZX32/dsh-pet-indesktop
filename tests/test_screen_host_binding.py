# -*- coding: utf-8 -*-
"""DLC 识屏包线·宿主绑定：``bind_screen_context`` 的端口形状与窗口/偏好语义。

真文件（tmp_path 下的 feature-data/<owner>/）、真原子写、真内核锁；
呈现提供方用假的（生产侧是 AppShell 注册的 MultiWindowProxy 语义面）。
"""

from __future__ import annotations

import json

import pytest
from pet.config import Config
from pet.credentials import CredentialError, CredentialVaultPort
from pet.feature_host_bindings import (
    bind_local_context,
    bind_screen_context,
    register_screen_presentation,
)
from pet.feature_ports import FeatureWindowState
from pet.official_features import SCREEN_FEATURE_ID

OWNER = SCREEN_FEATURE_ID


def _root(tmp_path):
    return Config(base=tmp_path).dir / "feature-data" / OWNER


class _FakeVaultBackend:
    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


class _FakePresentation:
    """MultiWindowProxy 语义面的最小假货：气泡/占用/同步全记录。"""

    def __init__(self, *, visible=True, external=False):
        self._visible = visible
        self.bubbles = []
        self.holds = []
        self.synced = []
        self.external = [] if external else None
        self.agent_link_manager = None
        mouse_through = False
        self.mouse_through = mouse_through

    def isVisible(self):
        return self._visible

    def show_bubble(self, text, duration_ms=4500):
        self.bubbles.append((text, duration_ms))

    def hold_bubble(self, seconds):
        self.holds.append(seconds)

    def on_look_synced(self, user_text, reply):
        self.synced.append((user_text, reply))


@pytest.fixture
def presentation():
    register_screen_presentation(None)
    yield
    register_screen_presentation(None)


# --------------------------------------------------------------- 端口形状


def test_screen_context_grants_owner_scoped_ports(tmp_path, presentation):
    context = bind_screen_context(Config(base=tmp_path))
    assert context.owner == OWNER
    assert context.desktop is not None  # 4A 的桌面查询端口注入
    assert context.api is None  # 识屏包走独立视觉配置，不读聊天 Key
    assert context.legacy_secret_reader is None  # 不移植 legacy 迁移
    assert context.credentials is not None and context.preferences is not None and context.window is not None
    assert set(context.documents) == {"memory"}
    assert set(context.state_documents) == {"state", "dry_state"}
    # 端口根仍是 owner 自己的 feature-data 目录，不进 app 配置树
    context.configuration.commit_namespace({"settings": {}}, expected_revision=context.configuration.revision())
    assert (_root(tmp_path) / "configuration.json").is_file()
    assert OWNER not in json.dumps(Config(base=tmp_path).data, ensure_ascii=False)


def test_local_context_still_gets_none_of_the_screen_ports(tmp_path):
    context = bind_local_context(Config(base=tmp_path), "demo.x")
    assert context.credentials is None and context.preferences is None and context.window is None
    assert context.desktop is None


def test_screen_context_rejects_a_foreign_owner(tmp_path, presentation):
    with pytest.raises(ValueError):
        bind_screen_context(Config(base=tmp_path), owner="demo.impostor")


# --------------------------------------------------------------- 配置 journal


def test_configuration_journal_roundtrips_and_defaults_to_none(tmp_path, presentation):
    context = bind_screen_context(Config(base=tmp_path))
    config = context.configuration
    assert config.read_journal() is None
    journal = {"phase": "prepared", "created_refs": ["a"], "retired_refs": []}
    config.write_journal(journal)
    assert config.read_journal() == journal
    assert json.loads((_root(tmp_path) / "configuration.journal.json").read_text(encoding="utf-8")) == journal


# --------------------------------------------------------------- 偏好面


def test_preferences_stage_is_draft_and_flush_persists(tmp_path, presentation):
    context = bind_screen_context(Config(base=tmp_path))
    preferences = context.preferences
    assert preferences.read() == {}
    preferences.stage({"enabled": True, "whitelist": ["msedge.exe"]})
    assert preferences.read()["enabled"] is True  # stage 后立即可读（与上游 cfg.set 同口径）
    assert not (_root(tmp_path) / "preferences.json").is_file()  # 但未落盘
    assert preferences.flush() is True
    assert json.loads((_root(tmp_path) / "preferences.json").read_text(encoding="utf-8"))["whitelist"] == ["msedge.exe"]
    # 重新绑定后读到落盘值
    assert bind_screen_context(Config(base=tmp_path)).preferences.read()["enabled"] is True


def test_preferences_refuse_fields_outside_the_grant(tmp_path, presentation):
    preferences = bind_screen_context(Config(base=tmp_path)).preferences
    with pytest.raises(PermissionError):
        preferences.stage({"api_key": "不该出现的字段"})


# --------------------------------------------------------------- 凭据库


def test_credentials_vault_is_scoped_to_the_screen_owner(tmp_path, presentation):
    backend = _FakeVaultBackend()
    vault = CredentialVaultPort(OWNER, "test-instance", backend=backend)
    context = bind_screen_context(Config(base=tmp_path), vault=vault)
    ref = context.credentials.reserve()
    context.credentials.save("shared", "https://api.example.com", "sk-test", ref=ref)
    assert context.credentials.acquire(ref, "shared", "https://api.example.com", "manual_look") == "sk-test"
    with pytest.raises(CredentialError):
        context.credentials.acquire(ref, "shared", "https://api.example.com", "chat.send")


# --------------------------------------------------------------- 窗口端口


def test_window_ports_degrade_without_a_presentation_provider(tmp_path, presentation):
    window = bind_screen_context(Config(base=tmp_path)).window
    state = window.snapshot()
    assert isinstance(state, FeatureWindowState)
    assert state.visible is False and state.interacting is False
    assert window.enabled() is False
    assert window.agent_busy("code.exe", "t") is False
    window.show_bubble("没人看得见", 100)  # 不炸、不投递
    window.sync_text("q", "a")


def test_window_ports_fan_out_to_the_registered_provider(tmp_path, presentation):
    fake = _FakePresentation(external=False)
    register_screen_presentation(lambda: fake)
    window = bind_screen_context(Config(base=tmp_path), authorized=lambda: True).window
    assert window.snapshot().visible is True
    window.show_bubble("你好", 1200)
    window.hold_bubble(3.0)
    window.sync_text("q", "a")
    assert fake.bubbles == [("你好", 1200)]
    assert fake.holds == [3.0]
    assert fake.synced == [("q", "a")]
    # 没有 on_external_text 的提供方：external_text 回退 sync_text（上游同口径）
    window.external_text("rid", "manual", "q2", "a2")
    assert fake.synced[-1] == ("q2", "a2")


def test_window_enabled_requires_the_host_authority(tmp_path, presentation):
    fake = _FakePresentation()
    register_screen_presentation(lambda: fake)
    context = bind_screen_context(Config(base=tmp_path))
    assert context.window.enabled() is False  # 未过 bind_context 授权
    context2 = bind_screen_context(Config(base=tmp_path), authorized=lambda: True)
    assert context2.window.enabled() is True


# --------------------------------------------------------------- 识屏→聊天联动（app 面）


def test_sync_text_reaches_the_builtin_chat_session_store(tmp_path, presentation):
    """包 → 内置聊天面的真实落点：sync_text → on_look_synced → SessionStore 落盘。

    窗口侧那一小段是 ``PetInstance.sync_look_to_chat`` 的同语义替身（它的既有覆盖在
    ``test_overlay_chat_proactive.py``）；这里验的是**包的端口面**接到内置聊天存储后
    真的写出一条「用户问 + 宠物答」。
    """
    from pet.chat.models import ChatMessage
    from pet.chat.session_store import SessionStore

    config = Config(base=tmp_path)
    store = SessionStore(config.dir, "")
    session = store.create("shenshen", "test-provider", "你是桌宠")
    assert store.save(session)
    assert store.flush()

    class _Windowish:
        def on_look_synced(self, user_text, reply):
            store.append_messages(session, [ChatMessage("user", str(user_text)), ChatMessage("assistant", str(reply))])

    provider = _FakePresentation()
    windowish = _Windowish()
    provider.on_look_synced = windowish.on_look_synced
    register_screen_presentation(lambda: provider)
    window = bind_screen_context(config, authorized=lambda: True).window
    window.sync_text("[主动识屏] 前台进程：code.exe（写代码）", "你在写代码呀")
    loaded = store.load(session.session_id, "shenshen")
    assert loaded is not None
    roles = [(m.role, str(m.content)) for m in loaded.messages]
    assert ("user", "[主动识屏] 前台进程：code.exe（写代码）") in roles
    assert ("assistant", "你在写代码呀") in roles
