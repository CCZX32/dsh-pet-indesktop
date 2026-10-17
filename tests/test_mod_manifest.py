# -*- coding: utf-8 -*-
"""资源包 manifest 严格契约：导入/托管包按完整清单校验，手动素材走宽松路径。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pet.mod_manifest import (
    is_safe_package_id,
    load_resource_manifest,
    validate_resource_package,
    version_satisfies,
)


def _manifest(character_id: str = "demo", **overrides):
    data = {
        "id": character_id,
        "name": "Demo",
        "description": "demo package",
        "version": "1.0.0",
        "kind": "content",
        "api_version": "1",
        "core_requires": ">=4.2.5,<6.0.0",
        "platforms": ["windows", "macos", "linux"],
        "dependencies": [],
        "capabilities": ["character", "animation"],
        "entrypoint": None,
        "content": {"characters": [character_id]},
        "integrity": {"sha256": None, "signature": None},
    }
    data.update(overrides)
    return data


def _package(root: Path, *, manifest=None, character_id: str = "demo", video: bytes = b"video") -> Path:
    package = root / "package"
    (package / "videos").mkdir(parents=True)
    (package / "videos" / "idle.webm").write_bytes(video)
    (package / "manifest.json").write_text(
        json.dumps(_manifest(character_id) if manifest is None else manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return package


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_a_complete_package_passes_and_reports_its_digest(tmp_path):
    package = _package(tmp_path / "source")
    manifest, issues, digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert issues == []
    assert manifest is not None and manifest.package_id == "demo"
    assert manifest.characters == ("demo",)
    assert digest and len(digest) == 64


def test_a_missing_manifest_is_refused(tmp_path):
    package = _package(tmp_path / "source")
    (package / "manifest.json").unlink()

    manifest, issues, digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is None and digest is None
    assert "manifest_missing" in _codes(issues)


def test_invalid_json_is_refused(tmp_path):
    package = _package(tmp_path / "source")
    (package / "manifest.json").write_text("{", encoding="utf-8")

    manifest, issues, _digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is None
    assert "manifest_invalid" in _codes(issues)


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"id": "bad/id"}, "id_invalid"),
        ({"version": "1.0"}, "version_invalid"),
        ({"kind": "feature"}, "kind_invalid"),
        ({"api_version": "2"}, "api_version_invalid"),
        ({"core_requires": ">=4.0.0,<nope"}, "core_requires_invalid"),
        ({"platforms": ["windows", "plan9"]}, "platform_invalid"),
        ({"entrypoint": "run.py"}, "entrypoint_forbidden"),
        ({"content": {"characters": []}}, "characters_invalid"),
        ({"content": {"characters": ["bad/id"]}}, "character_id_invalid"),
        ({"integrity": {"sha256": "not-a-hash"}}, "integrity_sha256_invalid"),
        ({"name": ""}, "name_invalid"),
    ],
)
def test_contract_violations_are_reported_by_code(tmp_path, overrides, code):
    package = _package(tmp_path / "source", manifest=_manifest(**overrides))
    manifest, issues, _digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is None
    assert code in _codes(issues)


def test_an_unsatisfied_core_requirement_is_refused(tmp_path):
    package = _package(tmp_path / "source", manifest=_manifest(core_requires=">=9.0.0"))
    manifest, issues, _digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is None
    assert "core_requires_unsatisfied" in _codes(issues)


def test_an_unsupported_platform_is_refused(tmp_path):
    package = _package(tmp_path / "source", manifest=_manifest(platforms=["macos"]))
    manifest, issues, _digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is None
    assert "platform_unsupported" in _codes(issues)


def test_executables_and_derived_cache_inside_the_root_are_refused(tmp_path):
    executable = _package(tmp_path / "executable")
    (executable / "host").mkdir()
    (executable / "host" / "factory.py").write_text("x = 1", encoding="utf-8")

    _manifest_obj, issues, _digest = validate_resource_package(executable, core_version="4.3.2", platform_name="windows")
    assert "executable_forbidden" in _codes(issues)

    cache = _package(tmp_path / "cache")
    (cache / "frameseq").mkdir()
    (cache / "frameseq" / "idle.json").write_text("{}", encoding="utf-8")

    _manifest_obj, issues, _digest = validate_resource_package(cache, core_version="4.3.2", platform_name="windows")
    assert "derived_cache_inside" in _codes(issues)


def test_missing_or_empty_videos_are_refused(tmp_path):
    missing = _package(tmp_path / "missing")
    (missing / "videos" / "idle.webm").unlink()

    _manifest_obj, issues, _digest = validate_resource_package(missing, core_version="4.3.2", platform_name="windows")
    assert "videos_missing" in _codes(issues)

    empty = _package(tmp_path / "empty", video=b"")
    _manifest_obj, issues, _digest = validate_resource_package(empty, core_version="4.3.2", platform_name="windows")
    assert "video_empty" in _codes(issues)


def test_a_declared_hash_must_match_the_content(tmp_path):
    package = _package(tmp_path / "source")
    _manifest_obj, _issues, digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")
    assert digest

    matching = _package(tmp_path / "matching", manifest=_manifest(integrity={"sha256": digest, "signature": None}))
    manifest, issues, _digest = validate_resource_package(matching, core_version="4.3.2", platform_name="windows")
    assert manifest is not None and issues == []

    mismatching = _package(tmp_path / "mismatching", manifest=_manifest(integrity={"sha256": "0" * 64}))
    manifest, issues, _digest = validate_resource_package(mismatching, core_version="4.3.2", platform_name="windows")
    assert manifest is None
    assert "content_hash_mismatch" in _codes(issues)


def test_an_expected_hash_from_the_update_request_is_enforced(tmp_path):
    package = _package(tmp_path / "source")
    _manifest_obj, issues, digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")
    assert issues == [] and digest

    _manifest_obj, issues, _digest = validate_resource_package(
        package, core_version="4.3.2", platform_name="windows", declared_hash=digest
    )
    assert issues == []

    _manifest_obj, issues, _digest = validate_resource_package(
        package, core_version="4.3.2", platform_name="windows", declared_hash="f" * 64
    )
    assert "content_hash_mismatch" in _codes(issues)


def test_a_single_character_may_live_in_a_nested_characters_root(tmp_path):
    package = _package(tmp_path / "source")
    nested = package / "characters" / "demo"
    nested.mkdir(parents=True)
    (package / "videos").rename(nested / "videos")

    manifest, issues, _digest = validate_resource_package(package, core_version="4.3.2", platform_name="windows")

    assert manifest is not None and issues == []


def test_load_manifest_returns_structured_issues_for_a_bad_object(tmp_path):
    package = _package(tmp_path / "source")
    (package / "manifest.json").write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    manifest, issues = load_resource_manifest(package)

    assert manifest is None
    assert {issue.code for issue in issues} == {"manifest_not_object"}


@pytest.mark.parametrize(
    "version, requirement, expected",
    [
        ("4.3.2", ">=4.2.5,<6.0.0", True),
        ("6.0.0", ">=4.2.5,<6.0.0", False),
        ("4.3.2", "", True),
        ("4.3.2", "*", True),
        ("4.3.2", "==4.3.2", True),
        ("4.3.2", ">4.3.2", False),
    ],
)
def test_version_satisfies(version, requirement, expected):
    assert version_satisfies(version, requirement) is expected


def test_version_satisfies_rejects_unknown_clauses():
    with pytest.raises(ValueError):
        version_satisfies("4.3.2", "~=4.3")


def test_safe_package_id_rejects_traversal_and_device_names():
    assert is_safe_package_id("demo")
    assert is_safe_package_id("深深")
    for unsafe in ("", ".", "..", "bad/id", "bad\\id", "trail.", "CON", "con.package", " lead"):
        assert not is_safe_package_id(unsafe)
