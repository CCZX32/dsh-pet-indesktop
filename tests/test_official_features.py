# -*- coding: utf-8 -*-
"""Closed official registry + registration shape (host-adapted).

Blueprint: the DLC branch's ``tests/test_official_feature_contracts.py``. The parts
that need the feature-host runtime (``default_feature_host``, ``FeaturePackageLoader``,
``FeatureHost``) are not portable and live behind the S1c seam; the registry,
identity and registration rules are the ported production code.
"""

from __future__ import annotations

import pytest

from pet import official_features as of


def test_the_registry_is_closed_and_frozen():
    assert set(of.OFFICIAL_FEATURES) == {of.SCREEN_FEATURE_ID, of.AI_FEATURE_ID}
    assert of.SCREEN_OWNER == of.SCREEN_FEATURE_ID and of.AI_OWNER == of.AI_FEATURE_ID
    with pytest.raises(TypeError):
        of.OFFICIAL_FEATURES["official.other"] = None


def test_each_registration_matches_its_declared_contract():
    screen = of.official_feature(of.SCREEN_FEATURE_ID)
    assert (screen.factory, screen.execution_kind) == ("screen-understanding/v1", "host-worker")
    assert "screen.capture" in screen.capabilities
    chat = of.official_feature(of.AI_FEATURE_ID)
    assert (chat.factory, chat.execution_kind) == ("ai-chat/v1", "host-only")
    assert chat.id != screen.id


def test_an_unknown_or_malformed_owner_is_refused():
    for value in ("official.unknown", "", None, 7, "Official.Screen"):
        with pytest.raises(ValueError, match="unsupported official feature"):
            of.official_feature(value)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("official.screen-understanding", True),
        ("local.user-package_1", True),
        ("a", True),
        ("../escape", False),
        ("official..screen", False),
        ("-leading-dash", False),
        ("", False),
        ("x" * 129, False),
        (None, False),
        (7, False),
        # 规范形收紧（ID 会变成 feature-data/<id>/ 与 plugins/<id>/ 的**目录名**）：
        # NTFS 不区分大小写、Win32 折叠末尾点/空格，所以"同目录的另一种拼法"不许当
        # 另一个 ID 用——它会绕过官方闭集，或让两个 owner 共用一份数据目录。
        ("Official.Screen-Understanding", False),
        ("official.Screen-understanding", False),
        ("official.screen-understanding.", False),
        ("official.screen-understanding-", False),
        # Windows 设备名：feature-data\nul 指向 NUL 设备，不是目录。
        ("nul", False),
        ("con.package", False),
        ("COM1.tool", False),
        ("lpt9", False),
    ],
)
def test_feature_id_validation(value, expected):
    assert of.is_valid_feature_id(value) is expected


def test_a_case_or_trailing_dot_variant_cannot_shadow_the_official_registry():
    """官方闭集按**规范形**比较：变体先被 ID 校验拒掉，轮不到"查表查不到就放行"。"""
    for variant in ("Official.Screen-Understanding", "official.screen-understanding.", "OFFICIAL.AI-CHAT"):
        assert of.is_valid_feature_id(variant) is False
        with pytest.raises(ValueError, match="unsupported official feature"):
            of.official_feature(variant)
        with pytest.raises(ValueError, match="invalid feature"):
            of.FeatureRegistration(variant, "a/v1", "host-only", frozenset())


@pytest.mark.parametrize(
    "value, expected",
    [
        ("screen-understanding/v1", True),
        ("ai-chat/v1", True),
        ("bare", True),
        ("host/sub/deeper", False),
        ("", False),
        (None, False),
        ("host/" + "x" * 129, False),
    ],
)
def test_factory_id_validation(value, expected):
    assert of.is_valid_factory_id(value) is expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "bad id", "factory": "a/v1", "execution_kind": "host-only", "capabilities": frozenset()},
        {"id": "good.id", "factory": "bad factory", "execution_kind": "host-only", "capabilities": frozenset()},
        {"id": "good.id", "factory": "a/v1", "execution_kind": "in-process", "capabilities": frozenset()},
        {"id": "good.id", "factory": "a/v1", "execution_kind": "host-only", "capabilities": frozenset({"Bad Cap"})},
    ],
)
def test_a_malformed_registration_is_refused(kwargs):
    with pytest.raises(ValueError, match="invalid feature"):
        of.FeatureRegistration(**kwargs)


def test_the_registration_freezes_its_capability_set():
    registration = of.FeatureRegistration("good.id", "a/v1", "host-only", ["network.http"])
    assert registration.capabilities == frozenset({"network.http"})
    assert of.OfficialFeature is of.FeatureRegistration


def test_the_feature_host_runtime_entry_point_is_not_present_here():
    """S1c deliberately does not port the feature-host runtime entry point.

    Pinned so a later slice re-adding it has to do so together with the runtime;
    the alternative (a function that raises ``ModuleNotFoundError``) is exactly the
    dangling reference this port avoids.
    """
    assert not hasattr(of, "default_feature_host")
