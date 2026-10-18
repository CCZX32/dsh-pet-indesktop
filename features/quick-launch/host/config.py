# -*- coding: utf-8 -*-
"""快捷启动包的配置面：最多五个「名称 + 可执行文件」。"""

from __future__ import annotations

MAX_ENTRIES = 5


def clean_entries(value) -> list[dict]:
    if not isinstance(value, (list, tuple)):
        return []
    entries = []
    for item in value[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        path = item.get("path")
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(path, str) or not path.strip():
            continue
        entries.append({"label": label.strip()[:40], "path": path.strip()})
    return entries


class LaunchConfig:
    def __init__(self, context):
        self._context = context
        self._entries: list[dict] = []
        self.reload()

    def reload(self) -> None:
        try:
            raw = self._context.preferences.read()
        except Exception:
            raw = {}
        self._entries = clean_entries(raw.get("entries") if isinstance(raw, dict) else None)

    @property
    def entries(self) -> tuple[dict, ...]:
        return tuple(self._entries)

    def entry(self, index: int) -> dict | None:
        return self._entries[index] if 0 <= index < len(self._entries) else None

    def save(self, entries) -> bool:
        values = {"entries": clean_entries(entries)}
        self._context.preferences.stage(values)
        if not self._context.preferences.flush():
            return False
        self._entries = values["entries"]
        return True
