# -*- coding: utf-8 -*-
"""音乐启动器包的设置面板：四个播放器的手动路径。"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from pet.settings_widgets import SettingRow

from .config import MusicConfig
from .players import PLAYERS


class MusicSettings(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context
        self.config = MusicConfig(context)
        self._disposed = False
        self._fields: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("音乐启动器（包）", self)
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel("留空时自动搜索常见安装目录；手填路径优先，且不会再退回自动搜索。", self)
        intro.setObjectName("settingHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.enabled = QCheckBox("启用右键菜单项", self)
        layout.addWidget(SettingRow("music_package_enabled", "启用", "关闭后仍可在 MOD 中心重新启用。", self.enabled))
        for key, (label, _exe, _parents) in PLAYERS.items():
            field = QLineEdit(self)
            field.setPlaceholderText("例如 D:/CloudMusic/cloudmusic.exe")
            self._fields[key] = field
            layout.addWidget(SettingRow(f"music_package_{key}", label, "播放器可执行文件的完整路径。", field))
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
        if not self.config.save(enabled=values["enabled"], player_paths=values["player_paths"]):
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
        for key, field in self._fields.items():
            field.setText(self.config.manual_path(key))
        self._baseline = self._values()

    def _values(self) -> dict:
        return {
            "enabled": bool(self.enabled.isChecked()),
            "player_paths": {key: field.text().strip() for key, field in self._fields.items() if field.text().strip()},
        }
