from __future__ import annotations

import json
from pathlib import Path

from petcore.content.character_pack import build_character_pack, validate_character_source
from petcore.content.collect import collect_characters
from petcore.content.importer import install_character_source
from petcore.content.legacy import build_animations
from petcore.engine.enums import GraphType


def _source(root: Path) -> Path:
    source = root / "source"
    videos = source / "videos"
    videos.mkdir(parents=True)
    (videos / "idle.webm").write_bytes(b"")
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "name": "Test Pet",
                "body_box": [212, 60, 428, 330],
                "head_box": [185, 60, 436, 195],
            }
        ),
        encoding="utf-8",
    )
    return source


def test_build_character_pack_and_collect(tmp_path):
    source = _source(tmp_path)
    out = tmp_path / "mods" / "character.test"
    ok, message = build_character_pack(source, out, link=False)
    assert ok, message
    manifest = json.loads((out / "mod.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "character.test"
    assert manifest["kind"] == "content"
    assert manifest["character"]["media"] == "videos"
    assert manifest["character"]["body_box"] == [212, 60, 428, 330]
    assert (out / "videos" / "idle.webm").is_file()

    characters, _result = collect_characters(
        root=tmp_path / "data", mod_dirs=(tmp_path / "mods",), frameseq_mode="off"
    )
    assert any(character.id == "test" for character in characters)


def test_validate_rejects_missing_media_and_bad_boxes(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert validate_character_source(empty)

    source = _source(tmp_path)
    (source / "videos" / "idle.webm").unlink()
    assert validate_character_source(source)

    source = _source(tmp_path / "bad")
    (source / "manifest.json").write_text(
        json.dumps({"body_box": [0, 0, 0, 10]}), encoding="utf-8"
    )
    assert "invalid body_box" in validate_character_source(source)[0]


def test_build_rejects_invalid_id_and_non_empty_target(tmp_path):
    source = _source(tmp_path)
    ok, message = build_character_pack(source, tmp_path / "out", character_id="bad id")
    assert ok is False
    assert "invalid character id" in message

    target = tmp_path / "used"
    target.mkdir()
    (target / "x").write_text("x", encoding="utf-8")
    ok, message = build_character_pack(source, target)
    assert ok is False
    assert "not empty" in message


def test_settings_importer_installs_character_mod(tmp_path):
    source = _source(tmp_path)
    data_root = tmp_path / "data"
    ok, message, character_id = install_character_source(source, data_root)

    assert ok, message
    assert character_id == "character.source"
    assert (data_root / "mods" / "character.source" / "mod.json").is_file()
    assert not (data_root / ".character-import").exists()


def test_legacy_animation_folders_cover_vpet_graph_categories(tmp_path):
    videos = tmp_path / "videos"
    for folder in ("touch_head", "say", "sleep", "startup", "work", "raised_dynamic"):
        path = videos / folder
        path.mkdir(parents=True)
        (path / "sample.webm").write_bytes(b"")

    animations = build_animations(videos, tmp_path / "frameseq", "off")
    graphs = {animation.graph for animation in animations}

    assert GraphType.TOUCH_HEAD in graphs
    assert GraphType.SAY in graphs
    assert GraphType.SLEEP in graphs
    assert GraphType.STARTUP in graphs
    assert GraphType.WORK in graphs
    assert GraphType.RAISED_DYNAMIC in graphs
