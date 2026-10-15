# -*- coding: utf-8 -*-
"""DLC 聊天包线·宿主绑定：``bind_ai_context`` 的端口形状与 owner 作用域。

真文件（tmp_path 下的 feature-data/<owner>/）、真原子写、真内核锁；凭据用内存
后端（绝不碰真实钥匙串）。

与识屏绑定（``test_screen_host_binding.py``）的分工：识屏包拿桌面查询与窗口操作面，
聊天包**不拿**那两样——它要的是"自己的数据根 + 自己那本配置 + 凭据库"，会话与
界面状态全落在自己的 owner 目录下。
"""

from __future__ import annotations

import json

import pytest
from pet.config import Config
from pet.credentials import CredentialError, CredentialVaultPort
from pet.feature_host_bindings import bind_ai_context, bind_local_context
from pet.feature_ports import FeatureUserDataPort
from pet.official_features import AI_FEATURE_ID

OWNER = AI_FEATURE_ID


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


def _vault():
    return CredentialVaultPort(OWNER, "test-instance", backend=_FakeVaultBackend())


# --------------------------------------------------------------- 端口形状


def test_ai_context_grants_owner_scoped_ports(tmp_path):
    context = bind_ai_context(Config(base=tmp_path), vault=_vault())
    assert context.owner == OWNER
    assert context.credentials is not None and context.preferences is not None
    assert context.user_data is not None
    # 三样**故意不给**：桌面查询、窗口操作面、Core 的 API 端口。
    assert context.desktop is None
    assert context.window is None
    assert context.api is None
    assert context.allow_in_process is True
    assert context.worker_launch_factory is None


def test_ai_context_keeps_its_data_out_of_the_app_config_tree(tmp_path):
    """包的数据落在自己的 feature-data 目录，不进 app 配置树（与本地 MOD 同口径）。

    进配置树就会牵动出厂默认表 / 设置搜索别名 / 默认标记（见 AGENTS.md 指向的
    ``docs/SETTINGS-CHANGE-GATES.md``），而这是**包**的数据，不是 Core 的设置项。
    """
    config = Config(base=tmp_path)
    context = bind_ai_context(config, vault=_vault())
    context.configuration.commit_namespace({"ui": {"chat_ui_style": "modern"}}, expected_revision=context.configuration.revision())
    assert (_root(tmp_path) / "configuration.json").is_file()
    assert OWNER not in json.dumps(config.data, ensure_ascii=False)


def test_ai_context_rejects_a_foreign_owner(tmp_path):
    with pytest.raises(ValueError):
        bind_ai_context(Config(base=tmp_path), owner="demo.impostor")


def test_local_context_still_gets_none_of_the_ai_ports(tmp_path):
    context = bind_local_context(Config(base=tmp_path), "demo.x")
    assert context.credentials is None and context.preferences is None and context.user_data is None


# --------------------------------------------------------------- legacy 迁移


def test_the_legacy_secret_reader_never_silently_imports_a_secret(tmp_path):
    """legacy 读取器恒为拒绝：包不会顺着旧引用把明文 key 迁进来。

    本仓库口径与识屏绑定不同（那里恒为 ``None``）：聊天包的配置适配器会**主动**
    调它，所以给的是"调用即拒绝"的显式口子，而不是"没有这个口子"。
    """
    context = bind_ai_context(Config(base=tmp_path), vault=_vault())
    assert context.legacy_secret_reader is not None
    with pytest.raises(CredentialError):
        context.legacy_secret_reader("provider/openai-main")


# --------------------------------------------------------------- 偏好面


def test_ai_preferences_stage_is_a_draft_and_flush_persists(tmp_path):
    context = bind_ai_context(Config(base=tmp_path), vault=_vault())
    preferences = context.preferences
    assert preferences.read() == {}
    preferences.stage({"active_provider": "openai-main", "history_message_limit": 40})
    assert preferences.read()["history_message_limit"] == 40
    assert not (_root(tmp_path) / "preferences.json").is_file()  # 未落盘
    assert preferences.flush() is True
    assert json.loads((_root(tmp_path) / "preferences.json").read_text(encoding="utf-8"))["active_provider"] == "openai-main"


def test_ai_preferences_refuse_fields_outside_the_grant(tmp_path):
    preferences = bind_ai_context(Config(base=tmp_path), vault=_vault()).preferences
    with pytest.raises(PermissionError):
        preferences.stage({"chat_api_key": "明文 key 不许从这条路过"})
    with pytest.raises(PermissionError):
        preferences.stage({"character": "shenshen"})  # 角色不是包的偏好字段


# --------------------------------------------------------------- 凭据库


def test_the_vault_is_scoped_to_the_ai_owner(tmp_path):
    vault = _vault()
    context = bind_ai_context(Config(base=tmp_path), vault=vault)
    ref = context.credentials.reserve()
    context.credentials.save("openai-main", "https://api.deepseek.com", "sk-test", ref=ref)
    assert context.credentials.acquire(ref, "openai-main", "https://api.deepseek.com", "chat.send") == "sk-test"
    # 换个用途（识屏手工看屏）不认这把 key
    with pytest.raises(CredentialError):
        context.credentials.acquire(ref, "openai-main", "https://api.deepseek.com", "manual_look")


# --------------------------------------------------------------- 用户数据面


def test_user_data_is_one_owner_directory_plus_display_snapshot(tmp_path):
    context = bind_ai_context(Config(base=tmp_path), vault=_vault())
    user_data = context.user_data
    assert isinstance(user_data, FeatureUserDataPort)
    assert user_data.root == _root(tmp_path)
    assert user_data.root.is_dir()
    assert user_data.instance_id == ""
    display = user_data.read_display()
    assert display["character"] == "shenshen"
    assert "self_talk_bubble_style" in display


def test_read_display_reflects_the_instance_id_and_the_alias(tmp_path):
    config = Config(base=tmp_path, instance_id="slot-3")
    config.set_character_alias("shenshen", "小三三")
    context = bind_ai_context(config, vault=_vault())
    assert context.user_data.instance_id == "slot-3"
    assert context.user_data.alias_for("shenshen") == "小三三"
    # 无别名的角色回空串（不是回角色 id：别名是"可能的显示名"，不是身份）
    assert context.user_data.alias_for("unknown-id") == ""


def test_the_display_snapshot_is_read_lazily(tmp_path):
    """展示面是**每次调用现读**，不是绑定那一刻的快照。"""
    config = Config(base=tmp_path)
    context = bind_ai_context(config, vault=_vault())
    assert context.user_data.read_display()["character"] == "shenshen"
    config.set("character", "other-pet")
    assert context.user_data.read_display()["character"] == "other-pet"
