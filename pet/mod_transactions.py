# -*- coding: utf-8 -*-
"""资源包安装/激活/删除的事务日志。零 Qt。

本仓库的启用态由**目录位置**表达（``characters/`` ↔ ``mod-disabled/`` ↔
``mod-versions/<id>/<version>/``），没有上游 ``active.json`` / ``previous.json``
指针；因此日志记录的是目录搬移的四个阶段，而不是指针快照：

``prepared`` → ``version_removed`` → ``swapped`` → ``committed``
    install / activate（含回滚）。旧版已移入保留区、新版尚未落位时崩溃，恢复到
    操作前；新版已落位但未提交时，恢复时先自检，通过则补提交、失败则换回旧版。

``prepared`` → ``deleted`` → ``committed``
    remove。删除本身幂等；恢复时对仍存在的目标再删一次。

日志放在 ``mod-staging/transactions/<operation_id>.json``，原子写。恢复逻辑在
:class:`pet.mod_management.ResourceMods` 里（只有它知道根目录边界与包校验规则）；
本模块只负责记录的形状、读写与阶段合法性。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .feature_state_io import safe_path

TRANSACTIONS_DIRNAME = "transactions"

_INSTALL_PHASES = ("prepared", "version_removed", "swapped", "committed")
_REMOVE_PHASES = ("prepared", "deleted", "committed")
_PHASES = {"install": _INSTALL_PHASES, "activate": _INSTALL_PHASES, "remove": _REMOVE_PHASES}


class JournalError(ValueError):
    """The journal on disk is malformed or names an unsupported operation."""


@dataclass(frozen=True)
class JournalRecord:
    operation_id: str
    kind: str
    character_id: str
    phase: str
    target: str
    from_version: str
    to_version: str
    retained: str | None = None
    incoming: str | None = None
    targets: tuple[str, ...] = ()
    created_at: str = ""

    def document(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "character_id": self.character_id,
            "phase": self.phase,
            "target": self.target,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "retained": self.retained,
            "incoming": self.incoming,
            "targets": list(self.targets),
            "created_at": self.created_at,
        }

    @classmethod
    def from_document(cls, value: Any) -> JournalRecord:
        if not isinstance(value, dict):
            raise JournalError("journal_not_object")
        operation_id = value.get("operation_id")
        kind = value.get("kind")
        phase = value.get("phase")
        character_id = value.get("character_id")
        target = value.get("target")
        from_version = value.get("from_version")
        to_version = value.get("to_version")
        retained = value.get("retained")
        incoming = value.get("incoming")
        created_at = value.get("created_at")
        targets = value.get("targets", [])
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or kind not in _PHASES
            or phase not in _PHASES[kind]
            or not isinstance(character_id, str)
            or not isinstance(target, str)
            or not target
            or not isinstance(from_version, str)
            or not isinstance(to_version, str)
            or (retained is not None and not isinstance(retained, str))
            or (incoming is not None and not isinstance(incoming, str))
            or not isinstance(created_at, str)
            or not isinstance(targets, list)
            or not all(isinstance(item, str) and item for item in targets)
        ):
            raise JournalError("journal_invalid")
        return cls(
            operation_id=operation_id,
            kind=kind,
            character_id=character_id,
            phase=phase,
            target=target,
            from_version=from_version,
            to_version=to_version,
            retained=retained,
            incoming=incoming,
            targets=tuple(targets),
            created_at=created_at,
        )


def _write_atomic(path: Path, record: JournalRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(record.document(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ModJournal:
    """One journal directory; callers own the data-root boundary checks."""

    def __init__(self, staging_root: Path) -> None:
        self.root = Path(staging_root) / TRANSACTIONS_DIRNAME

    def _path(self, operation_id: str) -> Path:
        target = self.root / f"{operation_id}.json"
        safe_path(target)
        return target

    def begin(
        self,
        *,
        kind: str,
        character_id: str,
        target: Path,
        from_version: str,
        to_version: str,
        retained: Path | None = None,
        incoming: Path | None = None,
        targets: Iterable[Path] = (),
    ) -> JournalRecord:
        if kind not in _PHASES:
            raise JournalError("journal_kind_invalid")
        record = JournalRecord(
            operation_id=uuid4().hex,
            kind=kind,
            character_id=character_id,
            phase="prepared",
            target=str(target),
            from_version=from_version,
            to_version=to_version,
            retained=None if retained is None else str(retained),
            incoming=None if incoming is None else str(incoming),
            targets=tuple(str(item) for item in targets),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        _write_atomic(self._path(record.operation_id), record)
        return record

    def advance(self, record: JournalRecord, phase: str) -> JournalRecord:
        if phase not in _PHASES[record.kind]:
            raise JournalError("journal_phase_invalid")
        updated = replace(record, phase=phase)
        _write_atomic(self._path(record.operation_id), updated)
        return updated

    def finish(self, record: JournalRecord) -> None:
        self._path(record.operation_id).unlink(missing_ok=True)

    def records(self) -> list[JournalRecord]:
        if not self.root.is_dir():
            return []
        found: list[JournalRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                safe_path(path)
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                raise JournalError(f"journal_unreadable:{path.name}") from None
            record = JournalRecord.from_document(document)
            if record.operation_id != path.stem:
                raise JournalError(f"journal_identity_conflict:{path.name}")
            found.append(record)
        return found


__all__ = [
    "JournalError",
    "JournalRecord",
    "ModJournal",
    "TRANSACTIONS_DIRNAME",
]
