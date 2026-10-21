from __future__ import annotations

from pathlib import Path

from .. import paths
from .character_pack import build_character_pack


def pack_legacy(
    character_id: str,
    out: Path,
    *,
    link: bool = True,
    source_root: Path | None = None,
) -> tuple[bool, str]:
    source = (Path(source_root) if source_root else paths.legacy_characters_root()) / character_id
    return build_character_pack(
        source,
        out,
        character_id=character_id,
        link=link,
    )
