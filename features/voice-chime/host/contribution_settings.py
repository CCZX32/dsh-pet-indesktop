# -*- coding: utf-8 -*-
"""语音报时包的设置面板：调度、气泡与台词。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from pet.settings_widgets import SettingRow

from .config import VoiceConfig
from .schedule import SCHEDULE_KEYS, SCHEDULE_LABELS


class VoiceChimeSettings(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context
        self.config = VoiceConfig(context)
        self._disposed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("语音报时（包）", self)
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel("调度与台词在包内；合成、播放与免打扰沿用 Core 的音频通道。", self)
        intro.setObjectName("settingHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.enabled = QCheckBox("启用自动报时", self)
        self.schedule = QComboBox(self)
        for key in SCHEDULE_KEYS:
            self.schedule.addItem(SCHEDULE_LABELS[key], key)
        self.custom_times = QLineEdit(self)
        self.custom_times.setPlaceholderText("例如 08:00, 12:30, 18:00")
        self.show_bubble = QCheckBox("同时显示气泡", self)
        self.quotes_zh = QPlainTextEdit(self)
        self.quotes_zh.setPlaceholderText("每行一条中文台词；留空使用内置台词。")
        self.quotes_zh.setFixedHeight(84)
        self.quotes_en = QPlainTextEdit(self)
        self.quotes_en.setPlaceholderText("每行一条英文台词；留空使用内置台词。")
        self.quotes_en.setFixedHeight(64)

        layout.addWidget(SettingRow("voice_chime_package_enabled", "自动报时", "关闭后仍可从右键菜单手动报时。", self.enabled))
        layout.addWidget(SettingRow("voice_chime_package_schedule", "报时频率", "整点或固定间隔。", self.schedule))
        layout.addWidget(SettingRow("voice_chime_package_times", "自定义时间点", "仅“自定义时间点”模式生效，逗号分隔。", self.custom_times))
        layout.addWidget(SettingRow("voice_chime_package_bubble", "气泡", "语音之外是否同时显示文字。", self.show_bubble))
        layout.addWidget(SettingRow("voice_chime_package_quotes_zh", "中文台词", "每行一条，按日期与时刻轮换。", self.quotes_zh))
        layout.addWidget(SettingRow("voice_chime_package_quotes_en", "英文台词", "每行一条。", self.quotes_en))
        layout.addStretch(1)

        self.reload()
        self.hide()

    def dirty(self) -> bool:
        return not self._disposed and self._values() != self._baseline

    def draft(self):
        return {"values": self._values()}

    def confirm_save(self) -> bool:
        if self._disposed:
            return False
        values = self._values()
        if not self.config.save(
            enabled=values["enabled"],
            schedule=values["schedule"],
            custom_times=values["custom_times"],
            show_bubble=values["show_bubble"],
            quotes_zh=values["quotes_zh"],
            quotes_en=values["quotes_en"],
        ):
            return False
        self.reload()
        return True

    def discard_changes(self) -> bool:
        if self._disposed:
            return False
        self.reload()
        return True

    def dispose(self) -> None:
        self._disposed = True
        self.hide()
        self.deleteLater()

    def reload(self) -> None:
        self.config.reload()
        self.enabled.setChecked(self.config.enabled)
        index = self.schedule.findData(self.config.schedule)
        self.schedule.setCurrentIndex(index if index >= 0 else 0)
        self.custom_times.setText(", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in self.config.custom_times))
        self.show_bubble.setChecked(self.config.show_bubble)
        self.quotes_zh.setPlainText(self.config.quotes_zh)
        self.quotes_en.setPlainText(self.config.quotes_en)
        self._baseline = self._values()

    def _times(self):
        return [item.strip() for item in self.custom_times.text().replace("，", ",").split(",") if item.strip()]

    def _values(self) -> dict:
        return {
            "enabled": bool(self.enabled.isChecked()),
            "schedule": str(self.schedule.currentData()),
            "custom_times": self._times(),
            "show_bubble": bool(self.show_bubble.isChecked()),
            "quotes_zh": self.quotes_zh.toPlainText().strip(),
            "quotes_en": self.quotes_en.toPlainText().strip(),
        }
