from __future__ import annotations

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QTimeEdit, QVBoxLayout
from petcore.ui.settings.base import make_button
from petcore.ui.settings.style import is_dark, stylesheet
from .model import next_reminder


class TodoEditor(QDialog):
    def __init__(self, panel, entry=None):
        super().__init__(panel)
        self.panel, self.entry = panel, entry
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("编辑待办" if entry else "新增待办")
        self.resize(460, 360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QPlainTextEdit(self)
        self.title_edit.setAccessibleName("待办内容")
        self.title_edit.setPlainText(entry["title"] if entry else "")
        self.kind = QComboBox(self)
        for text, value in (("未设置时间", "none"), ("一次性", "once"), ("每日重复", "daily")):
            self.kind.addItem(text, value)
        self.date = QDateEdit(QDate.currentDate(), self)
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.time = QTimeEdit(QTime.currentTime(), self)
        self.time.setDisplayFormat("HH:mm")
        form.addRow("内容", self.title_edit)
        form.addRow("重复", self.kind)
        form.addRow("日期", self.date)
        form.addRow("时间", self.time)
        for control, name in ((self.kind, "重复规则"), (self.date, "提醒日期"), (self.time, "提醒时间")):
            control.setAccessibleName(name)
        if entry:
            self.kind.setCurrentIndex(self.kind.findData(entry["kind"]))
            if entry["date"]:
                self.date.setDate(QDate.fromString(entry["date"], "yyyy-MM-dd"))
            if entry["time"]:
                self.time.setTime(QTime.fromString(entry["time"], "HH:mm"))
        def visibility():
            self.date.setEnabled(self.kind.currentData() == "once")
            self.time.setEnabled(self.kind.currentData() != "none")
        self.kind.currentIndexChanged.connect(visibility)
        visibility()
        layout.addLayout(form)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        row = QHBoxLayout()
        cancel = make_button("取消", self)
        cancel.clicked.connect(self.reject)
        self.save_button = make_button("保存", self, primary=True)
        self.save_button.clicked.connect(self.save)
        row.addStretch(); row.addWidget(cancel); row.addWidget(self.save_button)
        layout.addLayout(row)

    def save(self):
        kind = self.kind.currentData()
        fields = dict(title=self.title_edit.toPlainText(), kind=kind,
                      date=self.date.date().toString("yyyy-MM-dd") if kind == "once" else "",
                      time=self.time.time().toString("HH:mm") if kind != "none" else "")
        try:
            if self.entry:
                self.panel.runtime.update(self.panel.slot, self.entry["id"], **fields)
            else:
                self.panel.runtime.add(self.panel.slot, **fields)
        except (OSError, ValueError, TypeError):
            self.error.setText("保存失败：请检查内容、日期及数据目录的可写性。原数据未删除。")
            return
        self.accept()


class TodoPanel(QDialog):
    def __init__(self, runtime, slot):
        super().__init__()
        self.runtime, self.slot, self.editor = runtime, slot, None
        self._delete_id = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"待办提醒 · 宠物 {slot}")
        self.resize(560, 440)
        self.setStyleSheet(stylesheet(is_dark(), font_size=13))
        layout = QVBoxLayout(self)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.items = QListWidget(self)
        self.items.setAccessibleName("待办清单")
        self.items.currentRowChanged.connect(self._selection_changed)
        self.items.itemDoubleClicked.connect(lambda _: self.edit())
        layout.addWidget(self.items, 1)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        row = QHBoxLayout()
        self.new_button = make_button("新增", self, primary=True)
        self.edit_button = make_button("编辑", self)
        self.toggle_button = make_button("启用 / 停用", self)
        self.delete_button = make_button("删除", self)
        for button, callback in ((self.new_button, lambda: self.edit(new=True)), (self.edit_button, self.edit),
                                 (self.toggle_button, self.toggle), (self.delete_button, self.delete)):
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def current(self):
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, _row):
        self._delete_id = None
        self.delete_button.setText("删除")
        for button in (self.edit_button, self.toggle_button, self.delete_button):
            button.setEnabled(self.current() is not None)

    def refresh(self):
        current = self.current()
        try:
            state = self.runtime.store(self.slot).state
            pet = self.runtime.pet(self.slot)
            next_item = next_reminder(state, self.runtime.now(), lead_minutes=pet.config.get("todo_reminder_lead_minutes", 5)) if pet.config.get("todo_reminder_enabled", True) else None
            self.preview.setText("下一条：" + next_item["at"].replace("T", " ") + " · " + ("提前" if next_item["phase"] == "lead" else "到期") + " · " + next_item["title"] if next_item else "暂无下一条提醒（未设时间、停用和已归档条目不会调度）")
            self.items.clear()
            for entry in state["items"]:
                status = "已归档" if entry["archived"] else "停用" if not entry["enabled"] else "未设时间" if entry["kind"] == "none" else (entry["date"] if entry["kind"] == "once" else "每日") + " " + entry["time"]
                item = QListWidgetItem(f'[{status}] {entry["title"]}', self.items)
                item.setToolTip(entry["title"])
                item.setData(Qt.ItemDataRole.UserRole, dict(entry))
                if current and entry["id"] == current["id"]:
                    self.items.setCurrentItem(item)
            self.error.clear()
            self._selection_changed(self.items.currentRow())
        except (OSError, ValueError, TypeError):
            self.error.setText("待办文件无法读取，已保留原文件；请检查数据目录。")

    def edit(self, _checked=False, *, new=False):
        if self.editor is not None:
            self.editor.raise_()
            return
        entry = None if new else self.current()
        if not new and entry is None:
            return
        editor = TodoEditor(self, entry)
        self.editor = editor
        editor.finished.connect(lambda _: setattr(self, "editor", None))
        editor.show()

    def toggle(self):
        entry = self.current()
        if entry:
            self._mutate(lambda: self.runtime.toggle(self.slot, entry["id"]))

    def delete(self):
        entry = self.current()
        if not entry:
            return
        if self._delete_id != entry["id"]:
            self._delete_id = entry["id"]
            self.delete_button.setText("确认删除")
            self.error.setText("再次点击确认删除此条目；其他条目和迁移备份不受影响。")
            return
        self._mutate(lambda: self.runtime.delete(self.slot, entry["id"]))

    def _mutate(self, operation):
        try:
            operation()
        except (OSError, ValueError, TypeError):
            self.error.setText("保存失败，原数据保留。")
