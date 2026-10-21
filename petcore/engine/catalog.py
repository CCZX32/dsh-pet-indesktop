from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from ..contracts.content import AnimationSpec
from .enums import AnimatType, GraphType, ModeType

_MODE_FALLBACK: dict[ModeType, tuple[ModeType, ...]] = {
    ModeType.HAPPY: (ModeType.HAPPY, ModeType.NOMAL, ModeType.POOR_CONDITION),
    ModeType.NOMAL: (ModeType.NOMAL, ModeType.HAPPY, ModeType.POOR_CONDITION),
    ModeType.POOR_CONDITION: (ModeType.POOR_CONDITION, ModeType.NOMAL, ModeType.HAPPY),
    ModeType.ILL: (ModeType.ILL,),
}


@dataclass
class GraphCatalog:
    animations: list[AnimationSpec]
    rng: random.Random

    def __init__(
        self, animations: Iterable[AnimationSpec] = (), rng: random.Random | None = None
    ):
        self.animations = []
        self.rng = rng or random.Random()
        self._by_name: dict[str, dict[AnimatType, dict[ModeType, list[AnimationSpec]]]] = {}
        self._names_by_graph: dict[GraphType, list[str]] = {}
        for spec in animations:
            self.add(spec)

    def add(self, spec: AnimationSpec) -> None:
        self.animations.append(spec)
        modes = self._by_name.setdefault(spec.name, {}).setdefault(spec.animat, {})
        modes.setdefault(spec.mode, []).append(spec)
        names = self._names_by_graph.setdefault(spec.graph, [])
        if spec.name not in names:
            names.append(spec.name)

    def add_many(self, specs: Iterable[AnimationSpec]) -> None:
        for spec in specs:
            self.add(spec)

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    def names_for(self, graph: GraphType) -> tuple[str, ...]:
        return tuple(self._names_by_graph.get(graph, ()))

    def specs_for(self, graph: GraphType) -> tuple[AnimationSpec, ...]:
        wanted = set(self._names_by_graph.get(graph, ()))
        return tuple(spec for spec in self.animations if spec.name in wanted)

    def specs_for_event(self, group: str) -> tuple[AnimationSpec, ...]:
        key = str(group)
        return tuple(
            spec
            for spec in self.animations
            if spec.graph is GraphType.EVENT and spec.event_group == key
        )

    def event_groups(self) -> tuple[str, ...]:
        found: list[str] = []
        for spec in self.animations:
            if spec.graph is GraphType.EVENT and spec.event_group and spec.event_group not in found:
                found.append(spec.event_group)
        return tuple(found)

    def event_names(self, group: str) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs_for_event(group))

    def has(self, name: str) -> bool:
        return name in self._by_name

    def find(
        self, name: str, animat: AnimatType, mode: ModeType = ModeType.NOMAL
    ) -> AnimationSpec | None:
        modes = self._by_name.get(name, {}).get(animat)
        if not modes:
            return None
        for candidate in _MODE_FALLBACK.get(mode, (mode,)):
            variants = modes.get(candidate)
            if variants:
                return self.rng.choice(variants)
        return None

    def find_for(
        self, graph: GraphType, animat: AnimatType, mode: ModeType = ModeType.NOMAL
    ) -> AnimationSpec | None:
        names = list(self._names_by_graph.get(graph, ()))
        if not names:
            return None
        self.rng.shuffle(names)
        for name in names:
            spec = self.find(name, animat, mode)
            if spec is not None:
                return spec
        return None

    def find_name(self, graph: GraphType) -> str | None:
        names = self._names_by_graph.get(graph)
        if not names:
            return None
        return self.rng.choice(names)
