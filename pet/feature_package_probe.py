"""Verified probe contract. No same-user subprocess fallback is permitted.

A Core-owned OS sandbox runner is deliberately required. Cleaning environment
variables, a temporary HOME, or Python audit hooks is not a security boundary
for arbitrary native Worker code. This module fails closed until that runner is
provided; it never quietly downgrades an isolation requirement.

宿主面适配（两处，见 ``.scratch/dlc-fusion/S1c-HANDOFF.md``）：

* ``probe_policy`` 由 ``pet/feature_probe_adapter`` 折进本模块。它只把验证器
  的公开策略序列化成一本可传输的账（零 I/O、零 Qt），而 adapter 的其余部分
  （``WindowsFeatureProbeSandbox`` / ``TrustedProbeBundle``）是原生 Windows
  沙箱启动器，不在本片范围。折进来之后 :class:`SubprocessFeatureSelfChecker`
  自成一个完整单元，不再有一条指向未移植模块的惰性 import。
* 未移植 DLC 的 ``verified_host_probe``：它按契约"只在沙箱内调用"，而本仓库没有
  LPAC 原生沙箱流水线（``SubprocessFeatureSelfChecker.available`` 恒 False），
  所以这条探针路径在本拓扑根本跑不起来。宿主运行时（``plugins.feature_host``）
  已在 D2 落地；缺的是沙箱本身，不是它。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Protocol

from .plugins.package_trust import FeaturePackageVerifier, PackageVerificationError, VerifiedFeatureDescriptor

if TYPE_CHECKING:
    from .feature_package_transactions import RuntimePreparation


def probe_policy(verifier: FeaturePackageVerifier) -> dict[str, object]:
    """Serializable, public half of the verifier a sandboxed child must enforce."""
    return dict(
        feature_id=verifier.feature_id,
        anchor_policy={
            name: dict(
                feature_ids=sorted(policy.feature_ids), capabilities=sorted(policy.capabilities), revoked=policy.revoked, allow_legacy_v1=policy.allow_legacy_v1
            )
            for name, policy in verifier.anchor_policy.items()
        },
        core_version=verifier.core_version,
        api_version=verifier.api_version,
        platform=verifier.platform,
        allowed_capabilities=sorted(verifier.allowed_capabilities),
        trust_anchors={name: key.hex() for name, key in verifier.trust_anchors.items()},
        allow_developer_unsigned=False,
        allow_local_packages=verifier.allow_local_packages,
        limits=asdict(verifier.limits),
    )


@dataclass(frozen=True)
class ProbeRequest:
    package_root: Path
    policy: Mapping[str, object]
    timeout: float
    deny_user_data: bool = True
    deny_network: bool = True
    deny_desktop: bool = True


@dataclass(frozen=True)
class ProbeOutcome:
    host_valid: bool
    worker_hello: bool
    worker_graceful_exit: bool
    isolation_enforced: bool
    reason: str | None = None
    worker_status: str = "verified"


class ProbeSandbox(Protocol):
    """Trusted Core launcher; both host and Worker must share OS isolation."""

    def run(self, request: ProbeRequest) -> ProbeOutcome: ...


class SubprocessFeatureSelfChecker:
    def __init__(self, verifier: FeaturePackageVerifier, *, sandbox: ProbeSandbox | None = None, timeout: float = 30.0):
        self.verifier = verifier
        self.sandbox = sandbox
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return self.sandbox is not None

    def check(self, descriptor: VerifiedFeatureDescriptor) -> RuntimePreparation:
        from .feature_package_transactions import RuntimePreparation

        try:
            self.verifier.reverify(descriptor)
        except (PackageVerificationError, OSError):
            return RuntimePreparation("failed", "self_check_verification_failed")
        if self.sandbox is None:
            return RuntimePreparation("failed", "self_check_sandbox_unavailable")
        policy = probe_policy(self.verifier)
        try:
            result = self.sandbox.run(ProbeRequest(descriptor.root, policy, self.timeout))
        except (OSError, TimeoutError):
            return RuntimePreparation("failed", "self_check_sandbox_failed")
        if not result.isolation_enforced:
            return RuntimePreparation("failed", "self_check_isolation_not_enforced")
        worker_valid = (
            result.worker_status == "not_applicable" and not result.worker_hello and not result.worker_graceful_exit
            if descriptor.execution_kind == "host-only"
            else result.worker_status == "verified" and result.worker_hello and result.worker_graceful_exit
        )
        if not (result.host_valid and worker_valid):
            return RuntimePreparation("failed", result.reason or "self_check_failed")
        return RuntimePreparation()


def validate_worker_transcript(transcript: bytes, *, graceful_returncode: int, worker_id: str = "proactive-screen") -> bool:
    """Bounded minimum hello/shutdown protocol proof, with no task/config push.

    The sandbox launcher sends only shutdown after seeing hello, closes stdin,
    and owns the deadline/process-tree cleanup. A successful native exit alone
    is not a handshake. The launcher must not send screenshot/model requests.
    """
    from .workers.protocol import MAX_MESSAGE_BYTES, decode_message

    if len(transcript) > MAX_MESSAGE_BYTES * 4 or graceful_returncode != 0:
        return False
    hello = False
    try:
        for line in transcript.splitlines():
            if len(line) > MAX_MESSAGE_BYTES:
                return False
            message = decode_message(line)
            if message.worker_id != worker_id or message.type not in ("hello", "heartbeat"):
                return False
            if message.type == "hello":
                if hello:
                    return False
                hello = True
    except (ValueError, json.JSONDecodeError):
        return False
    return hello
