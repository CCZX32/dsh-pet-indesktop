# -*- coding: utf-8 -*-
"""资源硬门：严格清单、摘要幂等、激活后自检、任意版本激活与回滚。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pet.mod_management import ModError, ResourceMods
from tests.mod_package_fakes import write_package


def _resources(root: Path, **kwargs) -> ResourceMods:
    kwargs.setdefault("prepare_removal", lambda _entry: True)
    return ResourceMods(root / "data", **kwargs)


def test_install_uses_the_strict_manifest_contract(tmp_path):
    resources = _resources(tmp_path)
    package = write_package(tmp_path / "source")
    (package / "manifest.json").write_text(json.dumps({"id": "demo", "name": "Demo"}), encoding="utf-8")

    with pytest.raises(ModError) as excinfo:
        resources.install(package)

    assert "version" in str(excinfo.value)
    assert excinfo.value.issues
    assert not (resources.live_root / "demo").exists()


def test_install_refuses_an_executable_in_an_imported_package(tmp_path):
    resources = _resources(tmp_path)
    package = write_package(tmp_path / "source")
    (package / "host").mkdir()
    (package / "host" / "factory.py").write_text("x = 1", encoding="utf-8")

    with pytest.raises(ModError, match="可执行"):
        resources.install(package)

    assert not (resources.live_root / "demo").exists()


def test_reimporting_identical_content_is_idempotent(tmp_path):
    resources = _resources(tmp_path)
    first = resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"same"))

    second = resources.install(write_package(tmp_path / "two", version="1.0.0", video=b"same"))

    assert first.id == second.id
    assert not (resources.retained_root / "demo").exists()


def test_the_same_version_with_different_content_is_refused(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"old"))
    resources.set_enabled("demo", True)

    with pytest.raises(ModError, match="同版本"):
        resources.install(write_package(tmp_path / "two", version="1.0.0", video=b"new"))

    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"old"


def test_an_update_keeps_the_old_version_retained(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)
    resources.install(write_package(tmp_path / "two", version="2.0.0", video=b"v2"))

    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v2"
    assert (resources.retained_root / "demo" / "1.0.0" / "videos" / "idle.webm").read_bytes() == b"v1"


def test_a_failed_self_check_restores_the_previous_version(tmp_path, monkeypatch):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)

    def fail(*_args, **_kwargs):
        raise ModError("injected self-check failure")

    monkeypatch.setattr(resources, "_self_check", fail)
    with pytest.raises(ModError):
        resources.install(write_package(tmp_path / "two", version="2.0.0", video=b"v2"))
    monkeypatch.undo()

    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v1"
    assert not (resources.retained_root / "demo" / "2.0.0").exists()


def test_activate_switches_to_any_retained_version(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)
    resources.install(write_package(tmp_path / "two", version="2.0.0", video=b"v2"))
    resources.install(write_package(tmp_path / "three", version="3.0.0", video=b"v3"))

    outcome = resources.activate("demo", "1.0.0")

    assert outcome.success
    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v1"
    assert (resources.retained_root / "demo" / "3.0.0" / "videos" / "idle.webm").read_bytes() == b"v3"


def test_activate_refuses_an_unknown_version(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0"))

    outcome = resources.activate("demo", "9.9.9")

    assert not outcome.success
    assert "没有这个保留版本" in outcome.message


def test_activate_refuses_while_the_character_is_in_use(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)
    resources.install(write_package(tmp_path / "two", version="2.0.0", video=b"v2"))
    resources.prepare_removal = lambda _entry: False

    outcome = resources.activate("demo", "1.0.0")

    assert not outcome.success and outcome.pending
    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v2"


def test_rollback_still_picks_the_highest_retained_version(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)
    resources.install(write_package(tmp_path / "two", version="2.0.0", video=b"v2"))
    resources.install(write_package(tmp_path / "three", version="3.0.0", video=b"v3"))

    outcome = resources.rollback("demo")

    assert outcome.success
    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v2"


def _package_with_declared_hash(root: Path, *, version: str, video: bytes) -> Path:
    from pet.mod_hashing import content_sha256

    package = write_package(root, version=version, video=video)
    digest = content_sha256(package)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["integrity"]["sha256"] = digest
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


def test_a_landed_version_that_stops_matching_its_digest_is_caught_on_rollback(tmp_path):
    resources = _resources(tmp_path)
    resources.install(_package_with_declared_hash(tmp_path / "one", version="1.0.0", video=b"v1"))
    resources.set_enabled("demo", True)
    resources.install(_package_with_declared_hash(tmp_path / "two", version="2.0.0", video=b"v2"))
    retained = resources.retained_root / "demo" / "1.0.0"
    (retained / "videos" / "idle.webm").write_bytes(b"tampered")

    outcome = resources.rollback("demo")

    assert not outcome.success
    assert (resources.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v2"


def test_retained_versions_excludes_the_active_one(tmp_path):
    resources = _resources(tmp_path)
    resources.install(write_package(tmp_path / "one", version="1.0.0"))
    resources.install(write_package(tmp_path / "two", version="2.0.0"))

    assert resources.retained_versions("demo") == ["1.0.0"]


def test_unmanaged_character_roots_are_still_lenient(tmp_path):
    builtin = tmp_path / "builtin"
    (builtin / "shenshen" / "videos").mkdir(parents=True)
    (builtin / "shenshen" / "videos" / "idle.webm").write_bytes(b"video")
    resources = _resources(tmp_path, character_roots=[("builtin", builtin)])

    rows = {row.id: row for row in resources.entries()}

    assert rows["resource:builtin:shenshen"].version == "0.0.0"
