# -*- coding: utf-8 -*-
"""语音报时包的配置面：调度偏好与自定义台词。"""

from __future__ import annotations

from .schedule import clean_schedule, parse_custom_times

DEFAULTS = {
    "enabled": False,
    "schedule": "hourly",
    "custom_times": [],
    "show_bubble": True,
    "quotes_zh": "",
    "quotes_en": "",
}


class VoiceConfig:
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
            "enabled": raw.get("enabled") if isinstance(raw.get("enabled"), bool) else DEFAULTS["enabled"],
            "schedule": clean_schedule(raw.get("schedule")),
            "custom_times": list(parse_custom_times(raw.get("custom_times"))),
            "show_bubble": raw.get("show_bubble") if isinstance(raw.get("show_bubble"), bool) else True,
            "quotes_zh": raw.get("quotes_zh") if isinstance(raw.get("quotes_zh"), str) else "",
            "quotes_en": raw.get("quotes_en") if isinstance(raw.get("quotes_en"), str) else "",
        }

    @property
    def enabled(self) -> bool:
        return bool(self._values["enabled"])

    @property
    def schedule(self) -> str:
        return str(self._values["schedule"])

    @property
    def custom_times(self):
        return tuple(self._values["custom_times"])

    @property
    def show_bubble(self) -> bool:
        return bool(self._values["show_bubble"])

    @property
    def quotes_zh(self) -> str:
        return str(self._values["quotes_zh"])

    @property
    def quotes_en(self) -> str:
        return str(self._values["quotes_en"])

    def save(self, *, enabled, schedule, custom_times, show_bubble, quotes_zh, quotes_en) -> bool:
        values = {
            "enabled": bool(enabled),
            "schedule": clean_schedule(schedule),
            "custom_times": [f"{hour:02d}:{minute:02d}" for hour, minute in parse_custom_times(custom_times)],
            "show_bubble": bool(show_bubble),
            "quotes_zh": str(quotes_zh or ""),
            "quotes_en": str(quotes_en or ""),
        }
        self._context.preferences.stage(values)
        if not self._context.preferences.flush():
            return False
        self._values = values
        return True
