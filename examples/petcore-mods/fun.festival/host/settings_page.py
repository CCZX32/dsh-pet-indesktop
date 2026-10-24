from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox
from petcore.ui.settings.base import SettingsPage, make_checkbox, make_spin
from .domain import clean_birthday

SPECS = (
    ("festival_enabled", "手动查询今日节日", True, "只控制右键查询；不是自动提醒授权。"),
    ("festival_reminder_enabled", "自动节日与生日提醒", False, "默认关闭，仅此宠物；开启后当天已过首个时点会补提醒一次。"),
    ("festival_reminder_cn", "中国节日", True, "公历与农历，排除闰月重复。"),
    ("festival_reminder_solar_terms", "24 节气", True, "清明同时属于中国节日与节气。"),
    ("festival_reminder_west", "西方节日", True, "包含复活节、母亲节、父亲节等浮动日期。"),
    ("festival_birthday", "生日（MM-DD）", "", "可留空；仅存月日，不受分类开关影响；02-29只在闰年提醒。"),
    ("festival_reminder_mode", "提醒方式", "times", "按次数分布于09:00–21:00，或自定义时点。"),
    ("festival_reminder_count", "每日次数", 2, "1–6次。"),
    ("festival_reminder_times", "自定义时点", "09:00", "HH:MM，逗号/空格分隔；无有效时点时使用09:00。"),
    ("festival_reminder_show_quote", "附带节日文案", True, "同日每次轮换；同日多节日合并展示。"),
    ("festival_reminder_speak", "语音提醒", False, "默认关闭，使用共享语音通道；免打扰后仅汇总文字。"),
    ("festival_custom_quotes_cn", "中国节日与节气自定义文案", "", "每行一条，追加到内置文案池，单条最多120字。"),
    ("festival_custom_quotes_west", "西方节日自定义文案", "", "每行一条，追加到内置文案池，单条最多120字。"),
)


class FestivalPage(SettingsPage):
    title = "节日提醒"

    def __init__(self, host, parent=None, *, runtime=None):
        super().__init__(host, parent)
        self.runtime, self.slot = runtime, getattr(getattr(host, "window", None), "slot", 0)
        self._initial = {key: host.config.get(key, default) for key, _, default, _ in SPECS}
        self.controls = {}
        self.group_heading("节日与生日提醒")
        card = self.section("此宠物的节日", level=3)
        for key, label, default, hint in SPECS:
            if isinstance(default, bool):
                control = make_checkbox(self)
            elif isinstance(default, int):
                control = make_spin(self)
                control.setRange(1, 6)
            elif key == "festival_reminder_mode":
                control = QComboBox(self)
                control.addItem("按每日次数", "times"); control.addItem("自定义时间", "custom")
            elif key.startswith("festival_custom_quotes"):
                control = QPlainTextEdit(self)
                control.setMinimumHeight(110)
            else:
                control = QLineEdit(self)
                if key == "festival_birthday":
                    control.setPlaceholderText("MM-DD（可留空）")
                    control.setMaxLength(5)
            self.controls[key] = control
            control.setAccessibleName(label)
            card.add_row(label, control, hint, expand=True)
        self.error = self.add_note("")
        self.add_note("默认不自动提醒、不发声。设置取消仅还原偏好，不撤销已触发状态。生日只存本机，无新增网络请求；不提供未接通的节日动画开关。")
        self._load()
        for control in self.controls.values():
            signal = control.toggled if isinstance(control, QCheckBox) else control.valueChanged if isinstance(control, QSpinBox) else control.currentIndexChanged if isinstance(control, QComboBox) else control.textChanged
            signal.connect(self._changed)

    def _load(self):
        for key, control in self.controls.items():
            control.blockSignals(True)
            value = self.host.config.get(key)
            if isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QSpinBox):
                control.setValue(int(value))
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(value))
            elif isinstance(control, QPlainTextEdit):
                control.setPlainText(str(value or ""))
            else:
                control.setText(str(value or ""))
            control.blockSignals(False)
        self._dependencies()

    def _dependencies(self):
        enabled = self.controls["festival_reminder_enabled"].isChecked()
        custom = self.controls["festival_reminder_mode"].currentData() == "custom"
        self.controls["festival_reminder_count"].setEnabled(enabled and not custom)
        self.controls["festival_reminder_times"].setEnabled(enabled and custom)
        for key in ("festival_birthday", "festival_reminder_mode", "festival_reminder_speak"):
            self.controls[key].setEnabled(enabled)

    def _changed(self, _value=None):
        self.error.clear()
        for key, control in self.controls.items():
            value = control.isChecked() if isinstance(control, QCheckBox) else control.value() if isinstance(control, QSpinBox) else control.currentData() if isinstance(control, QComboBox) else control.toPlainText() if isinstance(control, QPlainTextEdit) else control.text()
            if key == "festival_birthday" and value and not clean_birthday(value):
                self.error.setText("生日需为有效MM-DD；当前输入未采用，保留上次有效值。")
                continue
            self.host.config.set(key, value)
        self._dependencies()
        if self.runtime:
            self.runtime.preferences_changed(self.slot)
        self.changed.emit()

    def dirty(self):
        return any(self.host.config.get(k) != v for k, v in self._initial.items())

    def confirm_save(self):
        self._initial = {k: self.host.config.get(k) for k in self._initial}

    def discard_changes(self):
        for key, value in self._initial.items():
            self.host.config.set(key, value)
        self._load()
        self.error.clear()
        if self.runtime:
            self.runtime.preferences_changed(self.slot)
        self.changed.emit()

    def keywords(self):
        return ["节日", "农历", "节气", "生日", "西方", "提醒", "festival", "birthday"]
