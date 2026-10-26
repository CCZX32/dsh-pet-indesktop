"""旧壳待办条目搬进 ``reminder.todo`` 扩展的 v2 文档。

口径：

- 旧壳 ``todo_items.json`` 是全局的（不分 slot），只迁到主宠 slot 0 的
  ``feature-data/reminder.todo/todo-slot-0-v2.json``；
- 目标 v2 已存在就绝不覆盖：扩展启动时自己会把「v2 已在」记成 already_migrated；
- 写前把旧文件原样复制成 ``todo-slot-0-legacy-v1.json``（该扩展自己的历史备份
  口径），旧文件本身只读不改；
- 落盘后用扩展自己的 ``validate()`` 复读复核，坏文件立刻删掉。

字段语义差异：旧条目的 ``fired_lead_slot`` / ``fired_due_slot`` 是「哪一档已经
提醒过」的标记串（``<date>T<HH:MM>#<phase>``），新模型 ``marks`` 存的却是那次
occurrence 的**到期时刻**，所以这里按到期时刻重算，绝不照抄旧串；算不出来就
不写 marks 并在 detail 里记 ``marks-dropped-<phase>``。
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from .. import paths
from . import (
    STATUS_ALREADY,
    STATUS_FAILED_VALIDATION,
    STATUS_MIGRATED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
    STATUS_UNSUPPORTED,
    MigrationContext,
    MigrationEntry,
)

KIND = "todos"
SLOT = 0
SCHEMA_VERSION = 2
OWNER = "reminder.todo"

DEFAULT_TIME = "09:00"
TITLE_LIMIT = 80
ID_LIMIT = 64
STAMP_FORMAT = "%Y-%m-%dT%H:%M"

ITEM_KINDS = ("none", "once", "daily")
PHASES = (("lead", "fired_lead_slot"), ("due", "fired_due_slot"))

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_MODEL_SCRIPT = ("host", "model.py")


# ------------------------------------------------------------ 扩展自己的校验口径


def _model_candidates() -> tuple[Path, ...]:
    """扩展 ``model.py`` 的候选位置：源码树样板 + 安装器投放的 mods 目录。"""
    candidates = [
        Path(__file__).resolve().parents[2] / "examples" / "petcore-mods" / OWNER / "host" / "model.py"
    ]
    try:
        installed = paths.install_mods_dir()
    except OSError:
        installed = None
    if installed is not None:
        candidates.append(Path(installed) / OWNER / "host" / "model.py")
    return tuple(candidates)


def _load_module(path: Path) -> Any:
    try:
        spec = importlib.util.spec_from_file_location("_petcore_migration_todo_model", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError, ValueError, AttributeError):
        return None
    return module


@lru_cache(maxsize=1)
def _validator() -> Any:
    """取扩展的 ``validate``；扩展不在场时返回 None（不自己另写一套校验）。"""
    for candidate in _model_candidates():
        if not candidate.is_file():
            continue
        module = _load_module(candidate)
        validate = getattr(module, "validate", None)
        if callable(validate):
            return validate
    return None


# ------------------------------------------------------------ 字段归一


def _normalize_hhmm(value: Any) -> str:
    """归一化 HH:MM；接受单位数小时（9:05 → 09:05），非法返回空串。"""
    match = _HHMM_RE.match(str(value or "").strip())
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _normalize_date(value: Any) -> str:
    """归一化成 ``YYYY-MM-DD``；非法返回空串。"""
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        return ""


def _normalize_kind(value: Any) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if text in ITEM_KINDS else None


def _fired(value: Any) -> bool:
    """旧壳的盖戳字段非空即「这一档已经提醒过」；``-1`` 视同没盖戳。"""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        text = value.strip()
        return bool(text) and text != "-1"
    return value != -1


def _due_stamp(kind: str, date_text: str, time_text: str) -> str | None:
    """这次 occurrence 的到期时刻（``%Y-%m-%dT%H:%M``）；算不出来返回 None。

    ``daily`` 用今天那次、``once`` 用条目自己的日期——与旧壳 ``_fire_datetimes``
    的天选择一致；写进 marks 的值必须等于新模型 ``advance`` 会算出的 occurrence，
    否则盖戳对不上，同一条会被再提醒一次。
    """
    if kind not in ("once", "daily"):
        return None
    try:
        clock = time.fromisoformat(time_text)
    except ValueError:
        return None
    if kind == "daily":
        day = date.today()
    else:
        try:
            day = date.fromisoformat(date_text)
        except ValueError:
            return None
    return datetime.combine(day, clock).strftime(STAMP_FORMAT)


def _identity(raw: dict[str, Any], seen: set[str]) -> str:
    text = str(raw.get("id") or "").strip()[:ID_LIMIT]
    if text and text not in seen:
        return text
    return uuid4().hex


def _map_item(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """旧条目 → v2 条目；返回 (条目 | None, 归一说明)。"""
    if not isinstance(raw, dict):
        return None, ["dropped-node"]
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        return None, ["dropped-title"]
    notes: list[str] = []
    kind = _normalize_kind(raw.get("kind"))
    if kind is None:
        # 旧壳 clean_todo_items 对未知 kind 的钳制口径同此。
        kind = "once"
        notes.append("normalized-kind")
    time_text = _normalize_hhmm(raw.get("time"))
    if not time_text:
        if kind == "none":
            time_text = ""
        else:
            time_text = DEFAULT_TIME
            notes.append("normalized-time")
    date_text = ""
    if kind == "once":
        date_text = _normalize_date(raw.get("date"))
        if not date_text:
            date_text = date.today().isoformat()
            notes.append("normalized-date")
    marks: dict[str, str] = {}
    stamp = _due_stamp(kind, date_text, time_text)
    for phase, key in PHASES:
        if not _fired(raw.get(key)):
            continue
        if stamp is None:
            notes.append(f"marks-dropped-{phase}")
        else:
            marks[phase] = stamp
    enabled = raw.get("enabled")
    item = {
        "id": "",
        "title": title.strip()[:TITLE_LIMIT],
        "kind": kind,
        "date": date_text,
        "time": time_text,
        "enabled": enabled if isinstance(enabled, bool) else True,
        "archived": False,
        "marks": marks,
    }
    return item, notes


def _map_items(raw_items: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for raw in raw_items:
        item, notes = _map_item(raw)
        for note in notes:
            counts[note] = counts.get(note, 0) + 1
        if item is None:
            continue
        item["id"] = _identity(raw, seen)
        seen.add(item["id"])
        items.append(item)
    notes = [f"{note}:{counts[note]}" for note in sorted(counts)]
    return items, notes


def _detail(notes: list[str] | None = None) -> str:
    return ";".join([f"slot:{SLOT}", *(notes or [])])


# ------------------------------------------------------------ 域入口


def _parse_object(payload: bytes) -> dict[str, Any] | None:
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _revalidate(target: Path, validate: Any) -> str:
    """落盘后按扩展口径复读复核；返回问题描述，空串表示通过。"""
    try:
        validate(json.loads(target.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, TypeError) as exc:
        return type(exc).__name__
    return ""


def _migrate_source(
    ctx: MigrationContext,
    source: Path,
    *,
    target: Path,
    history: Path,
) -> MigrationEntry | None:
    if target.is_file():
        return ctx.record(
            KIND,
            STATUS_ALREADY,
            source=str(source),
            target=str(target),
            detail=_detail(["target-exists"]),
        )
    try:
        original = source.read_bytes()
    except OSError as exc:
        return ctx.record(
            KIND,
            STATUS_SKIPPED,
            source=str(source),
            detail=_detail([f"read-failed:{type(exc).__name__}"]),
        )
    raw = _parse_object(original)
    if raw is None:
        return ctx.record(
            KIND, STATUS_SKIPPED, source=str(source), detail=_detail(["invalid-json"])
        )
    raw_items = raw.get("items")
    if raw_items is None:
        # 旧壳 load() 对缺失 items 的口径就是「没有待办」，这里同样按空集迁移。
        raw_items = []
    elif not isinstance(raw_items, list):
        return ctx.record(
            KIND, STATUS_SKIPPED, source=str(source), detail=_detail(["items-not-list"])
        )
    items, notes = _map_items(raw_items)
    if raw_items and not items:
        # 全是垃圾就不落盘：旧文件原样保留，报告里看得见跳过了多少条。
        return ctx.record(
            KIND,
            STATUS_SKIPPED,
            source=str(source),
            detail=_detail([*notes, f"dropped:{len(raw_items)}"]),
        )
    payload = {"schema_version": SCHEMA_VERSION, "items": items}
    validate = _validator()
    if validate is None:
        # 目标文档的 schema 归扩展所有；扩展不在场就不猜它的校验口径。
        return ctx.record(
            KIND,
            STATUS_UNSUPPORTED,
            source=str(source),
            target=str(target),
            detail=_detail(["validator-missing"]),
        )
    try:
        validate(payload)
    except (ValueError, TypeError) as exc:
        return ctx.record(
            KIND,
            STATUS_FAILED_VALIDATION,
            source=str(source),
            target=str(target),
            detail=_detail([*notes, f"error:{type(exc).__name__}"]),
        )
    # 扩展对这份「迁移前历史」的口径是 `[title, ...]`（`list[str]`）；写旧文件的
    # 原始字节（`{"items": [...]}`）会让它在 v2 缺失时报 invalid migration backup，
    # 待办面板随即打不开（审计 AUD-10）。
    titles = [str(item.get("title") or "") for item in items]
    history_payload = json.dumps(titles, ensure_ascii=False, indent=2).encode("utf-8")
    if not history.is_file() and not ctx.write_bytes(KIND, history, history_payload):
        # 历史备份写不成就先不迁：ctx 已按 failed_write 记账，这里不再重复报。
        return None
    if target.exists():
        return ctx.record(
            KIND,
            STATUS_ALREADY,
            source=str(source),
            target=str(target),
            detail=_detail(["target-exists"]),
        )
    ctx.remember_restore(KIND, Path(""), target)
    if not ctx.write_json(KIND, target, payload):
        return None
    entry = ctx.record(
        KIND,
        STATUS_MIGRATED,
        source=str(source),
        target=str(target),
        backup=str(history),
        detail=_detail(notes),
        count=len(items),
    )
    if ctx.dry_run:
        return entry
    problem = _revalidate(target, validate)
    if not problem:
        return entry
    try:
        target.unlink(missing_ok=True)
    except OSError:
        # 删不掉也要把失败报出去，别让坏文件被当成迁移成功。
        problem = f"{problem};unlink-failed"
    return ctx.record(
        KIND,
        STATUS_FAILED_VALIDATION,
        source=str(source),
        target=str(target),
        detail=_detail([*notes, f"error:{problem}"]),
    )


def _append(entries: list[MigrationEntry], entry: MigrationEntry | None) -> None:
    if entry is not None:
        entries.append(entry)


def migrate(ctx: MigrationContext) -> list[MigrationEntry]:
    """旧 ``todo_items.json`` → ``feature-data/reminder.todo/todo-slot-0-v2.json``。"""
    directory = ctx.root / "feature-data" / OWNER
    target = directory / f"todo-slot-{SLOT}-v2.json"
    history = directory / f"todo-slot-{SLOT}-legacy-v1.json"
    entries: list[MigrationEntry] = []
    found = False
    for legacy_root in ctx.legacy_roots:
        source = Path(legacy_root) / "todo_items.json"
        if not source.is_file():
            continue
        found = True
        _append(
            entries,
            _migrate_source(ctx, source, target=target, history=history),
        )
    if not found:
        entries.append(ctx.record(KIND, STATUS_NOT_FOUND, target=str(target), detail=_detail()))
    return entries
