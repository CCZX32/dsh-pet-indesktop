# -*- coding: utf-8 -*-
"""账户用量包的构建门：manifest 形状、清单库存、ZIP 与目录一致。"""

from __future__ import annotations

import hashlib
import json
import zipfile

from tests.account_usage_fakes import OWNER, build_package


def test_built_manifest_is_host_only_and_matches_the_registry(tmp_path):
    built = build_package(tmp_path / "built")
    manifest = json.loads((built / "manifest.json").read_text("utf-8"))
    assert manifest["id"] == OWNER
    assert manifest["execution_kind"] == "host-only"
    assert manifest["worker"] is None
    assert manifest["factory"] == "account-usage/v1"
    assert manifest["api_version"] == "1"
    assert set(manifest["capabilities"]) == {"network.http", "settings.contribute", "menu.contribute"}
    assert "host/factory.py" in manifest["files"]


def test_inventory_covers_every_shipped_byte(tmp_path):
    built = build_package(tmp_path / "built")
    manifest = json.loads((built / "manifest.json").read_text("utf-8"))
    on_disk = {
        path.relative_to(built).as_posix(): path.read_bytes()
        for path in built.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert set(manifest["files"]) == set(on_disk)
    for relative, data in on_disk.items():
        assert manifest["files"][relative]["sha256"] == hashlib.sha256(data).hexdigest()
        assert manifest["files"][relative]["size"] == len(data)


def test_zip_contains_the_same_tree_as_the_directory(tmp_path):
    built = build_package(tmp_path / "built")
    with zipfile.ZipFile(built.with_suffix(".zip")) as archive:
        names = {name for name in archive.namelist() if not name.endswith("/")}
    expected = {path.relative_to(built).as_posix() for path in built.rglob("*") if path.is_file()}
    assert names == expected
