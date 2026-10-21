from __future__ import annotations

import json
from pathlib import Path

from petcore.mods import state
from petcore.mods.loader import load_mods


def write_pack(base: Path, payload: dict, files: dict[str, str] | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "mod.json").write_text(json.dumps(payload), encoding="utf-8")
    for name, content in (files or {}).items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


def content_payload(mod_id: str = "character.demo", **overrides) -> dict:
    payload = {
        "schema": 1,
        "id": mod_id,
        "kind": "content",
        "name": mod_id,
        "version": "1.0.0",
        "api_version": "1",
    }
    payload.update(overrides)
    return payload


def feature_payload(mod_id: str = "feature.clock", **overrides) -> dict:
    payload = {
        "schema": 1,
        "id": mod_id,
        "kind": "feature",
        "name": mod_id,
        "version": "1.0.0",
        "api_version": "1",
        "execution": "host-only",
        "entrypoint": "host/factory.py:create_host",
    }
    payload.update(overrides)
    return payload


def test_discovery_is_sorted_by_id_and_path(tmp_path):
    root = tmp_path / "root"
    write_pack(root / "mods" / "a_pack", content_payload("z.z"))
    write_pack(root / "mods" / "b_pack", content_payload("a.a"))
    extra = tmp_path / "extra"
    write_pack(extra / "m_pack", content_payload("m.m"))

    result = load_mods(root, (extra,))

    assert [mod.manifest.id for mod in result.mods] == ["a.a", "m.m", "z.z"]
    assert result.diagnostics == ()


def test_duplicate_id_last_wins(tmp_path):
    root = tmp_path / "root"
    (root / "mods").mkdir(parents=True)
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_pack(first / "demo", content_payload(version="1.0.0"))
    write_pack(second / "demo", content_payload(version="2.0.0"))

    result = load_mods(root, (first, second))

    assert len(result.mods) == 1
    assert result.mods[0].manifest.version == "2.0.0"
    assert any("overridden" in item for item in result.diagnostics)


def test_disabled_mod_is_listed_but_contributes_nothing(tmp_path):
    root = tmp_path / "root"
    write_pack(root / "mods" / "demo", content_payload(character={"id": "demo"}))
    state.set_enabled(root, "character.demo", False)

    result = load_mods(root)

    assert [mod.manifest.id for mod in result.mods] == ["character.demo"]
    assert result.mods[0].enabled is False
    assert result.contents == ()


def test_broken_pack_does_not_break_loading(tmp_path):
    root = tmp_path / "root"
    write_pack(root / "mods" / "good", content_payload("character.good"))
    extra = tmp_path / "extra"
    write_pack(extra / "bad", content_payload("character.bad", version="nope"))

    result = load_mods(root, (extra,))

    assert [mod.manifest.id for mod in result.mods] == ["character.good"]
    assert any("character.bad" in item or "bad" in item for item in result.diagnostics)


def test_feature_mods_are_gated(tmp_path):
    root = tmp_path / "root"
    write_pack(
        root / "mods" / "clock",
        feature_payload(),
        {"host/factory.py": ""},
    )

    gated = load_mods(root)
    assert gated.mods[0].enabled is False
    assert any("feature mods disabled" in item for item in gated.diagnostics)

    allowed = load_mods(root, allow_feature_mods=True)
    assert allowed.mods[0].enabled is True
    assert allowed.diagnostics == ()


def test_feature_mods_outside_user_mods_stay_disabled(tmp_path):
    root = tmp_path / "root"
    (root / "mods").mkdir(parents=True)
    extra = tmp_path / "extra"
    write_pack(extra / "clock", feature_payload(), {"host/factory.py": ""})

    result = load_mods(root, (extra,), allow_feature_mods=True)

    assert result.mods[0].enabled is False
    assert any("feature mods disabled" in item for item in result.diagnostics)


def test_content_blocks_become_entries(tmp_path):
    root = tmp_path / "root"
    write_pack(
        root / "mods" / "demo",
        content_payload(
            character={"id": "shenshen", "media_dir": "media"},
            sounds={"click": "sounds/click.wav"},
            themes={"dark": {"path": "themes/dark.json"}},
            phrases={"greeting": "phrases/greeting.json"},
            seasonal={"winter": {"path": "seasonal/winter.json"}},
        ),
    )

    result = load_mods(root)

    keys = {(entry.kind, entry.id) for entry in result.contents}
    assert keys == {
        ("character", "shenshen"),
        ("sound", "click"),
        ("theme", "dark"),
        ("phrases", "greeting"),
        ("seasonal", "winter"),
    }
    assert all(entry.owner == "character.demo" for entry in result.contents)
    character = next(entry for entry in result.contents if entry.kind == "character")
    assert character.data["media_dir"] == "media"


def test_character_id_falls_back_to_manifest_namespace(tmp_path):
    root = tmp_path / "root"
    write_pack(
        root / "mods" / "demo",
        content_payload("character.shenshen", character={"media": "videos"}),
    )

    result = load_mods(root)

    character = next(entry for entry in result.contents if entry.kind == "character")
    assert character.id == "shenshen"
    assert character.path == (root / "mods" / "demo").resolve()


def test_corrupt_state_degrades_to_empty(tmp_path):
    root = tmp_path / "root"
    (root / "mods").mkdir(parents=True)
    (root / "mods-state.json").write_text("{not json", encoding="utf-8")
    write_pack(root / "mods" / "demo", content_payload())

    result = load_mods(root)

    assert result.mods[0].enabled is True
    state.set_enabled(root, "character.demo", False)
    assert "character.demo" in state.load_disabled(root)
