from __future__ import annotations

from pathlib import Path

from ..contracts.content import CharacterSpec
from ..mods.loader import LoadResult, load_mods
from .legacy import load_all
from .modcontent import build_character


def collect_characters(
    *,
    root: Path,
    mod_dirs,
    frameseq_mode: str = "auto",
    allow_feature_mods: bool = False,
) -> tuple[list[CharacterSpec], LoadResult]:
    specs: dict[str, CharacterSpec] = {}
    for spec in load_all(frameseq_mode=frameseq_mode):
        specs[spec.id] = spec

    result = load_mods(root, tuple(mod_dirs), allow_feature_mods=allow_feature_mods)
    for entry in result.contents:
        if entry.kind != "character":
            continue
        data = entry.data if isinstance(entry.data, dict) else {}
        spec = build_character(
            data,
            Path(entry.path),
            owner=entry.owner,
            character_id=entry.id,
            display_name=str(data.get("name") or entry.id),
            frameseq_mode=frameseq_mode,
        )
        if spec is not None:
            specs[spec.id] = spec

    if not specs:
        specs["fallback"] = CharacterSpec(
            id="fallback",
            name="Fallback",
            root=root,
            media_kind="none",
            animations=(),
            owner="core",
        )
    return list(specs.values()), result
