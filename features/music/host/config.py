# -*- coding: utf-8 -*-
"""音乐启动器包的配置面：手动播放器路径（键 → 路径）。"""

from __future__ import annotations

from .players import PLAYERS

DEFAULTS = {"enabled": True, "player_paths": {}}


def _paths(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(path).strip()
        for key, path in value.items()
        if key in PLAYERS and isinstance(path, str) and path.strip()
    }


class MusicConfig:
    def __init__(self, context):
        self._context = context
        self._values = dict(DEFAULTS)
        self.reload()

    def reload(self) -> None:
        try:
            raw = self._context.preferences.read()
        except Exception:
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        self._values = {
            "enabled": raw.get("enabled") if isinstance(raw.get("enabled"), bool) else True,
            "player_paths": _paths(raw.get("player_paths")),
        }

    @property
    def enabled(self) -> bool:
        return bool(self._values["enabled"])

    def manual_path(self, player_key: str) -> str:
        return str(self._values["player_paths"].get(player_key, ""))

    def save(self, *, enabled: bool, player_paths: dict) -> bool:
        values = {"enabled": bool(enabled), "player_paths": _paths(player_paths)}
        self._context.preferences.stage(values)
        if not self._context.preferences.flush():
            return False
        self._values = values
        return True
