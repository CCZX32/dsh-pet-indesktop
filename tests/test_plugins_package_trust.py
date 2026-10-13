# -*- coding: utf-8 -*-
"""Host-adapted tests for the ported package trust layer.

The DLC branch has no dedicated ``package_trust`` test file: its coverage lives in
``test_feature_packages.py`` / ``test_official_feature_contracts.py`` /
``test_feature_management_delivery_validation.py``, all of which drive the
feature-host runtime this repo does not have. This file is written against the
ported module alone, with the same fixture shape as the DLC blueprints (a real
Ed25519 key, a real on-disk package, a real ``FeaturePackageVerifier``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from pet.plugins.package_trust import (
    FACTORY_PATH,
    FeaturePackageVerifier,
    FileStamp,
    PackageVerificationError,
    SigningKeyPolicy,
    VerificationLimits,
    read_manifest_registration,
)

OWNER = "official.screen-understanding"
FACTORY = "screen-understanding/v1"


def _key():
    return Ed25519PrivateKey.generate()


def _raw(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _build(root: Path, *, key=None, key_id="release-2026", owner=OWNER, factory=FACTORY, extra_files=None, execution_kind="host-worker", version="1.2.3"):
    """A signed, complete package. ``key=None`` means an unsigned local package."""
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "host/__init__.py": b"",
        FACTORY_PATH: b"def create_host():\n    return None\n",
        "resources/defaults.json": b"{}",
    }
    if execution_kind == "host-worker":
        payloads["worker/screen-worker.exe"] = b"not-executed"
    payloads.update(extra_files or {})
    files = {}
    for name, data in payloads.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    manifest = {
        "format_version": 2,
        "id": owner,
        "key_id": key_id,
        "execution_kind": execution_kind,
        "version": version,
        "api_version": "1",
        "core_requires": ">=5.0.0,<6.0.0",
        "platforms": [sys.platform],
        "capabilities": ["screen.capture"],
        "factory": factory,
        "worker": {"path": "worker/screen-worker.exe", "args": ["--stdio"]} if execution_kind == "host-worker" else None,
        "files": files,
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (root / "manifest.json").write_bytes(raw)
    if key is not None:
        (root / "manifest.sig").write_bytes(key.sign(raw))
    return manifest, raw


def _verifier(key=None, *, key_id="release-2026", policy=None, **kwargs):
    kwargs.setdefault("core_version", "5.0.0")
    kwargs.setdefault("api_version", "1")
    kwargs.setdefault("platform", sys.platform)
    kwargs.setdefault("allowed_capabilities", {"screen.capture"})
    if key is not None:
        kwargs.setdefault("trust_anchors", {key_id: _raw(key)})
        if policy is not None:
            kwargs.setdefault("anchor_policy", {key_id: policy})
    return FeaturePackageVerifier(**kwargs)


def test_a_signed_package_verifies_with_the_declared_trust_anchor(tmp_path):
    key = _key()
    manifest, raw = _build(tmp_path / "pkg", key=key)
    descriptor = _verifier(key).verify(tmp_path / "pkg")
    assert descriptor.id == OWNER and descriptor.version == "1.2.3"
    assert descriptor.trust_status == "trusted_official" and descriptor.trust_anchor == "release-2026"
    assert descriptor.raw_manifest == raw
    assert set(descriptor.files) == set(manifest["files"])
    assert descriptor.execution_kind == "host-worker"
    assert _verifier(key).accepts_descriptor(descriptor)


def test_an_unknown_signing_key_is_refused_even_when_the_signature_is_valid(tmp_path):
    signer, other = _key(), _key()
    _build(tmp_path / "pkg", key=signer)
    with pytest.raises(PackageVerificationError, match="no explicitly trusted Core signer"):
        _verifier(other).verify(tmp_path / "pkg")


def test_a_tampered_payload_is_refused_before_any_signature_shortcut(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    (tmp_path / "pkg" / FACTORY_PATH).write_bytes(b"def create_host():\n    return object()\n")
    # The declared-size/identity guard fires first; either refusal is acceptable,
    # what matters is that a changed payload never reaches the signature verdict.
    with pytest.raises(PackageVerificationError, match="replaced file|digest/size mismatch"):
        _verifier(key).verify(tmp_path / "pkg")


def test_an_unsigned_package_is_refused_unless_the_core_opts_in(tmp_path):
    _build(tmp_path / "pkg", key=None)
    with pytest.raises(PackageVerificationError, match="missing official signature"):
        _verifier(_key()).verify(tmp_path / "pkg")
    local = _verifier(None, allow_local_packages=True)
    descriptor = local.verify(tmp_path / "pkg")
    assert descriptor.trust_status == "local_user" and descriptor.signature is None
    assert local.accepts_descriptor(descriptor)


def test_a_revoked_anchor_and_an_out_of_scope_anchor_both_refuse(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    shape = dict(feature_ids=frozenset({OWNER}), capabilities=frozenset({"screen.capture"}))
    with pytest.raises(PackageVerificationError):
        _verifier(key, policy=SigningKeyPolicy(revoked=True, **shape)).verify(tmp_path / "pkg")
    with pytest.raises(PackageVerificationError):
        _verifier(key, policy=SigningKeyPolicy(feature_ids=frozenset({"official.ai-chat"}), capabilities=frozenset({"screen.capture"}))).verify(tmp_path / "pkg")
    with pytest.raises(PackageVerificationError):
        _verifier(key, policy=SigningKeyPolicy(feature_ids=frozenset({OWNER}), capabilities=frozenset({"other.capability"}))).verify(tmp_path / "pkg")
    _verifier(key, policy=SigningKeyPolicy(**shape)).verify(tmp_path / "pkg")


def test_an_unlisted_file_and_a_missing_declared_file_are_both_refused(tmp_path):
    key = _key()
    _build(tmp_path / "unlisted", key=key)
    (tmp_path / "unlisted" / "surprise.py").write_bytes(b"untrusted")
    with pytest.raises(PackageVerificationError, match="unlisted file"):
        _verifier(key).verify(tmp_path / "unlisted")

    (tmp_path / "declared").mkdir()
    manifest, _ = _build(tmp_path / "declared", key=key)
    (tmp_path / "declared" / "resources/defaults.json").unlink()
    assert "resources/defaults.json" in manifest["files"]
    with pytest.raises(PackageVerificationError, match="missing declared payload"):
        _verifier(key).verify(tmp_path / "declared")


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/absolute.py", "host/./x.py", "host/../x.py", "host/aux.py", "host/name.", "host/na me.py", "host/nul.txt"],
)
def test_unsafe_declared_paths_are_refused(tmp_path, path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][path] = {"sha256": "0" * 64, "size": 0}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "pkg" / "manifest.json").write_bytes(raw)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(raw))
    with pytest.raises(PackageVerificationError, match="unsafe relative path|invalid/oversized"):
        _verifier(key).verify(tmp_path / "pkg")


def test_payload_cannot_smuggle_the_manifest_control_files(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["manifest.json"] = {"sha256": "0" * 64, "size": 0}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "pkg" / "manifest.json").write_bytes(raw)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(raw))
    with pytest.raises(PackageVerificationError, match="control files"):
        _verifier(key).verify(tmp_path / "pkg")


def test_case_colliding_declared_paths_are_refused(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["HOST/__init__.py"] = manifest["files"]["host/__init__.py"]
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "pkg" / "manifest.json").write_bytes(raw)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(raw))
    with pytest.raises(PackageVerificationError, match="collision"):
        _verifier(key).verify(tmp_path / "pkg")


@pytest.mark.parametrize(
    "field, value",
    [
        ("version", "1.2"),
        ("api_version", "2"),
        ("core_requires", ">=99.0.0,<100.0.0"),
        ("platforms", ["plan9"]),
        ("capabilities", ["credentials.read"]),
        ("factory", "other/v1"),
        ("execution_kind", "in-process"),
    ],
)
def test_schema_and_compatibility_violations_are_refused(tmp_path, field, value):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text(encoding="utf-8"))
    manifest[field] = value
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "pkg" / "manifest.json").write_bytes(raw)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(raw))
    with pytest.raises(PackageVerificationError):
        _verifier(key).verify(tmp_path / "pkg")


def test_a_host_only_package_must_not_declare_a_worker(tmp_path):
    key = _key()
    owner = "official.ai-chat"
    caps = {"network.http"}
    _build(tmp_path / "pkg", key=key, owner=owner, factory="ai-chat/v1", execution_kind="host-only")
    manifest = json.loads((tmp_path / "pkg" / "manifest.json").read_text(encoding="utf-8"))
    manifest["capabilities"] = ["network.http"]
    manifest["worker"] = {"path": "worker/screen-worker.exe", "args": []}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "pkg" / "manifest.json").write_bytes(raw)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(raw))
    verifier = _verifier(key, feature_id=owner, allowed_capabilities=caps)
    with pytest.raises(PackageVerificationError, match="host-only cannot declare a Worker"):
        verifier.verify(tmp_path / "pkg")


def test_declared_size_bounds_are_enforced_against_core_policy(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    verifier = _verifier(key, limits=VerificationLimits(max_manifest_bytes=16))
    with pytest.raises(PackageVerificationError):
        verifier.verify(tmp_path / "pkg")


def test_duplicate_json_fields_are_refused(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    raw = (tmp_path / "pkg" / "manifest.json").read_bytes()
    duplicated = raw.replace(b'{"api_version"', b'{"id":"official.ai-chat","api_version"', 1)
    (tmp_path / "pkg" / "manifest.json").write_bytes(duplicated)
    (tmp_path / "pkg" / "manifest.sig").write_bytes(key.sign(duplicated))
    with pytest.raises(PackageVerificationError, match="duplicate JSON field"):
        _verifier(key).verify(tmp_path / "pkg")


def test_reverify_detects_a_change_after_the_first_verification(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    verifier = _verifier(key)
    descriptor = verifier.verify(tmp_path / "pkg")
    verifier.check_snapshot_identity(descriptor)
    (tmp_path / "pkg" / "resources/defaults.json").write_bytes(b'{"changed":true}')
    with pytest.raises(PackageVerificationError):
        verifier.reverify(descriptor)
    with pytest.raises(PackageVerificationError):
        verifier.check_snapshot_identity(descriptor)


def test_a_symlinked_payload_is_refused(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    target = tmp_path / "pkg" / "resources" / "defaults.json"
    real = tmp_path / "outside.json"
    real.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.symlink(real, target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable to this account")
    with pytest.raises(PackageVerificationError, match="link/reparse point"):
        _verifier(key).verify(tmp_path / "pkg")


def test_read_manifest_registration_reads_only_the_bounded_registration(tmp_path):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    raw = (tmp_path / "pkg" / "manifest.json").read_bytes()
    registration, payload = read_manifest_registration(raw)
    assert registration.id == OWNER and registration.factory == FACTORY
    assert registration.execution_kind == "host-worker"
    assert payload["version"] == "1.2.3"
    with pytest.raises(PackageVerificationError, match="manifest size limit"):
        read_manifest_registration(raw, max_bytes=8)


def test_probe_policy_is_the_serializable_public_half_of_the_verifier(tmp_path):
    """Folded in from the DLC's ``pet/feature_probe_adapter`` (see the module docstring)."""
    import json

    from pet.feature_package_probe import ProbeOutcome, ProbeRequest, SubprocessFeatureSelfChecker, probe_policy

    key = _key()
    verifier = _verifier(key)
    policy = probe_policy(verifier)
    assert policy["feature_id"] == OWNER
    assert policy["trust_anchors"] == {"release-2026": _raw(key).hex()}
    assert policy["allowed_capabilities"] == ["screen.capture"]
    assert policy["allow_developer_unsigned"] is False
    assert set(policy) == {
        "feature_id",
        "anchor_policy",
        "core_version",
        "api_version",
        "platform",
        "allowed_capabilities",
        "trust_anchors",
        "allow_developer_unsigned",
        "allow_local_packages",
        "limits",
    }
    assert json.loads(json.dumps(policy)) == policy  # what a sandboxed child receives

    seen = {}

    class Sandbox:
        def run(self, request):
            seen["request"] = request
            return ProbeOutcome(True, True, True, True)

    _build(tmp_path / "pkg", key=key)
    descriptor = verifier.verify(tmp_path / "pkg")
    assert SubprocessFeatureSelfChecker(verifier, sandbox=Sandbox()).check(descriptor).status == "ready"
    request = seen["request"]
    assert isinstance(request, ProbeRequest) and request.policy == policy
    assert request.deny_network and request.deny_desktop and request.deny_user_data


