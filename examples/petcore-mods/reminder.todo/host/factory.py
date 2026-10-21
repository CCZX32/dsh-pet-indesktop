from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage


class TodoRuntime:
    def __init__(self, context):
        self.context = context
        self._dialog = None
        self.commands = {"open": self.open_panel}

    def _items(self) -> list[str]:
        config = getattr(self.context.host, "config", None)
        if config is None:
            return []
        return [str(item) for item in (config.get("todo_items") or []) if str(item).strip()]

    def open_panel(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        dialog = QDialog()
        dialog.setWindowTitle("待办提醒")
        dialog.resize(420, 360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("当前待办（在设置 →「待办」里编辑）", dialog))
        widget = QListWidget(dialog)
        items = self._items()
        if items:
            widget.addItems(items)
        else:
            widget.addItem("（暂无待办）")
        layout.addWidget(widget, 1)
        close = QPushButton("关闭", dialog)
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        self._dialog = dialog
        dialog.show()

    def start(self) -> None:
        return

    def stop(self) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    def close(self) -> None:
        self.stop()


class TodoPage(SettingsPage):
    title = "待办"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = self._text()
        card = self.section("清单")
        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText("每行一条待办")
        self.editor.setPlainText(self._initial)
        self.editor.setMinimumHeight(180)
        self.editor.textChanged.connect(self._on_changed)
        card.add_widget(self.editor)
        self.add_note("待办保存在本机配置里；右键「待办提醒」打开清单。")

    def config(self):
        return self.host.config

    def _text(self) -> str:
        return "\n".join(str(item) for item in (self.config().get("todo_items") or []))

    def _on_changed(self) -> None:
        items = [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]
        self.config().set("todo_items", items)
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
        self.config().set(
            "todo_items",
            [line.strip() for line in self._initial.splitlines() if line.strip()],
        )
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["待办", "提醒", "清单", "todo", "reminder"]


def create_host(_context):
    return FeatureDefinition(
        owner="reminder.todo",
        contributions=(
            Contribution(
                kind="menu",
                id="open",
                data={"label": "待办提醒", "command": "open", "order": 88, "icon": "todo"},
            ),
            Contribution(
                kind="settings_page",
                id="todo",
                data={"title": "待办", "order": 660, "icon": "todo"},
            ),
        ),
        runtime_factory=TodoRuntime,
        settings_factory=TodoPage,
    )
