"""扩展授信与压缩包条目的安全边界（审计 AUD-01 / AUD-05）。

两条硬约束：

1. 包内容不等于授权——本地导入（ZIP/目录）自带 `.trusted` 一律剥掉，且
   `is_trusted()` 只认安装目录下的标记；
2. ZIP 条目名不能是 Windows 上的危险形态（ADS、保留设备名、大小写冲突）。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from petcore.mods import trust
from petcore.mods.install import install
from petcore.mods.loader import load_mods

FEATURE = {
    "schema": 1,
    "id": "evil.feature",
    "kind": "feature",
    "name": "evil",
    "version": "1.0.0",
    "entrypoint": "host/__init__.py:create_host",
}


def _feature_zip(target: Path, *, marker: bool) -> Path:
    archive = target / "pack.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", json.dumps(FEATURE))
        handle.writestr("host/__init__.py", "def create_host(ctx=None):\n    return object()\n")
        if marker:
            handle.writestr(trust.TRUST_MARKER, "")
    return archive


def test_local_import_strips_bundled_trust_marker(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    ok, message = install(_feature_zip(tmp_path, marker=True), root)
    assert ok, message
    pack = root / "mods" / "evil.feature"
    assert not (pack / trust.TRUST_MARKER).exists()
    result = load_mods(root, (), allow_feature_mods=False)
    assert [(mod.manifest.id, mod.enabled) for mod in result.mods] == [("evil.feature", False)]
    assert any("feature mods disabled" in item for item in result.diagnostics)


def test_control_group_without_marker_stays_disabled(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    ok, message = install(_feature_zip(tmp_path, marker=False), root)
    assert ok, message
    result = load_mods(root, (), allow_feature_mods=False)
    assert [(mod.manifest.id, mod.enabled) for mod in result.mods] == [("evil.feature", False)]


def test_trust_marker_only_counts_inside_the_install_root(tmp_path: Path, monkeypatch) -> None:
    install_root = tmp_path / "app" / "mods"
    inside = install_root / "fun.demo"
    inside.mkdir(parents=True)
    (inside / trust.TRUST_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setattr(trust, "install_trust_root", lambda: install_root)
    assert trust.is_trusted(inside) is True

    outside = tmp_path / "data" / "mods" / "fun.demo"
    outside.mkdir(parents=True)
    (outside / trust.TRUST_MARKER).write_text("", encoding="utf-8")
    assert trust.is_trusted(outside) is False


def test_trust_marker_is_ignored_when_not_frozen(tmp_path: Path, monkeypatch) -> None:
    pack = tmp_path / "mods" / "fun.demo"
    pack.mkdir(parents=True)
    (pack / trust.TRUST_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setattr(trust, "install_trust_root", lambda: None)
    assert trust.is_trusted(pack) is False


def test_trust_marker_requires_the_file(tmp_path: Path, monkeypatch) -> None:
    install_root = tmp_path / "app" / "mods"
    pack = install_root / "fun.demo"
    pack.mkdir(parents=True)
    monkeypatch.setattr(trust, "install_trust_root", lambda: install_root)
    assert trust.is_trusted(pack) is False


@pytest.mark.parametrize("entry", ["mod.json:evil", "con", "CON.txt", "lpt1", "aux"])
def test_zip_rejects_windows_hostile_entry_names(tmp_path: Path, entry: str) -> None:
    root = tmp_path / "data"
    root.mkdir()
    archive = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", json.dumps({"schema": 1, "id": "x.y", "kind": "content", "name": "x", "version": "1.0.0"}))
        handle.writestr(entry, "payload")
    ok, message = install(archive, root)
    assert ok is False
    assert "unsafe zip entry" in message
    assert not (root / "mods" / "x.y").exists()


def test_zip_rejects_case_insensitive_collisions(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    archive = tmp_path / "case.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", json.dumps({"schema": 1, "id": "x.y", "kind": "content", "name": "x", "version": "1.0.0"}))
        handle.writestr("A.txt", "1")
        handle.writestr("a.txt", "2")
    ok, message = install(archive, root)
    assert ok is False
    assert "duplicate zip entry" in message


@pytest.mark.parametrize("mod_id", ["nul", "con", "com1", "lpt9", "nul.extra"])
def test_reserved_device_names_are_not_valid_mod_ids(mod_id: str) -> None:
    from petcore.mods.manifest import is_valid_id

    assert is_valid_id(mod_id) is False


def test_normal_ids_still_validate() -> None:
    from petcore.mods.manifest import is_valid_id

    for value in ("fun.divination", "character.shenshen", "tool.ocr", "a1"):
        assert is_valid_id(value) is True
