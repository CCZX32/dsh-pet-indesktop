from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import paths
from ..log import get_logger

SCHEMA_VERSION = 1

_logger = get_logger("mods.state")


def _state_path(root: Path) -> Path:
    return paths.mods_state_path(Path(root))


def load_disabled(root: Path) -> set[str]:
    path = _state_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as exc:
        _logger.warning("mods state unreadable, treating all mods as enabled: %s", exc)
        return set()
    if not isinstance(raw, dict):
        _logger.warning("mods state must be an object, treating all mods as enabled")
        return set()
    if raw.get("schema") != SCHEMA_VERSION:
        _logger.warning("mods state schema %r is unknown; reading anyway", raw.get("schema"))
    disabled = raw.get("disabled")
    if not isinstance(disabled, list):
        _logger.warning("mods state disabled list is invalid, treating all mods as enabled")
        return set()
    return {item for item in disabled if isinstance(item, str) and item}


def _write_disabled(root: Path, disabled: set[str]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"schema": SCHEMA_VERSION, "disabled": sorted(disabled)},
        ensure_ascii=False,
        indent=2,
    )
    handle, tmp_name = tempfile.mkstemp(prefix="mods-state.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def set_enabled(root: Path, mod_id: str, enabled: bool) -> None:
    disabled = load_disabled(root)
    if enabled:
        disabled.discard(mod_id)
    else:
        disabled.add(mod_id)
    _write_disabled(root, disabled)


def clear(root: Path, mod_id: str) -> None:
    """卸载后清掉停用记录，避免重装同名包继承旧的「停用」状态。"""
    disabled = load_disabled(root)
    if mod_id in disabled:
        disabled.discard(mod_id)
        _write_disabled(root, disabled)


def is_enabled(root: Path, mod_id: str) -> bool:
    return mod_id not in load_disabled(root)
