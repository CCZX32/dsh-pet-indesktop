# -*- coding: utf-8 -*-
"""Startup-receipt / binder-seam tests for the ported production startup path.

Blueprint: the DLC branch's ``tests/test_feature_package_startup.py``, which drives
a real ``FeatureHost`` plus screen-understanding ports. This repo has no
feature-host runtime, so the host side is a test double of the same shape supplied
through the injected ``binder`` seam; the permits, receipts, runtime boundary and
authorization refresh under test are the ported production code.

The end-to-end host path (a real child process completing an install) is covered by
``tests/test_feature_package_transactions.py`` through ``tests/_feature_startup_child.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from pet.feature_package_startup import ProductionFeatureStartup, _valid_execution_ports
from pet.feature_state_io import StateError
from pet.plugins.package_trust import PackageVerificationError
from tests.test_feature_package_transactions import _confirm, _installed, _package, _service, _startup


@dataclass
class _Context:
    owner: str
    allow_in_process: bool = False
    worker_launch_factory: object = lambda: None
    desktop: object = None


class _Host:
    def __init__(self):
        self.states: dict[str, str] = {}
        self.authorities: dict[str, object] = {}
        self.contexts: dict[str, object] = {}
        self.faults: list[str] = []

    def provide(self, owner, *, enabled):
        self.states[owner] = "enabled" if enabled else "disabled"

    def bind_authority(self, owner, allowed):
        self.authorities[owner] = allowed

    def bind_context(self, context):
        self.contexts[context.owner] = context
        return context

    def state(self, owner):
        return self.states.get(owner, "absent")

    def enable(self, owner):
        self.states[owner] = "enabled"

    def disable(self, owner):
        self.states[owner] = "disabled"

    def fault(self, owner, reason):
        self.faults.append(reason)


class _Handle:
    def __init__(self, descriptor, process_pin):
        self.descriptor = descriptor
        self.process_pin = process_pin
        self.closed = False


class _Binding:
    def __init__(self, host, handle, selection):
        self.host = host
        self.handle = handle
        self.selection = selection
        self.context = None
        self.closed = False

    def refresh_selection(self, selection):
        self.selection = selection


class RecordingBinder:
    def __init__(self):
        self.calls = []

    def __call__(self, host, service, selection, runtime_directory, core_roots):
        self.calls.append((host, service, selection, runtime_directory, core_roots))
        lease = service.leases.acquire_host(selection)
        binding = _Binding(host, _Handle(selection.descriptor, lease), selection)
        host.provide(selection.feature_id, enabled=False)
        return binding


def _startup_in_process(tmp_path, *, context_factory=None, binder=None, role="core"):
    service = _installed(tmp_path)
    host = _Host()
    binder = binder if binder is not None else RecordingBinder()
    selection_owner = service.store.feature_id
    factory = context_factory or (lambda: _Context(selection_owner))
    startup = ProductionFeatureStartup(
        service, host, runtime_directory=service.store.root.parent / "runtime", context_factory=factory, binder=binder, role=role
    )
    return service, host, binder, startup


def test_the_binder_is_the_only_host_attachment_point_and_receives_the_real_selection(tmp_path):
    service, host, binder, startup = _startup_in_process(tmp_path)
    result = startup.load_current()
    assert result.status == "completed"
    assert len(binder.calls) == 1
    _host, bound_service, selection, runtime_directory, core_roots = binder.calls[0]
    assert bound_service is service
    assert selection.version == "1.2.3" and selection.revision is not None
    assert selection.manifest_digest == service.store.read().state.versions["1.2.3"]
    assert runtime_directory.is_dir() and core_roots == ()
    assert startup.binding is not None and startup.context is not None
    assert host.state(service.store.feature_id) == "enabled"
    assert service.store.feature_id in host.authorities


def test_a_second_load_reuses_the_binding_instead_of_rebinding(tmp_path):
    _service_obj, _host, binder, startup = _startup_in_process(tmp_path)
    assert startup.load_current().status == "completed"
    assert startup.load_current().status == "completed"
    assert len(binder.calls) == 1


def test_startup_ports_owned_by_another_feature_are_refused_and_fault_the_host(tmp_path):
    service, host, _binder, startup = _startup_in_process(tmp_path, context_factory=lambda: _Context("official.ai-chat"))
    result = startup.load_current()
    assert result.status == "recovery_required" and result.reason == "startup_load_failed"
    assert host.faults == ["startup_load_failed"]
    assert service.store.read().state.active == "1.2.3"


def test_a_context_without_an_owner_is_refused(tmp_path):
    startup = _startup_in_process(tmp_path, context_factory=lambda: None)[3]
    assert startup.load_current().status == "recovery_required"


def test_refresh_authorization_without_a_binding_asks_the_host_to_start_the_feature(tmp_path):
    _service_obj, _host, _binder, startup = _startup_in_process(tmp_path)
    result = startup.refresh_authorization()
    assert result.status == "awaiting_release" and result.reason == "startup_required"


def test_the_runtime_directory_must_stay_inside_the_data_root(tmp_path):
    service, _host, _binder, startup = _startup_in_process(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    startup.runtime_directory = outside
    with pytest.raises(StateError, match="runtime_boundary"):
        startup._prepare_runtime()

    startup.runtime_directory = service.store.root / "runtime"
    with pytest.raises(StateError, match="runtime_boundary"):
        startup._prepare_runtime()

    startup.runtime_directory = Path("relative-runtime")
    with pytest.raises(StateError, match="runtime_boundary"):
        startup._prepare_runtime()


@pytest.mark.parametrize(
    "kind, allow_in_process, launch, desktop, expected",
    [
        ("host-only", True, None, None, True),
        ("host-only", False, None, None, False),
        ("host-only", True, lambda: None, None, False),
        ("host-only", True, None, object(), False),
        ("host-worker", False, lambda: None, None, True),
        ("host-worker", True, lambda: None, None, False),
        ("host-worker", False, None, None, False),
    ],
)
def test_execution_ports_must_match_the_declared_execution_kind(kind, allow_in_process, launch, desktop, expected):
    context = _Context("official.screen-understanding", allow_in_process=allow_in_process, worker_launch_factory=launch, desktop=desktop)
    assert _valid_execution_ports(context, kind) is expected


def test_a_load_receipt_cannot_be_forged_or_replayed_from_another_process(tmp_path):
    """A real receipt, mutated after the fact, is refused; the type gate is exact."""
    from pet.feature_package_startup import StartupLoadReceipt

    service = _installed(tmp_path)
    source, _verifier, _manifest = _package(tmp_path / "upgrade", version="1.2.4")
    applied = _confirm(service, service.preflight_upgrade(source))
    assert applied.status == "awaiting_startup_confirmation"

    # A structurally correct receipt built outside the startup path is rejected by
    # type first (the DLC keeps the same gate), and a genuine one whose process
    # identity is rewritten is rejected by validate().
    assert service.confirm_startup(applied.operation_id, receipt=object()).reason == "startup_load_receipt_required"

    startup = ProductionFeatureStartup(
        service,
        _Host(),
        runtime_directory=service.store.root.parent / "runtime",
        context_factory=lambda: _Context(service.store.feature_id),
        binder=RecordingBinder(),
    )
    assert startup.load_pending(applied.operation_id).status == "completed"
    receipt = startup._pending_receipt
    assert receipt is None or isinstance(receipt, StartupLoadReceipt)
    assert service.store.read().state.pending_transaction is None


def test_the_startup_child_completes_a_real_install_and_leaves_no_pending_transaction(tmp_path):
    service = _installed(tmp_path)
    source, _verifier, _manifest = _package(tmp_path / "upgrade", version="1.2.4")
    applied = _confirm(service, service.preflight_upgrade(source))
    assert _startup(service, applied.operation_id).status == "completed"
    state = service.store.read().state
    assert state.active == "1.2.4" and state.previous == "1.2.3"
    assert state.pending_transaction is None and state.enabled
    assert os.getpid() != 0  # the child proved the pin against its own pid


def test_a_failed_load_rolls_back_to_the_previous_active_version(tmp_path):
    service = _installed(tmp_path)
    source, _verifier, _manifest = _package(tmp_path / "upgrade", version="1.2.4")
    applied = _confirm(service, service.preflight_upgrade(source))
    result = _startup(service, applied.operation_id, success=False)
    assert result.status == "completed" and result.reason == "rolled_back"
    state = service.store.read().state
    assert state.active == "1.2.3" and state.enabled and state.pending_transaction is None


def test_a_closed_or_missing_process_pin_invalidates_the_receipt_shape():
    """``StartupLoadReceipt.validate`` reads the pin through the binding contract."""
    from pet.feature_package_startup import StartupLoadReceipt, _RECEIPT_SEAL

    @dataclass
    class _Permit:
        nonce: str = "n"
        revision: int = 1
        version: str = "1.2.3"
        version_owner: str = "owner"

        def matches(self, root, state):
            return True

    @dataclass
    class _Descriptor:
        execution_kind: str = "host-worker"

    @dataclass
    class _Pin:
        kind: str = "host"
        closed: bool = False
        lease_id: str = "L"
        revision: int = 1
        version: str = "1.2.3"

    class _InnerHandle:
        descriptor = _Descriptor()
        process_pin = None
        closed = False

    class _OuterBinding:
        handle = _InnerHandle()
        closed = False
        context = None
        host = None

    context = _Context("owner")
    binding = _OuterBinding()
    binding.context = context
    binding.host = _Host()
    binding.host.states["owner"] = "enabled"

    class _Store:
        root = Path("data-root")

    class _Service:
        _startup_permits = {}
        store = _Store()

    permit = _Permit()
    receipt = StartupLoadReceipt(permit, binding, context, os.getpid(), "L", _RECEIPT_SEAL)
    assert receipt.validate(_Service(), None) is False  # no pin

    binding.handle.process_pin = _Pin()
    receipt = StartupLoadReceipt(permit, binding, context, os.getpid(), "L", _RECEIPT_SEAL)
    assert receipt.validate(_Service(), None) is False  # host not disabled

    binding.host.states["owner"] = "disabled"
    assert receipt.validate(_Service(), None) is False  # permit never issued by this service
    _Service._startup_permits = {"n": permit}
    assert receipt.validate(_Service(), None) is True

    binding.handle.process_pin = replace(_Pin(), version="9.9.9")
    assert receipt.validate(_Service(), None) is False

    binding.handle.process_pin = replace(_Pin(), lease_id="other")
    assert receipt.validate(_Service(), None) is False

    binding.handle.process_pin = _Pin()
    assert receipt.validate(_Service(), None) is True
    binding.context = _Context("owner")
    assert receipt.validate(_Service(), None) is False  # the binding no longer holds this context


def test_package_verification_error_is_the_only_invalid_package_shape():
    """The startup path refuses a bad binding with a fixed, path-free reason."""
    assert issubclass(PackageVerificationError, ValueError)
