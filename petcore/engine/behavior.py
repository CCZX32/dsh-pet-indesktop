from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Sequence

from ..contracts.content import AnimationSpec
from .catalog import GraphCatalog
from .enums import AnimatType, GraphType

KIND_IDLE = "idle"
KIND_TURN = "turn"
KIND_ACT = "act"
KIND_MOVE = "move"

#: 待机 / 转向 / 随机动作 / 漫游 的默认权重（主分支 30/10/40/20 的累计阈值口径）。
DEFAULT_WEIGHTS: tuple[float, float, float, float] = (0.30, 0.10, 0.40, 0.20)

Weights = tuple[float, float, float, float]


def normalize_weights(idle, turn, act, move) -> Weights:
    """四项权重归一化：负数/NaN/非数字都当 0；全 0 回默认。"""
    values: list[float] = []
    for value in (idle, turn, act, move):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = 0.0
        if number != number or number < 0.0:
            number = 0.0
        values.append(number)
    total = sum(values)
    if total <= 0.0:
        return DEFAULT_WEIGHTS
    return tuple(value / total for value in values)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    spec: AnimationSpec


class BehaviorDirector:
    def __init__(
        self,
        catalog: GraphCatalog,
        rng: random.Random | None = None,
        *,
        weights: Sequence[float] | None = None,
        weights_provider: Callable[[], Sequence[float]] | None = None,
    ):
        self.catalog = catalog
        self.rng = rng or catalog.rng
        self._weights: Weights = (
            normalize_weights(*weights) if weights is not None else DEFAULT_WEIGHTS
        )
        self._weights_provider = weights_provider

    @property
    def weights(self) -> Weights:
        provider = self._weights_provider
        if provider is None:
            return self._weights
        try:
            values = tuple(provider())
        except Exception:
            return DEFAULT_WEIGHTS
        if len(values) != 4:
            return DEFAULT_WEIGHTS
        return normalize_weights(*values)

    def set_weights(self, weights: Sequence[float]) -> None:
        self._weights = normalize_weights(*tuple(weights)[:4])
        self._weights_provider = None

    def idle(self) -> Action | None:
        spec = self.catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP)
        return Action(KIND_IDLE, spec) if spec is not None else None

    def turn(self) -> Action | None:
        candidates = [
            spec
            for spec in self.catalog.specs_for(GraphType.MOVE)
            if spec.locate == "in_place"
        ]
        if not candidates:
            return None
        return Action(KIND_TURN, self.rng.choice(candidates))

    def act(self) -> Action | None:
        spec = self.catalog.find_for(GraphType.DEFAULT, AnimatType.SINGLE)
        return Action(KIND_ACT, spec) if spec is not None else None

    def move(self) -> Action | None:
        candidates = [
            spec
            for spec in self.catalog.specs_for(GraphType.MOVE)
            if spec.locate != "in_place"
        ]
        if not candidates:
            return None
        return Action(KIND_MOVE, self.rng.choice(candidates))

    def choose(self) -> Action | None:
        idle, turn, _act, _move = self.weights
        roll = self.rng.random()
        p_turn = idle + turn
        p_act = p_turn + _act
        if roll < idle:
            order = (self.idle, self.turn, self.act, self.move)
        elif roll < p_turn:
            order = (self.turn, self.idle, self.act, self.move)
        elif roll < p_act:
            order = (self.act, self.idle, self.turn, self.move)
        else:
            order = (self.move, self.idle, self.turn, self.act)
        for factory in order:
            action = factory()
            if action is not None:
                return action
        return None
