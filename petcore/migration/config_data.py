"""全局配置、每宠档案与活跃宠清单的迁移。

口径：

- **只补缺，不覆盖**——目标里已有的键一律保留，用户后来改过的值优先；
- 旧壳的 ``config-slot-0.json`` 是主宠档案，petcore 里主宠与全局共用
  ``config.json``，所以 slot0 的键按「只补缺」并进全局文件；
- 子宠 ``config-slot-N`` / ``config-pet-N``（N≥1）写 ``config-pet-N.json``；
- 活跃集合 ``overlay-active-pets.json`` 只在目标还是默认 ``[0]`` 时采纳。

所有写入都先备份目标文件；目标原本不存在时，回滚靠标记里的空 backup 记录
「删掉新建文件」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import _map_legacy_data, legacy_unmapped_keys
from . import (
    STATUS_ALREADY,
    STATUS_FAILED_VALIDATION,
    STATUS_MIGRATED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
    MigrationContext,
    MigrationEntry,
)

MAX_LEGACY_SLOTS = 16


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _current_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_object(path) or {}


def _missing_keys(current: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in mapped.items()
        if key not in current and value is not None
    }


def _merge_file(
    ctx: MigrationContext,
    kind: str,
    *,
    source: Path,
    target: Path,
    mapped: dict[str, Any],
    dropped: list[str] | None = None,
) -> MigrationEntry | None:
    current = _current_object(target)
    added = _missing_keys(current, mapped)
    details: list[str] = []
    if dropped:
        # 旧壳里有、但别名表覆盖不到的键：如实点名，别让「报告全绿 = 什么都没丢」
        # 变成一句假话（审计 AUD-08）。
        details.append(f"dropped:{len(dropped)}:" + ",".join(dropped[:8]))
    if not added:
        return ctx.record(
            kind,
            STATUS_ALREADY,
            source=str(source),
            target=str(target),
            detail=";".join(["no-missing-keys", *details]),
        )
    details.insert(0, "keys:" + ",".join(sorted(added)[:12]))
    detail = ";".join(details)
    if ctx.dry_run:
        return ctx.record(
            kind,
            STATUS_MIGRATED,
            source=str(source),
            target=str(target),
            detail="would-migrate:" + detail,
            count=len(added),
        )
    if target.exists():
        if ctx.backup(kind, target, target=target) is None:
            return None
    else:
        ctx.remember_restore(kind, Path(""), target)
    # 直接写合并后的原始字典，不走 `Config.save()`：后者会把全部 DEFAULTS 落盘，
    # 让「只补缺」在第二个域里失效（每个键都已存在）。
    if not ctx.write_json(kind, target, {**current, **added}):
        return None
    return ctx.record(
        kind,
        STATUS_MIGRATED,
        source=str(source),
        target=str(target),
        detail=detail,
        count=len(added),
    )


def _append(entries: list[MigrationEntry], entry: MigrationEntry | None) -> None:
    if entry is not None:
        entries.append(entry)


def migrate_config(ctx: MigrationContext) -> list[MigrationEntry]:
    entries: list[MigrationEntry] = []
    target = ctx.root / "config.json"
    found = False
    for legacy_root in ctx.legacy_roots:
        source = legacy_root / "config.json"
        if not source.is_file():
            continue
        found = True
        raw = _read_object(source)
        if raw is None:
            entries.append(
                ctx.record("config", STATUS_SKIPPED, source=str(source), detail="invalid-json")
            )
            continue
        mapped = _map_legacy_data(raw)
        if not mapped:
            entries.append(
                ctx.record(
                    "config", STATUS_FAILED_VALIDATION, source=str(source), detail="no-supported-keys"
                )
            )
            continue
        _append(
            entries,
            _merge_file(
                ctx,
                "config",
                source=source,
                target=target,
                mapped=mapped,
                dropped=legacy_unmapped_keys(raw),
            ),
        )
    if not found and not entries:
        entries.append(ctx.record("config", STATUS_NOT_FOUND, target=str(target)))
    return entries


def _slot_sources(legacy_root: Path) -> list[tuple[int, Path]]:
    sources: list[tuple[int, Path]] = []
    for pattern in ("config-slot-*.json", "config-pet-*.json"):
        for candidate in sorted(legacy_root.glob(pattern)):
            suffix = candidate.stem.rsplit("-", 1)[-1]
            sources.append((int(suffix) if suffix.isdigit() else -1, candidate))
    return sources


def migrate_slots(ctx: MigrationContext) -> list[MigrationEntry]:
    entries: list[MigrationEntry] = []
    global_target = ctx.root / "config.json"
    for legacy_root in ctx.legacy_roots:
        for slot, source in _slot_sources(legacy_root):
            if slot < 0 or slot >= MAX_LEGACY_SLOTS:
                entries.append(
                    ctx.record("slots", STATUS_SKIPPED, source=str(source), detail="invalid-slot")
                )
                continue
            raw = _read_object(source)
            if raw is None:
                entries.append(
                    ctx.record("slots", STATUS_SKIPPED, source=str(source), detail="invalid-json")
                )
                continue
            mapped = _map_legacy_data(raw)
            if not mapped:
                entries.append(
                    ctx.record(
                        "slots", STATUS_FAILED_VALIDATION, source=str(source), detail="no-supported-keys"
                    )
                )
                continue
            # slot0 是主宠：petcore 里主宠与全局共用 config.json。
            target = global_target if slot == 0 else ctx.root / f"config-pet-{slot}.json"
            _append(
                entries,
                _merge_file(
                    ctx,
                    "slots",
                    source=source,
                    target=target,
                    mapped=mapped,
                    dropped=legacy_unmapped_keys(raw),
                ),
            )
    if not entries:
        entries.append(ctx.record("slots", STATUS_NOT_FOUND, target=str(ctx.root)))
    return entries


def migrate_active_pets(ctx: MigrationContext) -> list[MigrationEntry]:
    entries: list[MigrationEntry] = []
    target = ctx.root / "config.json"
    current = _current_object(target)
    active = current.get("active_pets")
    for legacy_root in ctx.legacy_roots:
        source = legacy_root / "overlay-active-pets.json"
        if not source.is_file():
            continue
        raw = _read_object(source)
        if raw is None:
            entries.append(
                ctx.record("active_pets", STATUS_SKIPPED, source=str(source), detail="invalid-json")
            )
            continue
        slots = raw.get("slots")
        if not isinstance(slots, list):
            entries.append(
                ctx.record("active_pets", STATUS_SKIPPED, source=str(source), detail="slots-not-list")
            )
            continue
        cleaned = sorted(
            {
                int(value)
                for value in slots
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            }
        )
        if not cleaned:
            entries.append(
                ctx.record(
                    "active_pets", STATUS_SKIPPED, source=str(source), detail="empty-active-set"
                )
            )
            continue
        if isinstance(active, list) and active not in ([], [0]):
            entries.append(
                ctx.record(
                    "active_pets",
                    STATUS_ALREADY,
                    source=str(source),
                    target=str(target),
                    detail="target-has-active-pets",
                )
            )
            continue
        _append(
            entries,
            _merge_file(
                ctx,
                "active_pets",
                source=source,
                target=target,
                mapped={"active_pets": cleaned},
            ),
        )
        break
    if not entries:
        entries.append(ctx.record("active_pets", STATUS_NOT_FOUND, target=str(target)))
    return entries
