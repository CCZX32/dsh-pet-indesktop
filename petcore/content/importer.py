from __future__ import annotations

import shutil
from pathlib import Path

from .character_pack import build_character_pack
from ..mods.install import install


def install_character_source(
    source: Path,
    root: Path,
    *,
    character_id: str | None = None,
    name: str | None = None,
) -> tuple[bool, str, str | None]:
    """Build and install a directory character pack for the settings UI."""
    source = Path(source)
    root = Path(root)
    import_root = root / ".character-import"
    import_root.mkdir(parents=True, exist_ok=True)
    requested = str(character_id or source.name).strip()
    target = import_root / f"character.{requested}"
    if target.exists():
        shutil.rmtree(target)
    try:
        ok, message = build_character_pack(
            source, target, character_id=requested, name=name, link=False
        )
        if not ok:
            return False, message, None
        ok, message = install(target, root, force=True)
        return ok, message, f"character.{requested}" if ok else None
    finally:
        shutil.rmtree(target, ignore_errors=True)
        try:
            import_root.rmdir()
        except OSError:
            pass
