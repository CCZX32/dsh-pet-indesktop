# -*- coding: utf-8 -*-
"""快捷启动包的设置面板：每行「名称|可执行文件路径」，最多五行。"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from pet.settings_widgets import SettingRow

from .config import MAX_ENTRIES, LaunchConfig


class QuickLaunchSettings(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context
        self.config = LaunchConfig(context)
        self._disposed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("快捷启动（包）", self)
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel(f"每行「名称|可执行文件路径」，最多 {MAX_ENTRIES} 行；只接受真实存在的文件。", self)
        intro.setObjectName("settingHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.entries = QPlainTextEdit(self)
        self.entries.setFixedHeight(120)
        self.entries.setPlaceholderText("记事本|C:/Windows/notepad.exe\n计算器|C:/Windows/System32/calc.exe")
        self.error = QLabel("", self)
        self.error.setObjectName("settingHint")
        self.error.setWordWrap(True)

        layout.addWidget(SettingRow("quick_launch_package_entries", "启动项", "名称与路径用竖线分隔。", self.entries))
        layout.addWidget(self.error)
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
        if len(values["entries"]) > MAX_ENTRIES:
            self.error.setText(f"最多只能配置 {MAX_ENTRIES} 项。")
            return False
        if not self.config.save(values["entries"]):
            self.error.setText("配置写入失败。")
            return False
        self.error.setText("")
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
        self.entries.setPlainText("\n".join(f"{entry['label']}|{entry['path']}" for entry in self.config.entries))
        self._baseline = self._values()

    def _values(self) -> dict:
        entries = []
        for line in self.entries.toPlainText().splitlines():
            label, _, path = line.partition("|")
            label, path = label.strip(), path.strip()
            if label and path:
                entries.append({"label": label[:40], "path": path})
        return {"entries": entries}
