from __future__ import annotations

import json
from pathlib import Path

from petcore.mods.manifest import load_manifest, parse_version, version_satisfies


def write_pack(base: Path, payload: dict, files: dict[str, str] | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "mod.json").write_text(json.dumps(payload), encoding="utf-8")
    for name, content in (files or {}).items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


def content_payload(**overrides):
    payload = {
        "schema": 1,
        "id": "character.shenshen",
        "kind": "content",
        "name": "Shenshen",
        "version": "1.0.0",
        "api_version": "1",
        "author": "dsh",
        "character": {"id": "shenshen", "media_dir": "media"},
    }
    payload.update(overrides)
    return payload


def feature_payload(**overrides):
    payload = {
        "schema": 1,
        "id": "feature.clock",
        "kind": "feature",
        "name": "Clock",
        "version": "1.0.0",
        "api_version": "1",
        "execution": "host-only",
        "entrypoint": "host/factory.py:create_host",
        "capabilities": ["sound.play"],
    }
    payload.update(overrides)
    return payload


def test_happy_content_pack(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        content_payload(),
        {"media/idle.png": "png"},
    )
    manifest, diagnostics = load_manifest(pack)
    assert diagnostics == []
    assert manifest is not None
    assert manifest.id == "character.shenshen"
    assert manifest.kind == "content"
    assert manifest.name == "Shenshen"
    assert manifest.version == "1.0.0"
    assert manifest.author == "dsh"
    assert manifest.character == {"id": "shenshen", "media_dir": "media"}
    assert manifest.path == pack.resolve()
    assert manifest.entrypoint is None
    assert manifest.capabilities == ()


def test_bad_id_rejected(tmp_path):
    pack = write_pack(tmp_path / "pack", content_payload(id="Character.Shenshen"))
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("invalid id" in item for item in diagnostics)


def test_bad_version_rejected(tmp_path):
    pack = write_pack(tmp_path / "pack", content_payload(version="1.0"))
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("version must be X.Y.Z" in item for item in diagnostics)


def test_path_traversal_rejected(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        content_payload(character={"id": "shenshen", "media_dir": "../outside"}),
    )
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("escapes pack" in item for item in diagnostics)


def test_absolute_media_dir_rejected(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        content_payload(character={"id": "shenshen", "media_dir": "C:/outside"}),
    )
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("absolute path" in item for item in diagnostics)


def test_documented_character_keys_are_path_checked(tmp_path):
    media = write_pack(
        tmp_path / "media",
        content_payload(character={"media": "../outside"}),
    )
    manifest, diagnostics = load_manifest(media)
    assert manifest is None
    assert any("escapes pack" in item for item in diagnostics)

    strides = write_pack(
        tmp_path / "strides",
        content_payload(character={"media": "videos", "move_strides": "C:/strides.json"}),
    )
    manifest, diagnostics = load_manifest(strides)
    assert manifest is None
    assert any("absolute path" in item for item in diagnostics)

    clips = write_pack(
        tmp_path / "clips",
        content_payload(character={"media": "videos", "text_clips": "../clips.json"}),
    )
    manifest, diagnostics = load_manifest(clips)
    assert manifest is None
    assert any("escapes pack" in item for item in diagnostics)


def test_documented_character_block_is_accepted(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        content_payload(
            character={
                "media": "videos",
                "canvas": [640, 360],
                "feet_y": 330,
                "move_strides": "videos/move_strides.json",
                "text_clips": "videos/text_clips.json",
            }
        ),
        {"videos/idle/idle.webm": ""},
    )
    manifest, diagnostics = load_manifest(pack)
    assert diagnostics == []
    assert manifest is not None
    assert manifest.character["media"] == "videos"


def test_executable_file_in_content_pack_rejected(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        content_payload(),
        {"scripts/tool.py": "print('no')"},
    )
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("executable file in content pack" in item for item in diagnostics)


def test_content_pack_rejects_entrypoint(tmp_path):
    pack = write_pack(tmp_path / "pack", content_payload(entrypoint="host/factory.py:create"))
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("must not declare entrypoint" in item for item in diagnostics)


def test_feature_entrypoint_must_be_relative(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        feature_payload(entrypoint="C:/evil.py:create"),
        {"host/factory.py": ""},
    )
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("absolute path" in item for item in diagnostics)


def test_unknown_capability_rejected(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        feature_payload(capabilities=["sound.play", "kernel.root"]),
        {"host/factory.py": ""},
    )
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("unknown capability" in item for item in diagnostics)


def test_requires_field_is_known_and_parsed(tmp_path):
    pack = write_pack(
        tmp_path / "pack",
        feature_payload(requires=["character.shenshen", "character.shenshen"]),
        {"host/factory.py": ""},
    )
    manifest, diagnostics = load_manifest(pack)
    assert diagnostics == []
    assert manifest is not None
    assert manifest.requires == ("character.shenshen",)


def test_core_requires_boundaries(tmp_path):
    files = {"host/factory.py": ""}
    good = write_pack(
        tmp_path / "good",
        feature_payload(core_requires=">=0.1.0,<1.0.0"),
        files,
    )
    manifest, diagnostics = load_manifest(good)
    assert manifest is not None
    assert diagnostics == []

    too_new = write_pack(
        tmp_path / "too_new",
        feature_payload(core_requires=">0.1.0"),
        files,
    )
    manifest, diagnostics = load_manifest(too_new)
    assert manifest is None
    assert any("not satisfied" in item for item in diagnostics)

    exact = write_pack(
        tmp_path / "exact",
        feature_payload(core_requires="<=0.1.0"),
        files,
    )
    assert load_manifest(exact)[0] is not None

    malformed = write_pack(
        tmp_path / "malformed",
        feature_payload(core_requires="=>0.1.0"),
        files,
    )
    manifest, diagnostics = load_manifest(malformed)
    assert manifest is None
    assert any("malformed core_requires" in item for item in diagnostics)


def test_version_satisfies_helpers():
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("0.1") is None
    assert version_satisfies("", "0.1.0") is True
    assert version_satisfies(">=0.1.0, <1.0.0", "0.1.0") is True
    assert version_satisfies("==0.1.0", "0.1.0") is True
    assert version_satisfies("==0.1.0", "0.2.0") is False
    assert version_satisfies(">=0.2.0", "0.1.0") is False
    assert version_satisfies(">=x", "0.1.0") is False
    assert version_satisfies(">=0.1.0", "not-a-version") is False


def test_unknown_field_is_only_a_diagnostic(tmp_path):
    pack = write_pack(tmp_path / "pack", content_payload(mystery=True))
    manifest, diagnostics = load_manifest(pack)
    assert manifest is not None
    assert any("unknown field: mystery" in item for item in diagnostics)
    assert "unknown field: mystery" in manifest.diagnostics


def test_missing_manifest_file(tmp_path):
    pack = tmp_path / "empty"
    pack.mkdir()
    manifest, diagnostics = load_manifest(pack)
    assert manifest is None
    assert any("mod.json not found" in item for item in diagnostics)
