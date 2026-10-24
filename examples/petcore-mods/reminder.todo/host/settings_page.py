from petcore.ui.settings.base import SettingsPage, make_button, make_checkbox, make_spin

KEYS = ("todo_reminder_enabled", "todo_reminder_lead_minutes", "todo_reminder_speak")


class TodoPage(SettingsPage):
    title = "待办"

    def __init__(self, host, parent=None, *, runtime=None):
        super().__init__(host, parent)
        self.runtime = runtime
        self.slot = getattr(getattr(host, "window", None), "slot", 0)
        self._initial = {key: host.config.get(key) for key in KEYS}
        self.group_heading("待办提醒")
        card = self.section("此宠物的提醒", level=3)
        self.enabled, self.voice = make_checkbox(self), make_checkbox(self)
        self.lead = make_spin(self)
        self.lead.setRange(0, 60)
        self.lead.setSuffix(" 分钟")
        self.lead.setAccessibleName("提前提醒分钟数")
        self._load()
        card.add_row("启用待办调度", self.enabled, "关闭此宠物后暂停调度，清单和已触发记录保留。", expand=True)
        card.add_row("提前提醒", self.lead, "0 表示仅到期提醒；迟到 10 分钟内补发，超时跳过。", expand=True)
        card.add_row("语音提醒", self.voice, "默认关闭；免打扰结束只汇总文字，不补播积压语音。", expand=True)
        button = make_button("管理待办", self)
        button.setEnabled(runtime is not None)
        button.clicked.connect(lambda: runtime.open_panel(self.slot))
        card.add_buttons([button])
        self.add_note("清单在独立数据文件中立即保存，设置取消不撤销清单编辑或已触发状态。旧文本清单迁移为未设置时间，不自动提醒。")
        self.enabled.toggled.connect(self._changed)
        self.voice.toggled.connect(self._changed)
        self.lead.valueChanged.connect(self._changed)

    def _load(self):
        for control in (self.enabled, self.voice, self.lead):
            control.blockSignals(True)
        self.enabled.setChecked(bool(self.host.config.get(KEYS[0], True)))
        self.lead.setValue(int(self.host.config.get(KEYS[1], 5)))
        self.voice.setChecked(bool(self.host.config.get(KEYS[2], False)))
        for control in (self.enabled, self.voice, self.lead):
            control.blockSignals(False)

    def _changed(self, _value=None):
        for key, value in zip(KEYS, (self.enabled.isChecked(), self.lead.value(), self.voice.isChecked())):
            self.host.config.set(key, value)
        if self.runtime:
            self.runtime.preferences_changed(self.slot)
        self.changed.emit()

    def dirty(self):
        return any(self.host.config.get(key) != value for key, value in self._initial.items())

    def confirm_save(self):
        self._initial = {key: self.host.config.get(key) for key in KEYS}

    def discard_changes(self):
        for key, value in self._initial.items():
            self.host.config.set(key, value)
        self._load()
        if self.runtime:
            self.runtime.preferences_changed(self.slot)
        self.changed.emit()

    def keywords(self):
        return ["待办", "提醒", "提前", "每日重复", "一次性", "todo", "reminder"]
