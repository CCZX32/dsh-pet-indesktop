# -*- coding: utf-8 -*-
"""账户用量包·宿主核：验签装载、端口绑定、查询/缓存/定时器/设置草稿。

全部走真链：真打包 → 真验签 → ``FeaturePackageLoader`` 从验签字节导入 →
``bind_account_context`` 真端口绑定；网络用假 transport，凭据是内存后端。
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.credentials import CredentialVaultPort
from pet.feature_host_bindings import bind_account_context, register_feature_presentation
from pet.plugins.feature_host import FeatureHost
from tests.account_usage_fakes import OWNER, MemoryVault, build_package, import_pkg, load_host

app = QApplication.instance() or QApplication([])

PAYLOAD = {
    "is_available": True,
    "balance_infos": [
        {"currency": "CNY", "total_balance": "110.00", "granted_balance": "10.00", "topped_up_balance": "100.00"}
    ],
}


class _Presentation:
    def __init__(self):
        self.bubbles = []

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append((text, duration_ms))

    def hold_bubble(self, seconds):
        pass

    def notify(self, title, message, on_click=None):
        pass


def _pump(predicate, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


@pytest.fixture
def built(tmp_path):
    return build_package(tmp_path / "pkg" / "built")


@pytest.fixture
def bound(built, tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    _loader, _descriptor, handle = load_host(built)
    host = FeatureHost()
    definition = handle.factory()
    host.provide(definition)
    vault = CredentialVaultPort(OWNER, "test-instance", backend=MemoryVault(), operations={"balance.query"})
    context = bind_account_context(Config(base=tmp_path), vault=vault)
    return host, context, vault, handle


def _configure(context, vault, *, base_url="https://api.deepseek.com", minutes=0, enabled=True, key="sk-test"):
    ref = vault.save("account-usage", base_url, key) if key else ""
    context.preferences.stage(
        {"enabled": enabled, "base_url": base_url, "refresh_minutes": minutes, "verify_ssl": True, "credential_ref": ref}
    )
    assert context.preferences.flush()
    return ref


def test_definition_matches_the_package_contract(bound):
    _host, _context, _vault, handle = bound
    definition = handle.factory()
    assert definition.owner == OWNER
    assert len(definition.menus) == 1
    assert callable(definition.settings_factory)
    assert callable(definition.runtime_factory)
    assert definition.allow_in_process is True
    assert definition.worker_launch_factory is None


def test_manual_query_formats_the_bubble_and_caches_result(bound, monkeypatch):
    host, context, vault, handle = bound
    _configure(context, vault)
    module = import_pkg(handle, "host.runtime_mount")
    monkeypatch.setattr(module, "fetch_balance", lambda *args, **kwargs: PAYLOAD)
    provider = _Presentation()
    register_feature_presentation(lambda: provider)
    try:
        runtime = host.runtime(context)
        runtime.show()
        assert _pump(lambda: provider.bubbles), "查询结果没有回到气泡"
        assert provider.bubbles[0][0] == "余额 ¥110.00（充值 ¥100.00 + 赠送 ¥10.00）"
        cache = context.user_data.root / "balance_cache.json"
        assert cache.is_file()
        # 30 秒内再次点击直接用缓存，不再发请求。
        calls = []
        monkeypatch.setattr(module, "fetch_balance", lambda *args, **kwargs: calls.append(1) or PAYLOAD)
        runtime.show()
        assert calls == []
    finally:
        register_feature_presentation(None)


def test_missing_key_degrades_with_an_actionable_bubble(bound, monkeypatch):
    host, context, _vault, handle = bound
    _configure(context, vault=None, key="")
    module = import_pkg(handle, "host.runtime_mount")
    monkeypatch.setattr(module, "fetch_balance", lambda *args, **kwargs: pytest.fail("没有 Key 不应发请求"))
    provider = _Presentation()
    register_feature_presentation(lambda: provider)
    try:
        runtime = host.runtime(context)
        runtime.show()
        assert provider.bubbles and "未配置 API Key" in provider.bubbles[0][0]
    finally:
        register_feature_presentation(None)


def test_auto_refresh_timer_starts_and_stops_with_the_runtime(bound):
    host, context, vault, _handle = bound
    _configure(context, vault, minutes=1)
    runtime = host.runtime(context)
    runtime.start()
    assert runtime._timer is not None and runtime._timer.isActive()
    runtime.stop()
    assert runtime._timer is None
    runtime.start()
    assert runtime._timer is not None
    runtime.close()
    assert runtime._timer is None
    assert context.scheduler._closed is True


def test_settings_panel_round_trip_keeps_the_key_out_of_preferences(bound):
    _host, context, vault, handle = bound
    settings_module = import_pkg(handle, "host.contribution_settings")
    panel = settings_module.AccountUsageSettings(context)
    try:
        assert panel.dirty() is False
        panel.base_url.setText("https://gateway.example.com/")
        panel.refresh.setValue(30)
        panel.key.setText("sk-new")
        assert panel.dirty() is True
        assert panel.draft()["key_pending"] is True
        assert panel.confirm_save() is True
        values = context.preferences.read()
        assert values["base_url"] == "https://gateway.example.com"
        assert values["refresh_minutes"] == 30
        assert "sk-new" not in str(values)
        assert values["credential_ref"]
        assert vault.acquire(values["credential_ref"], "account-usage", "https://gateway.example.com", "balance.query") == "sk-new"
        assert panel.dirty() is False

        panel.base_url.setText("https://other.example.com")
        assert panel.confirm_save() is True
        assert context.preferences.read()["credential_ref"] == ""
    finally:
        panel.dispose()


def test_settings_panel_rejects_a_non_http_endpoint(bound):
    _host, context, _vault, handle = bound
    panel = import_pkg(handle, "host.contribution_settings").AccountUsageSettings(context)
    try:
        panel.base_url.setText("api.deepseek.com")
        assert panel.confirm_save() is False
        assert "http" in panel.error.text()
    finally:
        panel.dispose()
