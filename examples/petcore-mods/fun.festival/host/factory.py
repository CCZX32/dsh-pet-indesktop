from __future__ import annotations

from datetime import date

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_checkbox

FESTIVALS = {
    (1, 1): "元旦",
    (2, 14): "情人节",
    (3, 8): "妇女节",
    (5, 1): "劳动节",
    (6, 1): "儿童节",
    (10, 1): "国庆节",
    (12, 25): "圣诞节",
    (12, 31): "跨年夜",
}


def today_festival(day: date | None = None) -> str | None:
    day = day or date.today()
    return FESTIVALS.get((day.month, day.day))


class FestivalRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"today": self.today}

    def today(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is not None and not bool(config.get("festival_enabled", True)):
            return
        name = today_festival()
        presentation = self.context.ports.presentation
        if presentation is None:
            return
        if name:
            presentation.say(f"今天是{name}，节日快乐！", duration_ms=6000)
        else:
            presentation.say("今天没有内置节日；日子普通也值得好好过。", duration_ms=5000)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class FestivalPage(SettingsPage):
    title = "节日提醒"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("festival_enabled", True))
        card = self.section("节日")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用节日提醒", self.enabled, "右键「今日节日」显示内置公历节日；不联网。")
        self.add_note("当前只包含公历固定日期（元旦、情人节、劳动节、国庆、圣诞等），农历节日留待后续数据包。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("festival_enabled", self.enabled.isChecked())
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
        self.config().set("festival_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["节日", "提醒", "元旦", "国庆", "圣诞", "festival"]


def create_host(_context):
    return FeatureDefinition(
        owner="fun.festival",
        contributions=(
            Contribution(
                kind="menu",
                id="today",
                data={"label": "今日节日", "command": "today", "order": 87, "icon": "todo"},
            ),
            Contribution(
                kind="settings_page",
                id="festival",
                data={"title": "节日提醒", "order": 650, "icon": "todo"},
            ),
        ),
        runtime_factory=FestivalRuntime,
        settings_factory=FestivalPage,
    )
