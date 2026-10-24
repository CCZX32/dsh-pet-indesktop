"""Versioned per-pet documents; migration never edits the old configuration."""
from copy import deepcopy
from pathlib import Path

from petcore.mods.json_store import read_json, write_json
from .model import new_state, validate


class TodoStore:
    def __init__(self, root, slot, legacy=()):
        if not isinstance(slot, int) or not 0 <= slot <= 128:
            raise ValueError("invalid pet slot")
        self.path = Path(root) / f"todo-slot-{slot}-v2.json"
        if self.path.exists():
            self.state = validate(read_json(self.path))
        else:
            backup = Path(root) / f"todo-slot-{slot}-legacy-v1.json"
            if backup.exists():
                original = read_json(backup)
                if not isinstance(original, list) or not all(isinstance(x, str) for x in original):
                    raise ValueError("invalid migration backup; preserved")
            else:
                original = [x for x in legacy if isinstance(x, str)]
                write_json(backup, original)
            state = new_state(original)
            write_json(self.path, state)
            self.state = state

    def save(self, state):
        validate(state)
        if state != self.state:
            write_json(self.path, state)
            self.state = deepcopy(state)
