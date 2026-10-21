from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONTRIBUTION_KINDS = frozenset(
    {
        "menu",
        "command",
        "settings_page",
        "hotkey",
        "card",
        "phrases",
        "sound",
        "theme",
        "seasonal",
        "install_hook",
    }
)


@dataclass(frozen=True, slots=True)
class Contribution:
    kind: str
    id: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CONTRIBUTION_KINDS:
            raise ValueError(f"unknown contribution kind: {self.kind}")
        if not self.id:
            raise ValueError("contribution id must not be empty")


@dataclass(frozen=True, slots=True)
class SettingsPageSpec:
    id: str
    title: str
    factory: Any
    icon: str = ""
    order: int = 500
    owner: str = ""
    label: str = ""
    group: str = "base"
    #: 非空 = 该页由同名 Core 设置页内嵌（"interaction" / "menu" / "about"），
    #: 不再进扩展管理的导航。
    host_page: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.title:
            raise ValueError("settings page requires id and title")
