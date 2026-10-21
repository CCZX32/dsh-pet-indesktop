from __future__ import annotations

from ..contracts.content import AnimationSpec
from .catalog import GraphCatalog
from .enums import AnimatType, GraphType, ModeType


class AnimationPlayer:
    def __init__(self, catalog: GraphCatalog):
        self.catalog = catalog
        self.current: AnimationSpec | None = None

    def play(
        self,
        graph: GraphType | None = None,
        *,
        name: str | None = None,
        animat: AnimatType | None = None,
        mode: ModeType = ModeType.NOMAL,
    ) -> AnimationSpec | None:
        spec: AnimationSpec | None = None
        if name is not None:
            if animat is not None:
                spec = self.catalog.find(name, animat, mode)
            else:
                for candidate in (
                    AnimatType.SINGLE,
                    AnimatType.B_LOOP,
                    AnimatType.A_START,
                    AnimatType.C_END,
                ):
                    spec = self.catalog.find(name, candidate, mode)
                    if spec is not None:
                        break
        elif graph is not None and animat is not None:
            spec = self.catalog.find_for(graph, animat, mode)
        self.current = spec
        return spec

    def advance(self) -> AnimationSpec | None:
        spec = self.current
        if spec is None:
            return None
        if spec.animat is AnimatType.SINGLE:
            self.current = None
            return None
        if spec.animat is AnimatType.A_START:
            nxt = self.catalog.find(spec.name, AnimatType.B_LOOP, spec.mode)
            if nxt is None:
                nxt = self.catalog.find(spec.name, AnimatType.C_END, spec.mode)
        elif spec.animat is AnimatType.B_LOOP:
            if spec.loop:
                nxt = spec
            else:
                nxt = self.catalog.find(spec.name, AnimatType.C_END, spec.mode)
        else:
            nxt = None
        self.current = nxt
        return nxt

    def reset(self) -> None:
        self.current = None
