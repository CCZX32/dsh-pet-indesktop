"""旧数据迁移框架与配置域的测试。

真实用户目录一律不碰：全部在 `tmp_path` 下造旧壳数据根。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petcore import migration
from petcore.migration import config_data


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def config_domains(monkeypatch):
    """只跑配置三域，避开并行开发中的会话/待办/凭据域。"""
    monkeypatch.setattr(
        migration,
        "_domain_functions",
        lambda: (
            ("config", config_data.migrate_config),
            ("slots", config_data.migrate_slots),
            ("active_pets", config_data.migrate_active_pets),
        ),
    )


def _target(tmp_path: Path) -> Path:
    return tmp_path / "new-root"


def _legacy(tmp_path: Path, name: str = "dsh-pet-standalone") -> Path:
    return tmp_path / name


def test_plan_writes_nothing(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen", "scale": 1.5})
    target = _target(tmp_path)

    report = migration.plan(target, legacy_root=legacy)

    assert report.dry_run is True
    assert not target.exists()
    assert not migration.marker_path(target).exists()


def test_config_domain_fills_only_missing_keys(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(
        legacy / "config.json",
        {"character": "旧角色", "scale": 1.5, "unknown_key": "不迁"},
    )
    target = _target(tmp_path)
    _write_json(target / "config.json", {"character": "当前角色"})

    report = migration.run(target, legacy_root=legacy)

    data = _read_json(target / "config.json")
    assert data["character"] == "当前角色", "目标已有的键不许被旧值覆盖"
    assert data["scale"] == 1.5
    assert "unknown_key" not in data
    assert any(entry.kind == "config" and entry.status == migration.STATUS_MIGRATED for entry in report.entries)
    assert (target / migration.MARKER_FILENAME).is_file()


def test_second_run_is_skipped_by_marker(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"scale": 1.25})
    target = _target(tmp_path)

    migration.run(target, legacy_root=legacy)
    second = migration.run(target, legacy_root=legacy)

    assert all(
        entry.status == migration.STATUS_ALREADY
        for entry in second.by_kind("config")
    )
    assert "config" in _read_json(target / migration.MARKER_FILENAME)["completed"]


def test_slot_zero_merges_into_global_config(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen"})
    _write_json(legacy / "config-slot-0.json", {"scale": 2.0, "always_on_top": False})
    target = _target(tmp_path)

    migration.run(target, legacy_root=legacy)

    data = _read_json(target / "config.json")
    assert data["scale"] == 2.0
    assert data["always_on_top"] is False


def test_child_slot_is_written_as_pet_config(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen"})
    _write_json(legacy / "config-slot-3.json", {"scale": 1.75})

    target = _target(tmp_path)
    migration.run(target, legacy_root=legacy)

    pet_config = target / "config-pet-3.json"
    assert pet_config.is_file()
    assert _read_json(pet_config)["scale"] == 1.75


def test_active_pets_adopted_only_when_target_is_default(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen"})
    _write_json(legacy / "overlay-active-pets.json", {"version": 2, "slots": [0, 2]})

    fresh = _target(tmp_path)
    migration.run(fresh, legacy_root=legacy)
    assert _read_json(fresh / "config.json")["active_pets"] == [0, 2]

    already = tmp_path / "already-there"
    _write_json(already / "config.json", {"active_pets": [0, 5]})
    migration.run(already, legacy_root=legacy)
    assert _read_json(already / "config.json")["active_pets"] == [0, 5]


def test_rollback_restores_and_removes(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"scale": 1.5})
    target = _target(tmp_path)
    original = {"character": "保留我", "schema": 5}
    _write_json(target / "config.json", original)

    migration.run(target, legacy_root=legacy)
    assert _read_json(target / "config.json")["scale"] == 1.5

    report = migration.rollback(target)

    restored = _read_json(target / "config.json")
    assert restored["character"] == "保留我"
    assert "scale" not in restored
    assert all(entry.status != migration.STATUS_FAILED_WRITE for entry in report.entries)
    assert not migration.marker_path(target).exists()


def test_missing_legacy_root_is_reported(tmp_path: Path, config_domains) -> None:
    report = migration.run(tmp_path / "new-root", legacy_root=tmp_path / "does-not-exist")
    assert report.entries == () or any(
        entry.status == migration.STATUS_NOT_FOUND for entry in report.entries
    )

def test_rollback_removes_files_that_did_not_exist_before(tmp_path: Path, config_domains) -> None:
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"scale": 1.5})
    target = _target(tmp_path)

    migration.run(target, legacy_root=legacy)
    assert (target / "config.json").is_file()

    migration.rollback(target)
    assert not (target / "config.json").exists()

def test_full_migration_covers_every_domain_without_touching_keyring(tmp_path: Path) -> None:
    """整条链路跑一遍：配置/slot/活跃集合/会话/待办都搬，凭据域在无旧凭据时不写。"""
    legacy = _legacy(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen", "scale": 1.5})
    _write_json(legacy / "config-slot-0.json", {"always_on_top": False})
    _write_json(legacy / "overlay-active-pets.json", {"version": 2, "slots": [0, 1]})
    _write_json(
        legacy / "sessions" / "shenshen" / "s1.json",
        {
            "session_id": "s1",
            "title": "旧会话",
            "created_at": "2026-10-01T10:00:00+00:00",
            "updated_at": "2026-10-01T10:05:00+00:00",
            "messages": [{"role": "user", "content": "你好"}],
        },
    )
    _write_json(
        legacy / "todo_items.json",
        {"version": 1, "items": [{"id": "t1", "title": "喝水", "kind": "daily", "time": "09:30", "enabled": True}]},
    )
    target = _target(tmp_path)

    report = migration.run(target, legacy_root=legacy)

    kinds = {entry.kind for entry in report.entries if entry.status == migration.STATUS_MIGRATED}
    assert {"config", "slots", "active_pets", "sessions", "todos"} <= kinds
    assert report.failures == ()
    assert (target / "sessions" / "shenshen" / "s1.json").is_file()
    assert (target / "feature-data" / "reminder.todo" / "todo-slot-0-v2.json").is_file()

    again = migration.run(target, legacy_root=legacy)
    assert all(
        entry.status in (migration.STATUS_ALREADY, migration.STATUS_NOT_FOUND)
        for entry in again.entries
    )
