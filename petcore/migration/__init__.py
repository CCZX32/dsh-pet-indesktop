"""旧壳数据的全量迁移。

发布入口从 `pet/` 切到 `petcore` 之前，旧壳的数据必须搬过来：全局配置、每宠
档案、活跃宠清单、会话、待办、API 规格与凭据引用。规则见 SPEC「迁移契约」：
原文件先备份、失败绝不覆盖、结果可诊断可回滚。

幂等只认 ``<root>/migration.json`` 里的 ``completed`` 记录，**不认**「目标文件
不存在」——目标文件在第一次启动后就存在了，那样写等于迁移只有一次机会，还会
把用户后来删掉的键当成已迁移。

每个域是一个 ``migrate(ctx) -> list[MigrationEntry]`` 函数，自己决定读哪些旧
文件、怎么备份、写到哪里；本模块只负责顺序、幂等、dry-run、回滚与汇总。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import paths
from ..log import get_logger

logger = get_logger("migration")

MARKER_FILENAME = "migration.json"
MARKER_SCHEMA = 1
BACKUP_DIRNAME = "migration-backup"

STATUS_MIGRATED = "migrated"
STATUS_ALREADY = "already_migrated"
STATUS_SKIPPED = "skipped_invalid"
STATUS_NOT_FOUND = "not_found"
STATUS_UNSUPPORTED = "unsupported"
STATUS_FAILED_BACKUP = "failed_backup"
STATUS_FAILED_WRITE = "failed_write"
STATUS_FAILED_VALIDATION = "failed_validation"
STATUS_ROLLED_BACK = "rolled_back"

#: 一次迁移里出现这些状态就说明数据没搬干净，调用方要看得见。
FAILURE_STATUSES = frozenset(
    {STATUS_FAILED_BACKUP, STATUS_FAILED_WRITE, STATUS_FAILED_VALIDATION, STATUS_UNSUPPORTED}
)


@dataclass(frozen=True)
class MigrationEntry:
    kind: str
    status: str
    source: str = ""
    target: str = ""
    backup: str = ""
    detail: str = ""
    count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "source": self.source,
            "target": self.target,
            "backup": self.backup,
            "detail": self.detail,
            "count": int(self.count),
        }


@dataclass
class MigrationReport:
    root: Path
    legacy_roots: tuple[Path, ...] = ()
    dry_run: bool = False
    entries: list[MigrationEntry] = field(default_factory=list)
    completed: dict[str, str] = field(default_factory=dict)
    restore: list[dict[str, str]] = field(default_factory=list)

    def add(self, entry: MigrationEntry) -> MigrationEntry:
        self.entries.append(entry)
        return entry

    @property
    def failures(self) -> tuple[MigrationEntry, ...]:
        return tuple(entry for entry in self.entries if entry.status in FAILURE_STATUSES)

    @property
    def migrated(self) -> tuple[MigrationEntry, ...]:
        return tuple(entry for entry in self.entries if entry.status == STATUS_MIGRATED)

    def by_kind(self, kind: str) -> tuple[MigrationEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == kind)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "legacy_roots": [str(path) for path in self.legacy_roots],
            "dry_run": bool(self.dry_run),
            "completed": dict(self.completed),
            "counts": {
                status: sum(1 for entry in self.entries if entry.status == status)
                for status in sorted({entry.status for entry in self.entries})
            },
            "entries": [entry.as_dict() for entry in self.entries],
        }


@dataclass
class MigrationContext:
    """域函数拿到的全部能力；写入一律走这里，便于 dry-run、备份与留痕。"""

    root: Path
    legacy_roots: tuple[Path, ...]
    dry_run: bool
    backup_root: Path
    report: MigrationReport | None = None
    pending: list[MigrationEntry] = field(default_factory=list)
    restore: list[dict[str, str]] = field(default_factory=list)

    def record(self, kind: str, status: str, **kwargs: Any) -> MigrationEntry:
        """构造一条结果；域函数负责返回它，这里不直接进报告。"""
        return MigrationEntry(kind=kind, status=status, **kwargs)

    def _auto(self, entry: MigrationEntry) -> MigrationEntry:
        """备份/写入这类内部失败由 ctx 自己记账，避免域函数漏报。"""
        self.pending.append(entry)
        return entry

    def current(self, kind: str) -> str:
        """当前迁移里的「这一域」名字，域函数不用再手写 kind。"""
        return kind

    def backup(self, kind: str, source: Path, *, target: Path | None = None) -> Path | None:
        """复制旧文件到 ``migration-backup``；已存在的不重写。"""
        destination = self.backup_root / f"{kind}-{source.parent.name}-{source.name}"
        if self.dry_run:
            return destination
        try:
            self.backup_root.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(source, destination)
        except OSError as exc:
            self._auto(
                self.record(
                    kind,
                    STATUS_FAILED_BACKUP,
                    source=str(source),
                    target=str(destination),
                    detail=type(exc).__name__,
                )
            )
            return None
        if target is not None:
            self.remember_restore(kind, destination, target)
        return destination

    def remember_restore(self, kind: str, backup: Path, target: Path) -> None:
        # `Path("")` 的字符串是 "."——统一折成空串，回滚才认得「删掉新建文件」。
        text = str(backup)
        record = {
            "kind": kind,
            "backup": "" if text in ("", ".") else text,
            "target": str(target),
        }
        if record not in self.restore:
            self.restore.append(record)

    def write_bytes(self, kind: str, target: Path, payload: bytes) -> bool:
        if self.dry_run:
            return True
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(target.suffix + ".migrating")
            temp.write_bytes(payload)
            os.replace(temp, target)
        except OSError as exc:
            self._auto(
                self.record(kind, STATUS_FAILED_WRITE, target=str(target), detail=type(exc).__name__)
            )
            return False
        return True

    def write_json(self, kind: str, target: Path, payload: Any) -> bool:
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return self.write_bytes(kind, target, text.encode("utf-8"))


def marker_path(root: Path) -> Path:
    return Path(root) / MARKER_FILENAME


def read_marker(root: Path) -> dict[str, Any]:
    try:
        raw = json.loads(marker_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema") != MARKER_SCHEMA:
        return {}
    if not isinstance(raw.get("completed"), dict):
        raw["completed"] = {}
    return raw


def _write_marker(root: Path, report: MigrationReport, restore: list[dict[str, str]]) -> None:
    path = marker_path(root)
    payload = {
        "schema": MARKER_SCHEMA,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed": dict(report.completed),
        "restore": restore,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        logger.warning("migration marker write failed: %s", path)


def _domain_functions() -> tuple[tuple[str, Callable[[MigrationContext], list[MigrationEntry]]], ...]:
    from . import accounts, config_data, sessions, todos

    return (
        ("config", config_data.migrate_config),
        ("slots", config_data.migrate_slots),
        ("active_pets", config_data.migrate_active_pets),
        ("sessions", sessions.migrate),
        ("todos", todos.migrate),
        ("api", accounts.migrate_api),
        ("credentials", accounts.migrate_credentials),
    )


def _resolve_legacy_roots(legacy_root: Path | None) -> tuple[Path, ...]:
    if legacy_root is not None:
        return (Path(legacy_root),)
    return tuple(paths.legacy_data_roots())


def _flush(report: MigrationReport, ctx: MigrationContext, produced) -> list[MigrationEntry]:
    batch = list(ctx.pending) + list(produced or [])
    ctx.pending.clear()
    for entry in batch:
        report.add(entry)
    return batch


def run(
    root: Path,
    *,
    legacy_root: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> MigrationReport:
    """按域顺序跑迁移；已完成的域默认跳过（``force`` 重跑）。"""
    root = Path(root)
    legacy_roots = _resolve_legacy_roots(legacy_root)
    marker = read_marker(root)
    report = MigrationReport(
        root=root,
        legacy_roots=legacy_roots,
        dry_run=bool(dry_run),
        completed=dict(marker.get("completed") or {}),
        restore=list(marker.get("restore") or []),
    )
    ctx = MigrationContext(
        root=root,
        legacy_roots=legacy_roots,
        dry_run=bool(dry_run),
        backup_root=root / BACKUP_DIRNAME,
        report=report,
    )
    if not legacy_roots:
        report.add(MigrationEntry("all", STATUS_NOT_FOUND, detail="没有发现旧壳数据目录"))
        return report
    try:
        domains = _domain_functions()
    except ImportError as exc:
        report.add(
            MigrationEntry("all", STATUS_UNSUPPORTED, detail=f"domain-module-missing:{exc.name}")
        )
        return report
    for kind, migrate in domains:
        if not force and kind in report.completed:
            report.add(MigrationEntry(kind, STATUS_ALREADY, detail="marker-completed"))
            continue
        try:
            produced = migrate(ctx)
        except Exception as exc:  # noqa: BLE001 - 单个域失败不能拖垮其它域
            logger.exception("migration domain failed: %s", kind)
            ctx.pending.clear()
            report.add(MigrationEntry(kind, STATUS_FAILED_VALIDATION, detail=type(exc).__name__))
            continue
        batch = _flush(report, ctx, produced)
        # 域内只要有一条失败就**不能**封存 completed：否则下一轮直接报
        # already_migrated，失败的那部分永远补不上（审计 AUD-09）。
        blocked = any(entry.status in FAILURE_STATUSES for entry in batch)
        if (
            not dry_run
            and not blocked
            and any(entry.status == STATUS_MIGRATED for entry in batch)
        ):
            report.completed[kind] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not dry_run:
        # 回滚映射由 ctx 累积在独立列表里，必须同步进报告才会写进标记。
        for item in ctx.restore:
            if item not in report.restore:
                report.restore.append(item)
        _write_marker(root, report, report.restore)
    return report


def plan(root: Path, *, legacy_root: Path | None = None) -> MigrationReport:
    """只读预演：不写任何文件，也不标记完成。"""
    return run(root, legacy_root=legacy_root, dry_run=True, force=True)


def rollback(root: Path) -> MigrationReport:
    """按标记里的 restore 映射把旧文件放回目标位置。

    安全口径（审计 AUD-06）：

    - 覆盖/删除前先把**当前**目标留一份 ``<target>.pre-rollback-<时间戳>``；
    - 同一目标有多条记录时只按**最早**那条恢复——三条记录依次覆盖同一个
      ``config.json`` 时，只应用最后一条会停在「迁移到一半」的中间态；
    - ``not_found`` / ``failed_write`` 都计失败；只有全部成功才删标记，否则
      restore 映射会随标记一起消失，回滚既不可重试也无法追溯。
    """
    root = Path(root)
    marker = read_marker(root)
    report = MigrationReport(root=root, dry_run=False)
    restore = [item for item in marker.get("restore") or [] if isinstance(item, dict)]
    if not restore:
        report.add(MigrationEntry("all", STATUS_NOT_FOUND, detail="没有可回滚的迁移记录"))
        return report
    ordered: list[dict] = []
    seen_targets: set[str] = set()
    failures = 0
    for item in restore:
        target_text = str(item.get("target") or "")
        if not target_text:
            failures += 1
            report.add(
                MigrationEntry(
                    str(item.get("kind") or "all"),
                    STATUS_NOT_FOUND,
                    backup=str(item.get("backup") or ""),
                )
            )
            continue
        if target_text in seen_targets:
            continue
        seen_targets.add(target_text)
        ordered.append(item)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for item in ordered:
        kind = str(item.get("kind") or "all")
        backup_text = str(item.get("backup") or "")
        target = Path(str(item.get("target")))
        if target.is_dir():
            failures += 1
            report.add(
                MigrationEntry(
                    kind, STATUS_FAILED_WRITE, target=str(target), detail="target-is-directory"
                )
            )
            continue
        preserved = _preserve_before_rollback(target, stamp)
        note = f"pre-rollback:{preserved}" if preserved else ""
        try:
            if not backup_text:
                # 迁移时目标文件原本不存在：回滚就是删掉它（当前内容已留档）。
                target.unlink(missing_ok=True)
                report.add(
                    MigrationEntry(
                        kind,
                        STATUS_ROLLED_BACK,
                        target=str(target),
                        detail=";".join(part for part in ("removed", note) if part),
                    )
                )
                continue
            backup = Path(backup_text)
            if not backup.is_file():
                failures += 1
                report.add(
                    MigrationEntry(
                        kind,
                        STATUS_NOT_FOUND,
                        backup=backup_text,
                        target=str(target),
                        detail=note,
                    )
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        except OSError as exc:
            failures += 1
            report.add(
                MigrationEntry(
                    kind,
                    STATUS_FAILED_WRITE,
                    backup=backup_text,
                    target=str(target),
                    detail=type(exc).__name__,
                )
            )
            continue
        report.add(
            MigrationEntry(
                kind,
                STATUS_ROLLED_BACK,
                backup=backup_text,
                target=str(target),
                detail=";".join(part for part in ("restored", note) if part),
            )
        )
    if failures:
        report.add(
            MigrationEntry("all", STATUS_FAILED_WRITE, detail=f"rollback-incomplete:{failures}")
        )
        return report
    try:
        marker_path(root).unlink(missing_ok=True)
    except OSError:
        logger.warning("migration marker remove failed: %s", marker_path(root))
    return report


def _preserve_before_rollback(target: Path, stamp: str) -> str:
    """回滚前给当前文件留一份副本；失败也要继续（只是报告里没有副本路径）。"""
    if not target.is_file():
        return ""
    destination = target.with_name(f"{target.name}.pre-rollback-{stamp}")
    try:
        shutil.copy2(target, destination)
    except OSError:
        logger.warning("rollback: cannot preserve %s", target, exc_info=True)
        return ""
    return str(destination)


__all__ = [
    "FAILURE_STATUSES",
    "MARKER_FILENAME",
    "MigrationContext",
    "MigrationEntry",
    "MigrationReport",
    "plan",
    "read_marker",
    "rollback",
    "run",
]
