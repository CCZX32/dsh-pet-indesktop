from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..contracts.content import AnimationSpec
from .catalog import GraphCatalog
from .enums import AnimatType, GraphType


HEAD_PAT_DEFAULT_MODE = "default_click"
HEAD_PAT_CUSTOM_MODE = "custom"
HEAD_PAT_ALL_MODE = "all_single"
HEAD_PAT_MODES = frozenset(
    {HEAD_PAT_DEFAULT_MODE, HEAD_PAT_CUSTOM_MODE, HEAD_PAT_ALL_MODE}
)

MIN_SEGMENT_DISTANCE = 4.0
MIN_TOTAL_DISTANCE = 14.0
REVERSAL_DOT_THRESHOLD = -0.25
MAX_PATH_AGE_SECONDS = 1.2
COOLDOWN_SECONDS = 0.65


@dataclass(slots=True)
class HeadPatTracker:
    """Detect a short back-and-forth cursor gesture inside the head box."""

    min_segment_distance: float = MIN_SEGMENT_DISTANCE
    min_total_distance: float = MIN_TOTAL_DISTANCE
    reversal_dot_threshold: float = REVERSAL_DOT_THRESHOLD
    max_path_age: float = MAX_PATH_AGE_SECONDS
    cooldown: float = COOLDOWN_SECONDS
    _last_point: tuple[float, float] | None = field(default=None, init=False)
    _last_direction: tuple[float, float] | None = field(default=None, init=False)
    _total_distance: float = field(default=0.0, init=False)
    _path_started_at: float | None = field(default=None, init=False)
    _cooldown_until: float = field(default=0.0, init=False)
    _reversals: int = field(default=0, init=False)

    def reset(self) -> None:
        self._last_point = None
        self._last_direction = None
        self._total_distance = 0.0
        self._path_started_at = None
        self._reversals = 0

    def update(
        self,
        point: tuple[float, float],
        *,
        inside_head: bool,
        now: float,
        eligible: bool,
    ) -> bool:
        if not inside_head or not eligible:
            self.reset()
            return False

        current = (float(point[0]), float(point[1]))
        timestamp = float(now)
        if timestamp < self._cooldown_until:
            self.reset()
            self._last_point = current
            self._path_started_at = timestamp
            return False

        previous = self._last_point
        if previous is None:
            self._last_point = current
            self._path_started_at = timestamp
            return False

        if (
            self._path_started_at is not None
            and timestamp - self._path_started_at > self.max_path_age
        ):
            self.reset()
            self._last_point = current
            self._path_started_at = timestamp
            return False

        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        distance = math.hypot(dx, dy)
        self._last_point = current
        if distance < self.min_segment_distance:
            return False

        direction = (dx / distance, dy / distance)
        old_direction = self._last_direction
        if old_direction is not None:
            dot = old_direction[0] * direction[0] + old_direction[1] * direction[1]
            if dot <= self.reversal_dot_threshold:
                self._reversals += 1
        self._last_direction = direction
        self._total_distance += distance

        if self._reversals >= 1 and self._total_distance >= self.min_total_distance:
            self._cooldown_until = timestamp + self.cooldown
            self.reset()
            self._cooldown_until = timestamp + self.cooldown
            self._last_point = current
            self._path_started_at = timestamp
            return True
        return False


def eligible_head_pat_specs(specs: Iterable[AnimationSpec]) -> tuple[AnimationSpec, ...]:
    """Return one-shot animations safe to start from an idle head gesture."""
    excluded = {
        GraphType.EVENT,
        GraphType.IDEL,
        GraphType.MOVE,
        GraphType.RAISED_STATIC,
        GraphType.RAISED_DYNAMIC,
    }
    result: list[AnimationSpec] = []
    seen: set[tuple[str, AnimatType]] = set()
    for spec in specs:
        if spec.animat is not AnimatType.SINGLE or spec.graph in excluded:
            continue
        key = (spec.name, spec.animat)
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
    return tuple(result)


def head_pat_specs(
    catalog: GraphCatalog | None,
    *,
    mode: str = HEAD_PAT_DEFAULT_MODE,
    names: Sequence[str] = (),
) -> tuple[AnimationSpec, ...]:
    """Resolve the configured animation pool against the current catalog."""
    if catalog is None:
        return ()
    all_specs = tuple(catalog.animations)
    if mode not in HEAD_PAT_MODES:
        mode = HEAD_PAT_DEFAULT_MODE
    eligible = eligible_head_pat_specs(all_specs)
    if mode == HEAD_PAT_DEFAULT_MODE:
        return tuple(spec for spec in eligible if spec.graph is GraphType.TOUCH_BODY)
    if mode == HEAD_PAT_ALL_MODE:
        return eligible
    wanted = {str(name).strip() for name in names if str(name).strip()}
    return tuple(spec for spec in eligible if spec.name in wanted)


def choose_head_pat_spec(
    specs: Sequence[AnimationSpec],
    *,
    rng: random.Random,
    previous_name: str | None = None,
) -> AnimationSpec | None:
    if not specs:
        return None
    candidates = list(specs)
    if len(candidates) > 1 and previous_name:
        without_previous = [spec for spec in candidates if spec.name != previous_name]
        if without_previous:
            candidates = without_previous
    return rng.choice(candidates)
