"""旧壳待办 → ``reminder.todo`` v2 迁移的域测试。

只碰 ``tmp_path``：造一份 ``todo_items.json``，直接调 ``todos.migrate``，
再用扩展自己的 ``validate`` 复核产物。
"""

from __future__ import annotations

import json
from datetime import date

from petcore.migration import (
    STATUS_ALREADY,
    STATUS_FAILED_VALIDATION,
    STATUS_MIGRATED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
    STATUS_UNSUPPORTED,
    MigrationContext,
)
from petcore.migration import todos


def _ctx(root, legacy, *, dry_run: bool = False) -> MigrationContext:
    return MigrationContext(
        root=root,
        legacy_roots=(legacy,),
        dry_run=dry_run,
        backup_root=root / "migration-backup",
    )


def _legacy_items(legacy, items, *, version: int = 1):
    legacy.mkdir(parents=True, exist_ok=True)
    path = legacy / "todo_items.json"
    path.write_text(
        json.dumps({"version": version, "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _target(root):
    return root / "feature-data" / "reminder.todo" / "todo-slot-0-v2.json"


def _load(root):
    return json.loads(_target(root).read_text(encoding="utf-8"))


def _validate(state):
    # 产品路径解析到的就是扩展自己的 validate（examples 里的 model.py）。
    validate = todos._validator()
    assert validate is not None, "reminder.todo 的 model.py 没被解析到"
    return validate(state)


def test_migrates_items_into_valid_v2_document(tmp_path):
    legacy = tmp_path / "legacy"
    source = _legacy_items(
        legacy,
        [
            {
                "id": "a1",
                "title": "交周报",
                "kind": "once",
                "time": "09:30",
                "date": "2026-11-02",
                "enabled": True,
                "fired_lead_slot": None,
                "fired_due_slot": None,
            },
            {
                "id": "a2",
                "title": "喝水",
                "kind": "daily",
                "time": "14:00",
                "date": "",
                "enabled": True,
                "fired_lead_slot": None,
                "fired_due_slot": None,
            },
        ],
    )
    original = source.read_bytes()
    data = tmp_path / "data"
    ctx = _ctx(data, legacy)

    entries = todos.migrate(ctx)

    assert [entry.status for entry in entries] == [STATUS_MIGRATED]
    entry = entries[0]
    assert entry.kind == "todos"
    assert entry.count == 2
    assert "slot:0" in entry.detail
    state = _load(data)
    assert state["schema_version"] == 2
    assert [item["title"] for item in state["items"]] == ["交周报", "喝水"]
    assert [item["id"] for item in state["items"]] == ["a1", "a2"]
    once, daily = state["items"]
    assert (once["kind"], once["date"], once["time"]) == ("once", "2026-11-02", "09:30")
    assert (daily["kind"], daily["date"], daily["time"]) == ("daily", "", "14:00")
    assert all(item["enabled"] is True and item["archived"] is False for item in state["items"])
    assert all(item["marks"] == {} for item in state["items"])
    _validate(state)
    history = data / "feature-data" / "reminder.todo" / "todo-slot-0-legacy-v1.json"
    # 扩展对这份历史的契约是 `[title, ...]`；旧文件的原始字节留在 migration-backup/
    # （审计 AUD-10：写 dict 文档会让扩展在 v2 缺失时报 invalid migration backup）。
    assert json.loads(history.read_text(encoding="utf-8")) == [item["title"] for item in state["items"]]
    assert original.startswith(b"{")
    assert entry.backup == str(history)
    assert source.read_bytes() == original
    assert {"kind": "todos", "backup": "", "target": str(_target(data))} in ctx.restore


def test_daily_and_once_fields_and_marks(tmp_path):
    today = date.today().isoformat()
    legacy = tmp_path / "legacy"
    _legacy_items(
        legacy,
        [
            {
                "id": "d1",
                "title": "日报",
                "kind": "daily",
                "time": "9:05",
                "date": "",
                "enabled": True,
                "fired_lead_slot": "2026-10-01T09:05#lead",
                "fired_due_slot": None,
            },
            {
                "id": "o1",
                "title": "缴费",
                "kind": "once",
                "time": "23:59",
                "date": "2026-03-01",
                "enabled": False,
                "fired_lead_slot": None,
                "fired_due_slot": "2026-03-01T23:59#due",
            },
            {
                "id": "n1",
                "title": "随手记",
                "kind": "none",
                "time": "",
                "date": "",
                "enabled": True,
                "fired_due_slot": "whatever",
            },
        ],
    )
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert entries[0].status == STATUS_MIGRATED
    state = _load(data)
    items = {item["id"]: item for item in state["items"]}
    daily = items["d1"]
    assert (daily["kind"], daily["time"], daily["date"]) == ("daily", "09:05", "")
    # daily 用今天那次；marks 记的是到期时刻，不是旧串。
    assert daily["marks"] == {"lead": f"{today}T09:05"}
    once = items["o1"]
    assert (once["kind"], once["date"], once["enabled"]) == ("once", "2026-03-01", False)
    assert once["marks"] == {"due": "2026-03-01T23:59"}
    none = items["n1"]
    assert (none["kind"], none["time"], none["date"]) == ("none", "", "")
    assert none["marks"] == {}
    assert "marks-dropped-due:1" in entries[0].detail
    _validate(state)


def test_existing_target_is_not_overwritten(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy_items(
        legacy, [{"id": "a", "title": "旧待办", "kind": "daily", "time": "08:00", "enabled": True}]
    )
    data = tmp_path / "data"
    assert todos.migrate(_ctx(data, legacy))[0].status == STATUS_MIGRATED
    target = _target(data)
    target.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "items": [
                    {
                        "id": "new",
                        "title": "用户改过",
                        "kind": "none",
                        "date": "",
                        "time": "",
                        "enabled": True,
                        "archived": False,
                        "marks": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before = target.read_bytes()

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_ALREADY]
    assert target.read_bytes() == before


def test_broken_json_is_skipped_and_preserved(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    source = legacy / "todo_items.json"
    source.write_text("{ not json", encoding="utf-8")
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_SKIPPED]
    assert "invalid-json" in entries[0].detail
    assert source.read_text(encoding="utf-8") == "{ not json"
    assert not _target(data).exists()


def test_items_not_a_list_is_skipped(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    source = legacy / "todo_items.json"
    source.write_text(json.dumps({"version": 1, "items": {"a": 1}}), encoding="utf-8")
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_SKIPPED]
    assert "items-not-list" in entries[0].detail
    assert not _target(data).exists()


def test_missing_items_migrates_an_empty_document(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "todo_items.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_MIGRATED]
    assert entries[0].count == 0
    assert _load(data) == {"schema_version": 2, "items": []}


def test_all_invalid_entries_leave_no_document(tmp_path):
    legacy = tmp_path / "legacy"
    source = _legacy_items(legacy, ["字符串条目", {"title": "   "}])
    original = source.read_bytes()
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_SKIPPED]
    assert "dropped:2" in entries[0].detail
    assert not _target(data).exists()
    assert source.read_bytes() == original


def test_unknown_kind_is_normalized_to_once(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy_items(
        legacy, [{"id": "m1", "title": "每月体检", "kind": "monthly", "time": "10:00", "date": ""}]
    )
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy))

    assert entries[0].status == STATUS_MIGRATED
    assert "normalized-kind:1" in entries[0].detail
    assert "normalized-date:1" in entries[0].detail
    item = _load(data)["items"][0]
    assert (item["kind"], item["date"], item["time"]) == ("once", date.today().isoformat(), "10:00")
    _validate(_load(data))


def test_duplicate_ids_are_regenerated(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy_items(
        legacy,
        [
            {"id": "same", "title": "一", "kind": "none"},
            {"id": "same", "title": "二", "kind": "none"},
        ],
    )
    data = tmp_path / "data"

    assert todos.migrate(_ctx(data, legacy))[0].status == STATUS_MIGRATED

    ids = [item["id"] for item in _load(data)["items"]]
    assert ids[0] == "same"
    assert ids[1] != "same" and ids[1]
    _validate(_load(data))


def test_dry_run_writes_nothing(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy_items(
        legacy, [{"id": "a", "title": "草稿", "kind": "daily", "time": "07:00", "enabled": True}]
    )
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, legacy, dry_run=True))

    assert [entry.status for entry in entries] == [STATUS_MIGRATED]
    assert not (data / "feature-data").exists()
    assert not (data / "migration-backup").exists()


def test_missing_legacy_file_reports_not_found(tmp_path):
    data = tmp_path / "data"

    entries = todos.migrate(_ctx(data, tmp_path / "legacy"))

    assert [entry.status for entry in entries] == [STATUS_NOT_FOUND]
    assert "slot:0" in entries[0].detail
    assert not (data / "feature-data").exists()


def test_payload_rejected_by_extension_is_not_written(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    _legacy_items(legacy, [{"id": "a", "title": "日报", "kind": "daily", "time": "08:00"}])
    data = tmp_path / "data"

    def _reject(_state):
        raise ValueError("unsupported todo document")

    monkeypatch.setattr(todos, "_validator", lambda: _reject)

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_FAILED_VALIDATION]
    assert "error:ValueError" in entries[0].detail
    assert not _target(data).exists()


def test_post_write_revalidation_failure_removes_the_document(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    _legacy_items(legacy, [{"id": "a", "title": "日报", "kind": "daily", "time": "08:00"}])
    data = tmp_path / "data"
    calls = []

    def _reject_on_reread(state):
        calls.append(state)
        if len(calls) > 1:
            raise ValueError("invalid todo entry; original file preserved")

    monkeypatch.setattr(todos, "_validator", lambda: _reject_on_reread)

    entries = todos.migrate(_ctx(data, legacy))

    assert len(calls) == 2
    assert [entry.status for entry in entries] == [STATUS_FAILED_VALIDATION]
    assert "error:ValueError" in entries[0].detail
    assert not _target(data).exists()


def test_absent_extension_validator_is_unsupported(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    _legacy_items(legacy, [{"id": "a", "title": "日报", "kind": "daily", "time": "08:00"}])
    data = tmp_path / "data"

    monkeypatch.setattr(todos, "_validator", lambda: None)

    entries = todos.migrate(_ctx(data, legacy))

    assert [entry.status for entry in entries] == [STATUS_UNSUPPORTED]
    assert "validator-missing" in entries[0].detail
    assert not _target(data).exists()
