"""Versioned per-pet documents; migration never edits the old configuration."""
from copy import deepcopy
from pathlib import Path

MIGRATION_STATUSES = frozenset({
    "not_needed", "migrated", "already_migrated", "skipped_invalid",
    "failed_backup", "failed_write", "failed_validation",
})

from petcore.mods.json_store import read_json, write_json
from .model import new_state, validate


class TodoStore:
    def __init__(self, root, slot, legacy=()):
        if not isinstance(slot, int) or not 0 <= slot <= 128:
            raise ValueError("invalid pet slot")
        self.root = Path(root)
        self.path = self.root / f"todo-slot-{slot}-v2.json"
        self.diagnostics: list[dict[str, str]] = []
        self.migration_status = "not_needed"
        if self.path.exists():
            try:
                self.state = validate(read_json(self.path))
            except (OSError, ValueError, TypeError) as exc:
                self.migration_status = "failed_validation"
                self._diagnose("failed_validation", self.path, exc)
                raise ValueError("failed_validation: invalid todo document; original file preserved") from exc
            self.migration_status = "already_migrated"
            self._diagnose("already_migrated", self.path, "v2-present")
        else:
            backup = self.root / f"todo-slot-{slot}-legacy-v1.json"
            try:
                if backup.exists():
                    original = read_json(backup)
                    if not isinstance(original, list) or not all(isinstance(x, str) for x in original):
                        raise ValueError("invalid migration backup; preserved")
                else:
                    original = [x for x in legacy if isinstance(x, str)]
                    write_json(backup, original)
            except OSError as exc:
                self.migration_status = "failed_backup"
                self._diagnose("failed_backup", backup, exc)
                raise OSError("failed_backup: todo migration source was not backed up") from exc
            except (ValueError, TypeError) as exc:
                self.migration_status = "skipped_invalid"
                self._diagnose("skipped_invalid", backup, exc)
                raise
            state = new_state(original)
            try:
                write_json(self.path, state)
            except OSError as exc:
                self.migration_status = "failed_write"
                self._diagnose("failed_write", self.path, exc)
                raise OSError("failed_write: todo v2 document was not written") from exc
            self.state = state
            self.migration_status = "migrated"
            self._diagnose("migrated", self.path, "legacy-preserved")

    def _diagnose(self, status, path, error):
        if status not in MIGRATION_STATUSES:
            raise ValueError(f"unknown migration status: {status}")
        self.diagnostics.append({"status": status, "path": str(path), "error": str(error)})

    def save(self, state):
        try:
            validate(state)
        except (ValueError, TypeError) as exc:
            self._diagnose("failed_validation", self.path, exc)
            raise
        if state != self.state:
            try:
                write_json(self.path, state)
            except OSError as exc:
                self._diagnose("failed_write", self.path, exc)
                raise
            self.state = deepcopy(state)
