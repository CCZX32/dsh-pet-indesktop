from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from petcore.mods.install import install, remove, validate


def write_pack(base: Path, payload: dict, files: dict[str, str] | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "mod.json").write_text(json.dumps(payload), encoding="utf-8")
    for name, content in (files or {}).items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


def content_payload(**overrides) -> dict:
    payload = {
        "schema": 1,
        "id": "character.demo",
        "kind": "content",
        "name": "Demo",
        "version": "1.0.0",
        "api_version": "1",
        "character": {"id": "demo", "media_dir": "media"},
    }
    payload.update(overrides)
    return payload


def make_zip(archive: Path, pack: Path) -> Path:
    with zipfile.ZipFile(archive, "w") as handle:
        for path in sorted(pack.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(pack).as_posix())
    return archive


def test_install_directory(tmp_path):
    root = tmp_path / "data"
    pack = write_pack(
        tmp_path / "src" / "demo",
        content_payload(),
        {"media/idle.png": "image-bytes"},
    )

    ok, message = install(pack, root)

    assert ok, message
    target = root / "mods" / "character.demo"
    assert (target / "mod.json").is_file()
    assert (target / "media" / "idle.png").read_text(encoding="utf-8") == "image-bytes"
    metadata = json.loads((target / "install.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == 1
    assert metadata["id"] == "character.demo"
    assert metadata["version"] == "1.0.0"
    assert "installed_at" in metadata
    expected = hashlib.sha256((target / "mod.json").read_bytes()).hexdigest()
    assert metadata["files"]["mod.json"] == expected
    assert metadata["files"]["media/idle.png"] == hashlib.sha256(b"image-bytes").hexdigest()
    assert not list((root / "mods").glob(".staging-*"))


def test_install_zip(tmp_path):
    root = tmp_path / "data"
    pack = write_pack(tmp_path / "src" / "demo", content_payload(), {"media/idle.png": "x"})
    archive = make_zip(tmp_path / "demo.zip", pack)

    ok, message = install(archive, root)

    assert ok, message
    target = root / "mods" / "character.demo"
    assert (target / "mod.json").is_file()
    assert (target / "media" / "idle.png").is_file()
    assert not list((root / "mods").glob(".unpack-*"))


def test_zip_slip_is_rejected(tmp_path):
    root = tmp_path / "data"
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", json.dumps(content_payload()))
        handle.writestr("../evil.txt", "escaped")

    ok, message = install(archive, root)

    assert not ok
    assert "unsafe zip entry" in message
    assert not (tmp_path / "evil.txt").exists()
    assert not (root / "mods" / "evil.txt").exists()
    assert not list((root / "mods").glob(".unpack-*"))


def test_force_replace(tmp_path):
    root = tmp_path / "data"
    first = write_pack(
        tmp_path / "first" / "demo",
        content_payload(version="1.0.0"),
        {"old.txt": "old"},
    )
    second = write_pack(
        tmp_path / "second" / "demo",
        content_payload(version="2.0.0"),
        {"new.txt": "new"},
    )

    assert install(first, root)[0]
    ok, message = install(second, root)
    assert not ok
    assert "already installed" in message
    target = root / "mods" / "character.demo"
    assert json.loads((target / "mod.json").read_text(encoding="utf-8"))["version"] == "1.0.0"

    ok, message = install(second, root, force=True)
    assert ok, message
    assert json.loads((target / "mod.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
    assert (target / "new.txt").is_file()
    assert not (target / "old.txt").exists()
    assert not list((root / "mods").glob(".trash-*"))


def test_invalid_pack_is_not_installed(tmp_path):
    root = tmp_path / "data"
    pack = write_pack(tmp_path / "src", content_payload(id="Bad.Id"))

    ok, message = install(pack, root)

    assert not ok
    assert "invalid id" in message
    assert not (root / "mods" / "Bad.Id").exists()


def test_remove_only_under_user_mods(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    pack = write_pack(tmp_path / "src" / "demo", content_payload())
    assert install(pack, root_a)[0]
    write_pack(root_b / "mods" / "character.demo", content_payload())

    ok, message = remove(root_a, "character.demo")
    assert ok, message
    assert not (root_a / "mods" / "character.demo").exists()

    ok, message = remove(root_a, "character.demo")
    assert not ok

    ok, message = remove(root_a, "../character.demo")
    assert not ok
    assert "invalid mod id" in message

    ok, message = remove(root_a, "character.demo")
    assert not ok
    assert (root_b / "mods" / "character.demo" / "mod.json").is_file()


def test_remove_refuses_pack_outside_mods_root(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside" / "character.demo"
    write_pack(outside, content_payload())
    (root / "mods").mkdir(parents=True)

    ok, message = remove(root, "character.demo")

    assert not ok
    assert (outside / "mod.json").is_file()


def test_validate(tmp_path):
    good = write_pack(tmp_path / "good", content_payload())
    bad = write_pack(tmp_path / "bad", content_payload(version="1.0"))
    archive = make_zip(tmp_path / "good.zip", good)

    assert validate(good) == []
    assert validate(archive) == []
    problems = validate(bad)
    assert any("version must be X.Y.Z" in item for item in problems)
