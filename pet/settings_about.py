# -*- coding: utf-8 -*-
"""Read-only product and author information shared by every settings variant."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget,
)

from . import __version__
from .context_menus.icons import vector_widget_icon
from .settings_widgets import SettingsSection, _system_dark

AUTHOR_ACCOUNTS = (
    ("BiliBili", "@張墨林"),
    ("BiliBili", "@快乐小咸鱼a"),
    ("抖音", "@Eager"),
    ("GitHub", "@MerZlin"),
)
GITHUB_PROFILE = "https://github.com/MerZlin"


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("menuStyle", "modern")
        self.setProperty("modernDark", _system_dark())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        product = QWidget(self)
        details = QVBoxLayout(product)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(6)
        for text, role in (("深深桌宠", "sectionTitle"),
                           (f"版本 {__version__}", "settingHint"),
                           ("开发与维护：MerZlin", "settingLabel")):
            label = QLabel(text, product)
            label.setObjectName(role)
            label.setWordWrap(True)
            details.addWidget(label)
        layout.addWidget(product)
        rows = [self._account_row(platform, handle) for platform, handle in AUTHOR_ACCOUNTS]
        layout.addWidget(SettingsSection("作者账号", rows, self))
        layout.addStretch(1)

    def _account_row(self, platform: str, handle: str) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        for value, role in ((platform, "settingHint"), (handle, "settingLabel")):
            label = QLabel(value, row)
            label.setObjectName(role)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(label)
        layout.addLayout(text, 1)
        copy = self._button(row, "copy", f"复制 {platform} 账号 {handle}")
        copy.clicked.connect(lambda: self._copy_account(handle, copy))
        layout.addWidget(copy)
        if platform == "GitHub":
            link = self._button(row, "external_link", "打开 GitHub 主页")
            link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_PROFILE)))
            layout.addWidget(link)
        return row

    @staticmethod
    def _button(parent: QWidget, icon: str, name: str) -> QPushButton:
        button = QPushButton(parent)
        button.setIcon(vector_widget_icon(button, icon))
        button.setFixedSize(32, 32)
        button.setToolTip(name)
        button.setAccessibleName(name)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _copy_account(handle: str, button: QPushButton) -> None:
        QApplication.clipboard().setText(handle)
        QToolTip.showText(button.mapToGlobal(QPoint(0, button.height())), "已复制", button)
