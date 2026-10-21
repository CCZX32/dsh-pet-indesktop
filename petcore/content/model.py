from __future__ import annotations

from ..contracts.content import AnimationSpec, CharacterSpec
from ..engine.catalog import GraphCatalog


def build_catalog(character: CharacterSpec) -> GraphCatalog:
    return GraphCatalog(character.animations)


__all__ = ["AnimationSpec", "CharacterSpec", "build_catalog"]
