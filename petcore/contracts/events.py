from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True, slots=True)
class CoreEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "core"


class EventBus(Protocol):
    def subscribe(
        self, owner: str, event_type: str, handler: Callable[[CoreEvent], None]
    ) -> Callable[[], None]: ...

    def publish(self, event: CoreEvent) -> None: ...
