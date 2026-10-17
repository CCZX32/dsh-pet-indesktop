# -*- coding: utf-8 -*-
"""官方包来源解析：显式根、源码态构建缓存、冻结态随包目录。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pet.official_features import AI_FEATURE_ID, SCREEN_FEATURE_ID
from pet.official_package_source import resolve_official_package


def _fake_package(root: Path, name: str) -> Path:
    package = root / name
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps({"id": "official.ai-chat"}), encoding="utf-8")
    return package


def test_an_unknown_owner_is_invalid(tmp_path):
    source = resolve_official_package("official.nope", root=tmp_path)

    assert source.status == "invalid"


def test_an_explicit_root_finds_the_directory_or_zip(tmp_path):
    _fake_package(tmp_path, "ai-chat")

    source = resolve_official_package(AI_FEATURE_ID, root=tmp_path)

    assert source.found and source.path == tmp_path / "ai-chat"


def test_an_explicit_root_can_answer_absent_without_building(tmp_path):
    source = resolve_official_package(AI_FEATURE_ID, root=tmp_path, allow_build=False)

    assert source.status == "absent"
    assert str(tmp_path) in source.reason


def test_source_state_builds_into_the_data_cache(tmp_path):
    source = resolve_official_package(AI_FEATURE_ID, config_dir=tmp_path, allow_build=True)

    assert source.found
    assert source.path == tmp_path / "official-packages" / "ai-chat"
    assert (source.path / "manifest.json").is_file()


def test_a_frozen_app_reads_the_features_directory_next_to_the_executable(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    (_fake_package(app_dir / "features", "ai-chat"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "dsh-pet.exe"))

    source = resolve_official_package(AI_FEATURE_ID)

    assert source.found and source.path == app_dir / "features" / "ai-chat"


def test_a_frozen_app_without_the_package_reports_where_it_looked(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "dsh-pet.exe"))

    source = resolve_official_package(SCREEN_FEATURE_ID)

    assert source.status == "absent"
    assert "features" in source.reason
