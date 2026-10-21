from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_checkbox

QUOTES = (
    "今日宜摸鱼，忌内耗。",
    "会有好事发生，耐心一点。",
    "先完成再完美，今天适合开工。",
    "把想做的事写下来，运气会变好。",
    "今天适合早点睡，明天会更清醒。",
    "遇到问题先深呼吸，答案在路上。",
)


class DivinationRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"draw": self.draw}

    def _state_path(self) -> Path | None:
        storage = getattr(self.context.ports, "storage", None)
        if storage is None:
            return None
        return storage.data_dir(self.context.owner) / "daily.json"

    def _load(self) -> dict:
        path = self._state_path()
        if path is None:
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, data: dict) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def draw(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is not None and not bool(config.get("divination_enabled", True)):
            return
        today = date.today().isoformat()
        state = self._load()
        quote = state.get("quote") if state.get("date") == today else None
        if not quote:
            quote = random.choice(QUOTES)
            self._save({"date": today, "quote": quote})
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say(str(quote), duration_ms=6000)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class DivinationPage(SettingsPage):
    title = "抽签"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("divination_enabled", True))
        card = self.section("每日一签")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用抽签", self.enabled, "右键「抽支签」每天随机一支；当天重复显示同一支。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("divination_enabled", self.enabled.isChecked())
        self.changed.emit()

    def dirty(self) -> bool:
        return self.enabled.isChecked() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.enabled.isChecked()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial)
        self.enabled.blockSignals(False)
        self.config().set("divination_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["抽签", "每日一签", "运气", "divination", "fortune"]


def create_host(_context):
    return FeatureDefinition(
        owner="fun.divination",
        contributions=(
            Contribution(
                kind="menu",
                id="draw",
                data={"label": "抽支签", "command": "draw", "order": 86, "icon": "todo"},
            ),
            Contribution(
                kind="settings_page",
                id="divination",
                data={"title": "抽签", "order": 630, "icon": "todo"},
            ),
        ),
        runtime_factory=DivinationRuntime,
        settings_factory=DivinationPage,
    )