# --- host-face regression: the Windows creation-timestamp gap -----------------
#
# A path-based ``lstat`` and a handle-based ``fstat`` legitimately disagree on the
# creation timestamp of a recently created file on this platform. Measured on the
# porting machine: 1001500 ns on every read of the same staged file, stable across
# repeats. The DLC read guard compared the full stamp and therefore rejected
# ordinary staging with "file changed before read". These two tests pin the fix:
# the guard must ignore the volatile field and still catch a real change.


def test_the_read_guard_ignores_a_divergent_creation_timestamp(tmp_path, monkeypatch):
    key = _key()
    _build(tmp_path / "pkg", key=key)

    class DivergentStat:
        """Delegate every field to a real ``stat_result`` except creation time."""

        def __init__(self, value):
            object.__setattr__(self, "_value", value)

        def __getattr__(self, name):
            if name == "st_ctime_ns":
                return object.__getattribute__(self, "_value").st_ctime_ns + 1_001_500
            return getattr(object.__getattribute__(self, "_value"), name)

    real_fstat = os.fstat
    monkeypatch.setattr(os, "fstat", lambda fd: DivergentStat(real_fstat(fd)))
    descriptor = _verifier(key).verify(tmp_path / "pkg")
    assert descriptor.version == "1.2.3"


def test_the_read_guard_still_catches_a_size_change(tmp_path, monkeypatch):
    key = _key()
    _build(tmp_path / "pkg", key=key)
    from pet.plugins import package_trust
    from pet.plugins.package_trust import PackageVerificationError

    original = package_trust._checked_stat

    def grown(path, **kwargs):
        stamp = original(path, **kwargs)
        if str(path).endswith("defaults.json"):
            return FileStamp(*[stamp.size + 1 if name == "size" else getattr(stamp, name) for name in stamp.__dataclass_fields__])
        return stamp

    monkeypatch.setattr(package_trust, "_checked_stat", grown)
    with pytest.raises(PackageVerificationError):
        _verifier(key).verify(tmp_path / "pkg")
