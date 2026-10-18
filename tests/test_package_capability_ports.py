# -*- coding: utf-8 -*-
"""host-only 官方包的三样通用能力：呈现面 / 定时器 / 凭据操作集。

这些是 5C 的第一片：账户用量等包不需要窗口句柄，只需要"把结果说给用户听、
按时间做周期动作、取自己那把 key"。测试用真文件 + 假呈现提供方/假 keyring，
不碰真桌面。
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.credentials import CredentialError, CredentialVaultPort
from pet.feature_host_bindings import (
    bind_account_context,
    register_feature_presentation,
)
from pet.feature_ports import FeatureHostContext
from pet.official_features import ACCOUNT_USAGE_FEATURE_ID

OWNER = ACCOUNT_USAGE_FEATURE_ID


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
    def __init__(self):
        self.bubbles = []
        self.holds = []
        self.notifications = []

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append((text, duration_ms))

    def hold_bubble(self, seconds):
        self.holds.append(seconds)

    def notify(self, title, message, on_click=None):
        self.notifications.append((title, message, on_click))


@pytest.fixture(autouse=True)
def _clear_presentation():
    register_feature_presentation(None)
    yield
    register_feature_presentation(None)


def _context(tmp_path, *, vault=None):
    return bind_account_context(Config(base=tmp_path), vault=vault)


def test_host_context_defaults_new_ports_to_none():
    context = FeatureHostContext(
        owner=OWNER,
        configuration=object(),
        documents={},
        state_documents={},
    )
    assert context.presentation is None
    assert context.scheduler is None


def test_bind_account_context_exposes_owner_scoped_ports(tmp_path):
    context = _context(tmp_path)
    assert context.owner == OWNER
    assert context.credentials is not None
    assert context.scheduler is not None
    # 呈现端口始终存在；没有提供方时它自己安全降级（绑定可早于 AppShell 注册）。
    assert context.presentation is not None
    assert context.user_data is not None
    assert context.user_data.root == Config(base=tmp_path).dir / "feature-data" / OWNER
    # 偏好字段是闭集：包只能 stage 自己那几项。
    context.preferences.stage({"base_url": "https://api.deepseek.com", "refresh_minutes": 15})
    assert context.preferences.read()["refresh_minutes"] == 15
    with pytest.raises(PermissionError):
        context.preferences.stage({"api_key": "secret"})


def test_presentation_forwards_to_registered_provider_and_degrades(tmp_path):
    provider = _FakePresentation()
    holder = {"provider": provider}
    register_feature_presentation(lambda: holder["provider"])
    context = _context(tmp_path)
    assert context.presentation is not None

    context.presentation.show_bubble("余额 10.00", duration_ms=6000)
    context.presentation.hold_bubble(2.5)
    context.presentation.notify("账户用量", "刷新完成")
    assert provider.bubbles == [("余额 10.00", 6000)]
    assert provider.holds == [2.5]
    assert provider.notifications == [("账户用量", "刷新完成", None)]

    # 生产工厂每次调用都读当前可见窗；窗口没了就安全降级，不抛。
    holder["provider"] = None
    context.presentation.show_bubble("迟到的结果")
    assert provider.bubbles == [("余额 10.00", 6000)]

    # 没有提供方时端口仍在，但调用是安全空操作。
    register_feature_presentation(None)
    unbound = _context(tmp_path)
    assert unbound.presentation is not None
    unbound.presentation.show_bubble("不会到")


def test_presentation_provider_errors_do_not_escape(tmp_path):
    def broken():
        raise RuntimeError("no window")

    register_feature_presentation(broken)
    context = _context(tmp_path)
    context.presentation.show_bubble("不会到")
    context.presentation.hold_bubble(1)
    context.presentation.notify("t", "m")


def test_explicit_credential_operations_allow_only_balance_query(tmp_path):
    backend = _FakeVaultBackend()
    vault = CredentialVaultPort(OWNER, "instance", backend=backend, operations={"balance.query"})
    ref = vault.save("account-usage", "https://api.deepseek.com", "sk-test")
    assert vault.acquire(ref, "account-usage", "https://api.deepseek.com", "balance.query") == "sk-test"
    with pytest.raises(CredentialError, match="operation_denied"):
        vault.acquire(ref, "account-usage", "https://api.deepseek.com", "chat.send")


def test_default_credential_operations_keep_screen_ceiling():
    backend = _FakeVaultBackend()
    vault = CredentialVaultPort("official.screen-understanding", "instance", backend=backend)
    ref = vault.save("screen", "desktop", "token")
    assert vault.acquire(ref, "screen", "desktop", "manual_look") == "token"
    with pytest.raises(CredentialError, match="operation_denied"):
        vault.acquire(ref, "screen", "desktop", "balance.query")


def test_scheduler_runs_single_and_repeating_then_closes(tmp_path):
    _app = QApplication.instance() or QApplication([])
    context = _context(tmp_path)
    scheduler = context.scheduler
    assert scheduler is not None

    once = []
    handle = scheduler.call_later(0, lambda: once.append(1))
    assert handle is not None
    QTest.qWait(30)
    assert once == [1]

    ticks = []
    repeating = scheduler.call_repeating(10, lambda: ticks.append(1))
    QTest.qWait(60)
    assert len(ticks) >= 2
    scheduler.close()
    settled = len(ticks)
    QTest.qWait(40)
    assert len(ticks) == settled

    # close 之后再排的定时器不会启动。
    assert scheduler.call_later(0, lambda: once.append(2)) is None
    QTest.qWait(20)
    assert once == [1]


def test_scheduler_callback_failure_stops_repeating(tmp_path):
    _app = QApplication.instance() or QApplication([])
    scheduler = _context(tmp_path).scheduler
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("boom")

    scheduler.call_repeating(5, broken)
    QTest.qWait(60)
    assert calls == [1]
    scheduler.close()
