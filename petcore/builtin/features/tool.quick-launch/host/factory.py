from __future__ import annotations

import os
import subprocess

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage


def _apps(config) -> list[dict]:
    return [dict(item) for item in (config.get("quick_launch_apps") or []) if isinstance(item, dict)]


def _launch(app: dict) -> bool:
    path = str(app.get("path") or "").strip()
    if not path:
        return False
    args = [str(item) for item in (app.get("args") or [])]
    try:
        subprocess.Popen([path, *args], close_fds=True)
        return True
    except OSError:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False


class QuickLaunchRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"open_menu": self.open_menu}

    def open_menu(self) -> None:
        config = getattr(self.context.host, "config", None)
        apps = _apps(config) if config is not None else []
        if not apps:
            presentation = self.context.ports.presentation
            if presentation is not None:
                presentation.notify("快捷启动", "还没有配置应用，请到设置 → 快捷启动 添加。")
            return
        menu = QMenu()
        for app in apps:
            name = str(app.get("name") or app.get("path") or "未命名")
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, item=app: _launch(item))
        menu.exec(QCursor.pos())

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class QuickLaunchPage(SettingsPage):
    title = "快捷启动"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = self._text()
        card = self.section("应用")
        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText("每行一个应用：名称|路径|参数1 参数2")
        self.editor.setPlainText(self._initial)
        self.editor.setMinimumHeight(160)
        self.editor.textChanged.connect(self._on_changed)
        card.add_widget(self.editor)
        self.add_note("例如：记事本|C:\\Windows\\notepad.exe|。只在本机启动程序，不上传任何信息。")

    def config(self):
        return self.host.config

    def _text(self) -> str:
        lines = []
        for app in _apps(self.config()):
            args = " ".join(str(item) for item in (app.get("args") or []))
            lines.append(f"{app.get('name', '')}|{app.get('path', '')}|{args}")
        return "\n".join(lines)

    def _parse(self, text: str) -> list[dict]:
        apps = []
        for line in text.splitlines():
            parts = [part.strip() for part in line.split("|")]
            if not parts or not parts[0]:
                continue
            name = parts[0]
            path = parts[1] if len(parts) > 1 else ""
            args = parts[2].split() if len(parts) > 2 and parts[2] else []
            if path:
                apps.append({"name": name, "path": path, "args": args})
        return apps

    def _on_changed(self) -> None:
        self.config().set("quick_launch_apps", self._parse(self.editor.toPlainText()))
        self.changed.emit()

    def dirty(self) -> bool:
        return self.editor.toPlainText() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.editor.toPlainText()

    def discard_changes(self) -> None:
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._initial)
        self.editor.blockSignals(False)
        self.config().set("quick_launch_apps", self._parse(self._initial))
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["快捷启动", "启动", "应用", "程序", "quick launch", "launcher"]


def create_host(_context):
    return FeatureDefinition(
        owner="tool.quick-launch",
        contributions=(
            Contribution(
                kind="menu",
                id="open_menu",
                data={"label": "快捷启动", "command": "open_menu", "order": 78, "icon": "application"},
            ),
            Contribution(
                kind="settings_page",
                id="quick_launch",
                data={"host_page": "menu", "title": "快捷启动", "order": 640, "icon": "application"},
            ),
        ),
        runtime_factory=QuickLaunchRuntime,
        settings_factory=QuickLaunchPage,
    )
