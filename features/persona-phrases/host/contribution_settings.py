# -*- coding: utf-8 -*-
"""日常台词包的设置面板。"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from pet.settings_widgets import SettingRow

from .config import PersonaConfig


class PersonaSettings(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context
        self.config = PersonaConfig(context)
        self._disposed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("日常台词（包）", self)
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel("每行一条；按日期轮换。留空使用内置台词。", self)
        intro.setObjectName("settingHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.phrases = QPlainTextEdit(self)
        self.phrases.setFixedHeight(140)
        self.phrases.setPlaceholderText("今天也要好好吃饭。\n慢慢来，比较快。")
        self.speak = QCheckBox("同时朗读", self)

        layout.addWidget(SettingRow("persona_package_phrases", "自定义台词", "每行一条。", self.phrases))
        layout.addWidget(SettingRow("persona_package_speak", "朗读", "复用 Core 音频通道。", self.speak))
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
        if not self.config.save(custom_phrases=values["custom_phrases"], speak=values["speak"]):
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
        self.phrases.setPlainText(self.config.custom_phrases)
        self.speak.setChecked(self.config.speak)
        self._baseline = self._values()

    def _values(self) -> dict:
        return {
            "custom_phrases": self.phrases.toPlainText().strip(),
            "speak": bool(self.speak.isChecked()),
        }
