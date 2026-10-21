from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .contributions import Contribution
from .host import HostPorts


class Runtime(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class FeatureContext(Protocol):
    owner: str
    core_version: str
    api_version: str
    ports: HostPorts
    config: dict[str, Any]
    events: Any
    host: Any

    def log(self, message: str, *, level: str = "info") -> None: ...


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    owner: str
    contributions: tuple[Contribution, ...] = ()
    runtime_factory: Callable[[FeatureContext], Runtime] | None = None
    settings_factory: Callable[[FeatureContext], Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("feature owner must not be empty")
        for contribution in self.contributions:
            if not contribution.id:
                raise ValueError("contribution id must not be empty")
