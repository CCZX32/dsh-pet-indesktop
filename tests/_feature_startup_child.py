# -*- coding: utf-8 -*-
"""Generated-fixture child process for the production startup path.

Blueprint: the DLC branch's ``tests/_feature_startup_child.py``. That child binds a
**real** ``FeatureHost`` plus screen-understanding ports (``pet.config``,
``pet.feature_host_bindings``, ``pet.feature_credentials``…) — the feature-host
runtime, which this repo does not have and S1c does not port. Everything the
receipt proves stays real here:

* the package is genuinely signed and verified against a real
  :class:`~pet.plugins.package_trust.FeaturePackageVerifier`;
* the host lease and the process pin are real ``CrossProcessLease`` objects from
  the ported :class:`~pet.feature_version_lease.FeatureVersionLeaseCoordinator`;
* the state machine, journal and commit CAS are the ported production code.

Only the "attach a verified package to the feature host" step is a double,
supplied through ``ProductionFeatureStartup``'s host-injected ``binder`` seam.
No private key, personal profile, desktop capture, Worker or network is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pet.feature_package_startup import ProductionFeatureStartup
from pet.feature_package_transactions import FeaturePackageTransactionService, OperationResult
from pet.plugins.package_trust import FeaturePackageVerifier, VerificationLimits


class FixtureContext:
    """Shape of ``FeatureHostContext``: identity + execution ports."""

    def __init__(self, owner: str, *, desktop: object | None = None):
        self.owner = owner
        self.allow_in_process = False
        self.worker_launch_factory = lambda: None
        self.desktop = desktop


class FixtureHost:
    """Minimal host：state/authority/enable/disable，与 DLC 的 FeatureHost 同语义。"""

    def __init__(self):
        self.states: dict[str, str] = {}
        self.authorities: dict[str, object] = {}
        self.contexts: dict[str, object] = {}
        self.faults: dict[str, str] = {}

    def provide(self, owner: str, *, enabled: bool) -> None:
        self.states[owner] = "enabled" if enabled else "disabled"

    def bind_authority(self, owner: str, allowed) -> None:
        self.authorities[owner] = allowed

    def bind_context(self, context):
        self.contexts[context.owner] = context
        return context

    def state(self, owner: str) -> str:
        return self.states.get(owner, "absent")

    def enabled(self, owner: str) -> bool:
        return self.state(owner) == "enabled"

    def enable(self, owner: str) -> None:
        self.states[owner] = "enabled"

    def disable(self, owner: str) -> None:
        self.states[owner] = "disabled"

    def fault(self, owner: str, reason: str) -> None:
        self.states[owner] = "fault"
        self.faults[owner] = reason


class FixtureHandle:
    """Shape of ``HostHandle``: descriptor + process pin + closed flag."""

    def __init__(self, descriptor, process_pin):
        self.descriptor = descriptor
        self.process_pin = process_pin
        self.closed = False


class FixtureBinding:
    """Shape of ``FeaturePackageBinding``."""

    def __init__(self, host: FixtureHost, handle: FixtureHandle, selection):
        self.host = host
        self.handle = handle
        self.selection = selection
        self.context = None
        self.closed = False

    def refresh_selection(self, selection) -> None:
        descriptor = self.handle.descriptor
        if selection.version != descriptor.version or selection.manifest_digest != self.selection.manifest_digest:
            raise ValueError("version replacement requires restart")
        self.selection = selection


def fixture_binder(host, service, selection, runtime_directory, core_roots):
    """``bind_verified_feature`` 的等价物，绑的是真租约 + 真描述符。"""
    lease = service.leases.acquire_host(selection)
    binding = FixtureBinding(host, FixtureHandle(selection.descriptor, lease), selection)
    host.provide(selection.feature_id, enabled=False)
    return binding


def main():
    document = json.loads(sys.stdin.buffer.read(65537))
    data_root = Path(document["data_root"])
    policy = document["policy"]
    policy["trust_anchors"] = {key: bytes.fromhex(value) for key, value in policy["trust_anchors"].items()}
    policy["limits"] = VerificationLimits(**policy["limits"])
    verifier = FeaturePackageVerifier(**policy)
    service = FeaturePackageTransactionService(data_root, verifier)
    host = FixtureHost()
    owner = verifier.feature_id
    runtime = data_root / "fixture-runtime"
    runtime.mkdir(exist_ok=True)

    def context():
        if not document["success"]:
            raise ValueError("generated post-import port-binding failure")
        return FixtureContext(owner)

    fired = False
    if document.get("crash_step"):
        original = service.store.commit

        def crash_after(change, *, expected_revision, operation_id):
            nonlocal fired
            value = original(change, expected_revision=expected_revision, operation_id=operation_id)
            if operation_id.endswith("." + document["crash_step"]) and not fired:
                fired = True
                raise OSError("generated commit acknowledgment failure")
            return value

        service.store.commit = crash_after
    try:
        startup = ProductionFeatureStartup(
            service, host, runtime_directory=runtime, context_factory=context, binder=fixture_binder, role=document.get("role", "core")
        )
        result = startup.load_pending(document["operation_id"])
    except Exception:
        result = OperationResult("recovery_required", reason="startup_bootstrap_failed")
    pin = startup.binding.handle.process_pin if startup.binding is not None else None
    print(
        json.dumps(
            {
                "status": result.status,
                "feature_id": result.feature_id,
                "operation_id": result.operation_id,
                "phase": result.phase,
                "revision": result.revision,
                "reason": result.reason,
                "host_state": host.state(owner),
                "bound": startup.binding is not None and startup.context is not None,
                "process_pin_live": pin is not None and not pin.closed,
                "crash_fired": fired,
            }
        )
    )


if __name__ == "__main__":
    main()
