# -*- coding: utf-8 -*-
"""DLC 识屏包线·官方路由：验签策略、管理器参数化、官方 owner 的 attach/发现。

官方闭集（``OFFICIAL_FEATURES``）的包**不走**本地导入路由（防冒名不变）；
它们由 Core 自有入口 ``attach_official`` 装配：验签策略的能力上限取自官方登记，
宿主绑定走 ``bind_screen_context``（凭据/偏好/窗口/桌面），不是 ``bind_local_context``。
"""

from __future__ import annotations

import pytest
from pet.config import Config
from pet.feature_install_state import FeatureInstallStateStore, StateChange
from pet.feature_management import (
    FeatureManagementManager,
    LocalFeatureRuntime,
    discover_official_feature_ids,
)
from pet.feature_policy import FEATURE_CAPABILITIES, official_package_verifier
from pet.feature_host_bindings import bind_screen_context
from pet.official_features import AI_FEATURE_ID, OFFICIAL_FEATURES, SCREEN_FEATURE_ID
from pet.plugins.package_trust import FeaturePackageVerifier

OWNER = SCREEN_FEATURE_ID
DIGEST = "0" * 64


# --------------------------------------------------------------- 验签策略


def test_official_verifier_ceiling_is_the_closed_registry():
    verifier = official_package_verifier(OWNER)
    assert isinstance(verifier, FeaturePackageVerifier)
    assert verifier.feature_id == OWNER
    assert verifier.allow_local_packages is True  # Phase5A 显式用户信任口径
    assert verifier.allowed_capabilities == OFFICIAL_FEATURES[OWNER].capabilities
    assert "screen.capture" in verifier.allowed_capabilities
    # 本地包上限不变（不被官方登记撑大）
    assert "screen.capture" not in FEATURE_CAPABILITIES


def test_official_verifier_refuses_a_non_official_id():
    with pytest.raises(ValueError):
        official_package_verifier("demo.impostor")


def test_official_verifier_supports_only_wired_owners():
    # AI 包的宿主绑定属聊天包线；本片只接识屏。
    with pytest.raises(ValueError):
        official_package_verifier(AI_FEATURE_ID)


# --------------------------------------------------------------- 管理器参数化


def test_manager_accepts_verifier_and_context_overrides(tmp_path):
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        manager = FeatureManagementManager(
            Config(base=tmp_path),
            runtime.host,
            OWNER,
            role="core",
            lifecycle=runtime.lifecycle,
            verifier=official_package_verifier(OWNER),
            context_factory=lambda: bind_screen_context(Config(base=tmp_path)),
        )
        assert manager.verifier.feature_id == OWNER
        assert "screen.capture" in manager.verifier.allowed_capabilities
        context = manager.startup.context_factory()
        assert context.preferences is not None and context.window is not None
    finally:
        runtime.close()


def test_manager_defaults_stay_on_the_local_path(tmp_path):
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        manager = FeatureManagementManager(Config(base=tmp_path), runtime.host, "demo.x", role="core", lifecycle=runtime.lifecycle)
        assert manager.verifier.allowed_capabilities == FEATURE_CAPABILITIES
        context = manager.startup.context_factory()
        assert context.preferences is None  # bind_local_context 不变
    finally:
        runtime.close()


# --------------------------------------------------------------- 官方 attach / 发现


def test_local_attach_still_refuses_official_owners(tmp_path):
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        assert runtime.attach(OWNER) is None
    finally:
        runtime.close()


def test_attach_official_builds_a_screen_manager(tmp_path):
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        manager = runtime.attach_official(OWNER)
        assert manager is not None and manager.owner == OWNER
        assert runtime.managers[OWNER] is manager
        assert "screen.capture" in manager.verifier.allowed_capabilities
        assert manager.startup.context_factory().window is not None
        assert runtime.attach_official(OWNER) is manager  # 幂等
        with pytest.raises(ValueError):
            runtime.attach_official("demo.impostor")
    finally:
        runtime.close()


def test_official_discovery_reads_the_same_ledger(tmp_path):
    config = Config(base=tmp_path)
    assert discover_official_feature_ids(config) == ()
    store = FeatureInstallStateStore(config.dir, feature_id=OWNER)
    store.commit(StateChange({"1.0.0": DIGEST}, active="1.0.0", enabled=False), expected_revision=0, operation_id="install-1")
    assert discover_official_feature_ids(config) == (OWNER,)
    # 本地发现依旧跳过官方 owner（两条链不混）
    from pet.feature_management import discover_local_feature_ids

    assert OWNER not in discover_local_feature_ids(config)
