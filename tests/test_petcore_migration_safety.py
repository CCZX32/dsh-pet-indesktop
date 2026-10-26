"""迁移回滚的安全性（审计 AUD-06 / AUD-09 / AUD-10）。

三条硬约束：

1. 回滚覆盖/删除前必须给**当前**文件留 `.pre-rollback-*` 副本；
2. 同一目标有多条 restore 记录时只按**最早**那条恢复（否则停在迁移中间态）；
3. 只要有一条 `not_found`/`failed_write`，标记就不能删——否则 restore 映射
   随标记一起消失，回滚既不可重试也查不到。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petcore import migration


@pytest.fixture(autouse=True)
def _no_user_keyring(monkeypatch):
    """迁移的凭据域在测试里一律走内存后端，不碰真实钥匙串。"""
    from petcore.migration import accounts

    monkeypatch.setattr(accounts, "_open_backend", lambda backend=None: None, raising=False)


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "config.json").write_text(
        json.dumps({"character": "old", "scale": 1.1}), encoding="utf-8"
    )
    return legacy


def test_rollback_preserves_current_file_before_overwriting(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    report = migration.run(root, legacy_root=_legacy(tmp_path))
    assert report.migrated, report.as_dict()

    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    config["scale"] = 2.5
    config["user_added"] = "keep-me"
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")

    outcome = migration.rollback(root)
    assert outcome.failures == (), outcome.as_dict()

    preserved = sorted(root.glob("config.json.pre-rollback-*"))
    assert preserved, "回滚前必须留当前文件的副本"
    kept = json.loads(preserved[0].read_text(encoding="utf-8"))
    assert kept["scale"] == 2.5
    assert kept["user_added"] == "keep-me"


def test_rollback_same_target_records_final_state_is_pre_migration(tmp_path: Path) -> None:
    """config/slots/active_pets 三条记录指向同一个 config.json。"""
    root = tmp_path / "root"
    root.mkdir()
    legacy = _legacy(tmp_path)
    (legacy / "config-slot-0.json").write_text(
        json.dumps({"character": "slot0", "self_talk_enabled": False}), encoding="utf-8"
    )
    (legacy / "overlay-active-pets.json").write_text(
        json.dumps({"slots": [0, 1]}), encoding="utf-8"
    )
    report = migration.run(root, legacy_root=legacy)
    assert report.migrated, report.as_dict()
    marker = migration.read_marker(root)
    targets = [item["target"] for item in marker.get("restore") or []]
    assert len(set(targets)) < len(targets), "本用例需要多条记录指向同一目标"

    migration.rollback(root)
    final = root / "config.json"
    # 迁移前磁盘上根本没有 config.json：回滚后必须是「没有」，
    # 而不是停在其中一条备份的中间态。
    assert not final.exists()


def test_rollback_keeps_marker_when_a_backup_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # 目标已存在，迁移才会备份它 —— 这正是「备份被删」场景的前提。
    (root / "config.json").write_text(json.dumps({"scale": 0.9}), encoding="utf-8")
    report = migration.run(root, legacy_root=_legacy(tmp_path))
    assert report.migrated
    marker = migration.read_marker(root)
    backups = [Path(item["backup"]) for item in marker.get("restore") or [] if item.get("backup")]
    assert backups
    backups[0].unlink()

    outcome = migration.rollback(root)
    assert outcome.failures, "缺备份必须算失败"
    assert migration.marker_path(root).exists(), "失败时标记必须保留，回滚方可重试"


def test_rollback_refuses_directory_targets(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    report = migration.run(root, legacy_root=_legacy(tmp_path))
    assert report.migrated
    target = root / "config.json"
    target.unlink()
    target.mkdir()

    outcome = migration.rollback(root)
    assert any(entry.detail == "target-is-directory" for entry in outcome.entries)
    assert migration.marker_path(root).exists()


def test_domain_with_a_write_failure_is_not_marked_complete(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    legacy = _legacy(tmp_path)
    sessions = legacy / "sessions" / "shenshen"
    sessions.mkdir(parents=True)
    (sessions / "a.json").write_text(json.dumps({"updated_at": "2026-10-20T10:00:00+00:00", "messages": []}), encoding="utf-8")
    (sessions / "b.json").write_text(json.dumps({"updated_at": "2026-10-20T10:00:00+00:00", "messages": []}), encoding="utf-8")
    # 让 sessions 目标目录被同名文件占住：其中一个文件的写入必定失败。
    (root / "sessions").mkdir()
    (root / "sessions" / "shenshen").write_text("blocker", encoding="utf-8")

    first = migration.run(root, legacy_root=legacy)
    assert any(entry.status == migration.STATUS_FAILED_WRITE for entry in first.entries), first.as_dict()
    assert "sessions" not in (migration.read_marker(root).get("completed") or {})

    second = migration.run(root, legacy_root=legacy)
    statuses = {entry.kind: entry.status for entry in second.by_kind("sessions")}
    assert statuses.get("sessions") != migration.STATUS_ALREADY


def test_todos_history_matches_the_extension_contract(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    legacy = _legacy(tmp_path)
    (legacy / "todo_items.json").write_text(
        json.dumps({"items": [{"title": "任务甲", "date": "2026-10-20", "time": "09:00"}]}),
        encoding="utf-8",
    )
    report = migration.run(root, legacy_root=legacy)
    entry = next((item for item in report.by_kind("todos")), None)
    assert entry is not None
    if entry.status == migration.STATUS_UNSUPPORTED:
        pytest.skip("待办扩展未安装，校验器缺失时按设计跳过")
    history = Path(entry.backup)
    assert history.is_file()
    payload = json.loads(history.read_text(encoding="utf-8"))
    assert isinstance(payload, list), "扩展期望 list[str]，不是旧文件的 dict 文档"
    assert all(isinstance(item, str) for item in payload)
