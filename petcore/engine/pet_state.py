from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.content import AnimationSpec
from .geometry import DEFAULT_SCALE, clamp_scale, content_size


@dataclass
class PetState:
    x: int = 0
    y: int = 0
    scale: float = DEFAULT_SCALE
    facing: str = "left"
    dragging: bool = False
    current: AnimationSpec | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def window_size(self) -> tuple[int, int]:
        return content_size(self.scale)

    def set_scale(self, scale: float) -> None:
        self.scale = clamp_scale(scale)

    def flip(self) -> None:
        self.facing = "left" if self.facing == "right" else "right"
