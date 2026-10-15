# -*- coding: utf-8 -*-
"""CredentialVaultPort / CoreBalanceVault 契约测试（DLC 4A 凭据端口移植）。

一律使用内存后端，从不触碰真实 keyring；错误消息是固定码，不许带后端异常
细节或凭据内容。参考实现：上游 DLC 分支 的
``pet/credentials.py``。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from pet import credentials
from pet.credentials import CoreBalanceVault, CredentialError, CredentialVaultPort
from pet.official_features import AI_FEATURE_ID, SCREEN_FEATURE_ID


class MemoryVault:
    """SecureBackend 形状的内存替身；fail=True 时读写抛带敏感细节的异常。"""

    priority = 1

    def __init__(self):
        self.items = {}
        self.fail = False

    def set_password(self, service, ref, value):
        if self.fail:
            raise RuntimeError("TEST-SECRET backend write failed")
        self.items[(service, ref)] = value

    def get_password(self, service, ref):
        if self.fail:
            raise RuntimeError("TEST-SECRET backend read failed")
        return self.items.get((service, ref))

    def delete_password(self, service, ref):
        self.items.pop((service, ref), None)


@pytest.fixture
def backend():
    return MemoryVault()


@pytest.fixture
def vault(backend):
    return CredentialVaultPort(SCREEN_FEATURE_ID, "instance-A", backend=backend)


def _code(excinfo) -> str:
    return str(excinfo.value)


# ---------------------------------------------------------------- scope / ref


def test_scope_is_stable_and_distinct_per_owner_and_instance(backend):
    a = CredentialVaultPort(SCREEN_FEATURE_ID, "instance-A", backend=backend)
    a2 = CredentialVaultPort(SCREEN_FEATURE_ID, "instance-A", backend=backend)
    b = CredentialVaultPort(SCREEN_FEATURE_ID, "instance-B", backend=backend)
    c = CredentialVaultPort(AI_FEATURE_ID, "instance-A", backend=backend)
    assert a.scope == a2.scope and len(a.scope) == 64
    assert len({a.scope, b.scope, c.scope}) == 3
    assert a.service.startswith("dsh-pet/features/") and a.service.endswith(a.scope)


def test_reserve_ref_shape_and_check(vault):
    ref = vault.reserve()
    assert ref.startswith(vault.scope + "/") and len(ref) == len(vault.scope) + 33
    vault._check_ref(ref)  # 自家 ref 不抛
    with pytest.raises(CredentialError, match="scope_denied"):
        vault._check_ref("0" * 64 + "/" + "f" * 32)
    with pytest.raises(CredentialError, match="scope_denied"):
        vault._check_ref(vault.scope + "/short")


@pytest.mark.parametrize("feature", ["Official.Screen", "bad..id", "nul", "foo.", "", 123])
def test_invalid_feature_id_rejected(backend, feature):
    with pytest.raises(CredentialError, match="scope_invalid"):
        CredentialVaultPort(feature, "instance-A", backend=backend)


# ---------------------------------------------------------------- save/acquire


def test_save_then_acquire_roundtrip(vault, backend):
    ref = vault.save("manual", "https://ep.invalid/v1/chat/completions", "SECRET-1")
    assert vault.acquire(ref, "manual", "https://ep.invalid/v1/chat/completions", "manual_look") == "SECRET-1"
    envelope = json.loads(backend.items[(vault.service, ref)])
    assert envelope == {"profile": "manual", "endpoint": "https://ep.invalid/v1/chat/completions", "secret": "SECRET-1"}


def test_save_with_reserved_ref_is_write_ahead_safe(vault):
    ref = vault.reserve()
    assert vault.save("manual", "ep", "SECRET-2", ref=ref) == ref
    assert vault.acquire(ref, "manual", "ep", "analyze_frame") == "SECRET-2"


def test_save_rejects_empty_secret_and_foreign_ref(vault):
    with pytest.raises(CredentialError, match="credential_missing"):
        vault.save("manual", "ep", "   ")
    with pytest.raises(CredentialError, match="scope_denied"):
        vault.save("manual", "ep", "SECRET", ref="0" * 64 + "/" + "f" * 32)


def test_acquire_mismatched_profile_or_endpoint_is_scope_denied(vault):
    ref = vault.save("manual", "ep", "SECRET-3")
    with pytest.raises(CredentialError, match="scope_denied"):
        vault.acquire(ref, "other-profile", "ep", "manual_look")
    with pytest.raises(CredentialError, match="scope_denied"):
        vault.acquire(ref, "manual", "https://other.endpoint", "manual_look")


def test_acquire_operation_gate(vault, backend):
    ref = vault.save("manual", "ep", "SECRET-4")
    with pytest.raises(CredentialError, match="operation_denied"):
        vault.acquire(ref, "manual", "ep", "chat.send")  # screen owner 没有 chat 操作
    ai = CredentialVaultPort(AI_FEATURE_ID, "instance-A", backend=backend)
    ai_ref = ai.save("provider/x", "https://chat.invalid", "AI-SECRET")
    assert ai.acquire(ai_ref, "provider/x", "https://chat.invalid", "chat.send") == "AI-SECRET"
    assert ai.acquire(ai_ref, "provider/x", "https://chat.invalid", "files.interpret") == "AI-SECRET"
    with pytest.raises(CredentialError, match="operation_denied"):
        ai.acquire(ai_ref, "provider/x", "https://chat.invalid", "manual_look")


def test_acquire_missing_and_empty(vault):
    with pytest.raises(CredentialError, match="credential_missing"):
        vault.acquire("", "manual", "ep", "manual_look")
    with pytest.raises(CredentialError, match="credential_missing"):
        vault.acquire(vault.reserve(), "manual", "ep", "manual_look")


def test_cross_vault_ref_is_denied(vault, backend):
    other = CredentialVaultPort(SCREEN_FEATURE_ID, "instance-B", backend=backend)
    ref = other.save("manual", "ep", "OTHER-SECRET")
    with pytest.raises(CredentialError, match="scope_denied"):
        vault.acquire(ref, "manual", "ep", "manual_look")


# ---------------------------------------------------------------- 后端失败不泄密


def test_write_failure_cleans_up_and_reports_fixed_code(vault, backend):
    backend.fail = True
    ref = vault.reserve()
    with pytest.raises(CredentialError, match="credential_write_failed"):
        vault.save("manual", "ep", "SECRET-5", ref=ref)
    assert (vault.service, ref) not in backend.items  # 写失败的残留被清掉


def test_read_failure_reports_fixed_code_without_backend_detail(vault, backend):
    ref = vault.save("manual", "ep", "SECRET-6")
    backend.fail = True
    with pytest.raises(CredentialError) as excinfo:
        vault.acquire(ref, "manual", "ep", "manual_look")
    assert _code(excinfo) == "credential_read_failed"
    assert "TEST-SECRET" not in repr(excinfo.value)


def test_corrupt_envelope_is_read_failed(vault, backend):
    ref = vault.reserve()
    backend.items[(vault.service, ref)] = "not-json"
    with pytest.raises(CredentialError, match="credential_read_failed"):
        vault.acquire(ref, "manual", "ep", "manual_look")
    backend.items[(vault.service, ref)] = json.dumps({"profile": "manual", "endpoint": "ep", "secret": ""})
    with pytest.raises(CredentialError, match="credential_read_failed"):
        vault.acquire(ref, "manual", "ep", "manual_look")


def test_status_maps_to_fixed_codes(vault, backend):
    ref = vault.save("manual", "ep", "SECRET-7")
    assert vault.status(ref, "manual", "ep", "manual_look") == "available"
    assert vault.status(vault.reserve(), "manual", "ep", "manual_look") == "credential_missing"
    assert vault.status(ref, "manual", "ep", "chat.send") == "operation_denied"


def test_delete_requires_explicit_authorization(vault, backend):
    ref = vault.save("manual", "ep", "SECRET-8")
    with pytest.raises(CredentialError, match="delete_not_authorized"):
        vault.delete(ref)
    vault.delete(ref, authorized=True)
    assert (vault.service, ref) not in backend.items
    vault.delete(ref, authorized=True)  # 已不存在时静默幂等


def test_delete_backend_failure_is_fixed_code(vault, backend):
    ref = vault.save("manual", "ep", "SECRET-9")
    backend.fail = True
    with pytest.raises(CredentialError, match="credential_delete_failed"):
        vault.delete(ref, authorized=True)


# ---------------------------------------------------------------- CoreBalanceVault


def test_balance_vault_has_core_prefix_and_own_operation(backend):
    balance = CoreBalanceVault("root-1", "instance-A", backend=backend)
    assert balance.service.startswith("dsh-pet/core/balance/")
    ref = balance.save("balance", "https://balance.invalid", "BAL-SECRET")
    assert balance.acquire(ref, "balance", "https://balance.invalid", "balance.query") == "BAL-SECRET"
    with pytest.raises(CredentialError, match="operation_denied"):
        balance.acquire(ref, "balance", "https://balance.invalid", "chat.send")
    # AI 作用域的 ref 在 balance 作用域下判 scope_denied（互不相认）。
    ai = CredentialVaultPort(AI_FEATURE_ID, "instance-A", backend=backend)
    ai_ref = ai.save("provider/x", "https://chat.invalid", "AI-SECRET-2")
    with pytest.raises(CredentialError, match="scope_denied"):
        balance.acquire(ai_ref, "provider/x", "https://chat.invalid", "balance.query")


@pytest.mark.parametrize(
    "root_id,instance",
    [("", "instance-A"), (None, "instance-A"), ("x" * 129, "instance-A"), ("root-1", "y" * 129), ("root-1", 42)],
)
def test_balance_vault_scope_validation(backend, root_id, instance):
    with pytest.raises(CredentialError, match="scope_invalid"):
        CoreBalanceVault(root_id, instance, backend=backend)


# ---------------------------------------------------------------- secure_backend 门禁


def _fake_keyring_module(backend):
    module = types.ModuleType("keyring")
    module.get_keyring = lambda: backend
    return module


def test_secure_backend_accepts_os_store(monkeypatch):
    class WinBackend:
        priority = 1

        def set_password(self, *a): ...
        def get_password(self, *a): ...
        def delete_password(self, *a): ...

    WinBackend.__module__ = "keyring.backends.Windows"
    monkeypatch.setitem(sys.modules, "keyring", _fake_keyring_module(WinBackend()))
    assert isinstance(credentials.secure_backend(), WinBackend)


def test_secure_backend_unwraps_chainer(monkeypatch):
    class MacBackend:
        priority = 1

        def set_password(self, *a): ...
        def get_password(self, *a): ...
        def delete_password(self, *a): ...

    MacBackend.__module__ = "keyring.backends.macOS"

    class Chainer:
        priority = 1

        def __init__(self):
            self.backends = [MacBackend()]

    Chainer.__module__ = "keyring.backends.chainer"
    monkeypatch.setitem(sys.modules, "keyring", _fake_keyring_module(Chainer()))
    assert type(credentials.secure_backend()).__module__ == "keyring.backends.macOS"


@pytest.mark.parametrize("module_name", ["keyring.backends.fail", "keyrings.alt.file", "some.plaintext"])
def test_secure_backend_rejects_non_os_stores(monkeypatch, module_name):
    class PlaintextBackend:
        priority = 1

    PlaintextBackend.__module__ = module_name
    monkeypatch.setitem(sys.modules, "keyring", _fake_keyring_module(PlaintextBackend()))
    with pytest.raises(CredentialError, match="backend_unavailable"):
        credentials.secure_backend()


def test_secure_backend_without_keyring_is_fixed_code(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(CredentialError, match="backend_unavailable"):
        credentials.secure_backend()


def test_import_does_not_touch_keyring():
    code = """
import sys
import pet.credentials
assert 'keyring' not in sys.modules, 'keyring must stay lazy'
print('PURE_CREDENTIALS_IMPORT_OK')
"""
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr
    assert "PURE_CREDENTIALS_IMPORT_OK" in child.stdout
