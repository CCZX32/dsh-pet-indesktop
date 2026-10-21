from __future__ import annotations

import math

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_button

QUIET_MINUTE_CHOICES = (15, 30, 60, 120)
DEFAULT_QUIET_MINUTES = 30
DEFAULT_KEY = "quiet_minutes_default"


def quiet_duration_label(minutes: int) -> str:
    value = int(minutes)
    if value % 60 == 0:
        return f"{value // 60} 小时"
    return f"{value} 分钟"


def _quiet_port(container):
    ports = getattr(container, "ports", None)
    return getattr(ports, "quiet", None)


class QuietRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"quiet_30": self.quiet_for_default, "restore": self.restore}

    def _default_minutes(self) -> int:
        config = getattr(self.context.host, "config", None)
        getter = getattr(config, "get", None)
        try:
            value = int(getter(DEFAULT_KEY) or DEFAULT_QUIET_MINUTES) if callable(getter) else DEFAULT_QUIET_MINUTES
        except (TypeError, ValueError):
            value = DEFAULT_QUIET_MINUTES
        if value not in QUIET_MINUTE_CHOICES:
            value = DEFAULT_QUIET_MINUTES
        return value

    def quiet_for(self, minutes: int) -> None:
        quiet = _quiet_port(self.context)
        if quiet is not None:
            quiet.set_quiet(int(minutes) * 60)
        presentation = getattr(self.context.ports, "presentation", None)
        if presentation is not None:
            # 命令反馈必须绕开免打扰抑制，否则「点完没反应」。
            presentation.notify(
                "免打扰",
                f"已静默 {quiet_duration_label(minutes)}，到期自动恢复；点「恢复提醒」可提前结束",
                force=True,
            )

    def quiet_for_default(self) -> None:
        self.quiet_for(self._default_minutes())

    def restore(self) -> None:
        quiet = _quiet_port(self.context)
        if quiet is not None:
            quiet.set_quiet(0)
        presentation = getattr(self.context.ports, "presentation", None)
        if presentation is not None:
            presentation.notify("免打扰", "已恢复提醒", force=True)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class QuietPage(SettingsPage):
    title = "免打扰"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = self._default_minutes()
        self.add_note(
            "免打扰期间桌宠不会自动冒泡（自言自语、节日提醒、报时等）；"
            "你主动点的菜单命令仍会给反馈。免打扰不落盘，到期或重启自动解除。"
        )

        default_card = self.section("默认时长")
        self.default_select = QComboBox(self)
        self.default_select.setAccessibleName("免打扰默认时长")
        for minutes in QUIET_MINUTE_CHOICES:
            self.default_select.addItem(quiet_duration_label(minutes), int(minutes))
        index = self.default_select.findData(self._initial)
        self.default_select.setCurrentIndex(index if index >= 0 else 1)
        self.default_select.currentIndexChanged.connect(self._on_changed)
        default_card.add_row(
            "右键菜单默认档",
            self.default_select,
            "只决定右键「免打扰」按多久静默；不改变当前是否在静默。",
        )

        state_card = self.section("当前状态")
        self.state_label = QLabel("", self)
        self.state_label.setObjectName("settingHint")
        self.state_label.setWordWrap(True)
        self.restore_button = make_button("恢复提醒", self)
        self.restore_button.clicked.connect(self._restore)
        state_card.add_row("状态", self.state_label, "免打扰是运行态：重启桌宠即自动解除。")
        state_card.add_buttons([self.restore_button])

        action_card = self.section("立即免打扰")
        buttons_row = QWidget(self)
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        for minutes in QUIET_MINUTE_CHOICES:
            button = make_button(quiet_duration_label(minutes), self)
            button.clicked.connect(lambda _checked=False, value=minutes: self._quiet(value))
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        action_card.add_row(
            "静默时长",
            buttons_row,
            "立即静默这段时间；再点一档 = 重新计时，不叠加。",
            expand=True,
        )
        self._refresh_state()

    def config(self):
        return self.host.config

    def _default_minutes(self) -> int:
        try:
            value = int(self.config().get(DEFAULT_KEY) or DEFAULT_QUIET_MINUTES)
        except (TypeError, ValueError):
            value = DEFAULT_QUIET_MINUTES
        return value if value in QUIET_MINUTE_CHOICES else DEFAULT_QUIET_MINUTES

    def _quiet_port(self):
        return getattr(self.host, "quiet", None)

    def _quiet(self, minutes: int) -> None:
        quiet = self._quiet_port()
        if quiet is not None:
            quiet.set_quiet(int(minutes) * 60)
        presentation = getattr(self.host, "presentation_port", None)
        if callable(presentation):
            try:
                presentation().notify(
                    "免打扰",
                    f"已静默 {quiet_duration_label(minutes)}，到期自动恢复",
                    force=True,
                )
            except Exception:
                pass
        self._refresh_state()
        self.changed.emit()

    def _restore(self) -> None:
        quiet = self._quiet_port()
        if quiet is not None:
            quiet.set_quiet(0)
        presentation = getattr(self.host, "presentation_port", None)
        if callable(presentation):
            try:
                presentation().notify("免打扰", "已恢复提醒", force=True)
            except Exception:
                pass
        self._refresh_state()
        self.changed.emit()

    def _refresh_state(self) -> None:
        quiet = self._quiet_port()
        remaining = quiet.remaining_seconds() if quiet is not None else 0.0
        if remaining > 0:
            minutes = int(math.ceil(remaining / 60.0))
            self.state_label.setText(f"静默中，剩余约 {minutes} 分钟")
            self.restore_button.setEnabled(True)
        else:
            self.state_label.setText("未开启")
            self.restore_button.setEnabled(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_state()

    def _on_changed(self, *_args) -> None:
        try:
            value = int(self.default_select.currentData() or DEFAULT_QUIET_MINUTES)
        except (TypeError, ValueError):
            value = DEFAULT_QUIET_MINUTES
        self.config().set(DEFAULT_KEY, value)
        self.changed.emit()

    def dirty(self) -> bool:
        return self._default_minutes() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self._default_minutes()

    def discard_changes(self) -> None:
        config = self.config()
        config.set(DEFAULT_KEY, self._initial)
        self.default_select.blockSignals(True)
        index = self.default_select.findData(self._initial)
        self.default_select.setCurrentIndex(index if index >= 0 else 1)
        self.default_select.blockSignals(False)
        self._refresh_state()
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["免打扰", "静默", "安静", "提醒", "quiet", "silent", "dnd"]


def create_host(context):
    def quiet_active() -> bool:
        quiet = _quiet_port(context)
        return bool(quiet is not None and quiet.quiet_active())

    return FeatureDefinition(
        owner="tool.quiet-mode",
        contributions=(
            Contribution(
                kind="menu",
                id="quiet_30",
                data={
                    "label": "免打扰",
                    "command": "quiet_30",
                    "order": 90,
                    "icon": "pause",
                    "checked": quiet_active,
                },
            ),
            Contribution(
                kind="settings_page",
                id="quiet",
                data={"host_page": "interaction", "title": "免打扰", "order": 710, "icon": "pause"},
            ),
        ),
        runtime_factory=QuietRuntime,
        settings_factory=QuietPage,
    )
