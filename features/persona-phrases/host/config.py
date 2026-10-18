# -*- coding: utf-8 -*-
"""日常台词包的配置面。"""

from __future__ import annotations

DEFAULTS = {"custom_phrases": "", "speak": False}


class PersonaConfig:
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
            "custom_phrases": raw.get("custom_phrases") if isinstance(raw.get("custom_phrases"), str) else "",
            "speak": raw.get("speak") if isinstance(raw.get("speak"), bool) else False,
        }

    @property
    def custom_phrases(self) -> str:
        return str(self._values["custom_phrases"])

    @property
    def speak(self) -> bool:
        return bool(self._values["speak"])

    def save(self, *, custom_phrases, speak) -> bool:
        values = {"custom_phrases": str(custom_phrases or ""), "speak": bool(speak)}
        self._context.preferences.stage(values)
        if not self._context.preferences.flush():
            return False
        self._values = values
        return True
