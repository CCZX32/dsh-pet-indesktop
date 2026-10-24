from petcore.ui.settings.base import SettingsPage, make_button, make_checkbox

KEYS = ('divination_enabled', 'divination_speak', 'divination_hint')


class DivinationPage(SettingsPage):
    title = '抽签'

    def __init__(self, host, parent=None, *, runtime=None):
        super().__init__(host, parent)
        self.runtime = runtime
        self.slot = getattr(getattr(host, 'window', None), 'slot', 0)
        self._initial = {key: host.config.get(key) for key in KEYS}
        self.group_heading('每日一签')
        card = self.section('此宠物的抽签偏好', level=3)
        self.enabled, self.voice, self.hint = (make_checkbox(self) for _ in range(3))
        self.controls = (self.enabled, self.voice, self.hint)
        self._load()
        for label, control, hint in (
            ('启用抽签', self.enabled, '48 支签轮流抽取，一轮不重复；同日所有宠物共用一支签。'),
            ('语音念签', self.voice, '默认关闭；开启后预热最多两条音频，播放结束后再揭签。'),
            ('首次互动提示', self.hint, '每天首次与宠物互动时提示一次，不会自动抽签。'),
        ):
            control.setAccessibleName(label)
            card.add_row(label, control, hint, expand=True)
            control.toggled.connect(self._changed)
        button = make_button('抽支签', self)
        button.setEnabled(runtime is not None)
        button.clicked.connect(lambda: runtime.draw(self.slot))
        card.add_buttons([button])
        self.add_note('签文与轮次立即保存，设置取消不会重抽或回滚今日签。免打扰期间只暂存文字，不补播语音。')

    def _load(self):
        for key, control in zip(KEYS, self.controls):
            control.blockSignals(True)
            control.setChecked(bool(self.host.config.get(key)))
            control.blockSignals(False)
        self.voice.setEnabled(self.enabled.isChecked())
        self.hint.setEnabled(self.enabled.isChecked())

    def _changed(self, _checked=None):
        for key, control in zip(KEYS, self.controls):
            self.host.config.set(key, control.isChecked())
        self._load()
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
        return ['抽签', '每日一签', '签文', '解签', '语音', 'divination']
