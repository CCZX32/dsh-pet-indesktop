"""文件解读设置页：启用、进度间隔、是否写入会话。"""

from __future__ import annotations

from PySide6.QtWidgets import QSpinBox

from petcore.ui.settings.base import SettingsPage, make_checkbox

from .reader import SCAN_FILE_LIMIT, SCAN_TIME_BUDGET_S, TEXT_EXTENSIONS


class FileReaderPage(SettingsPage):
    title = "文件解读"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        config = self.config()
        self._initial = {
            "enabled": bool(config.get("file_reader_enabled", True)),
            "progress": int(config.get("file_reader_progress_seconds", 15) or 15),
            "record": bool(config.get("file_reader_record", True)),
        }

        card = self.section("拖文件解读")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial["enabled"])
        self.enabled.toggled.connect(self._on_changed)
        card.add_row(
            "启用解读",
            self.enabled,
            "把文件拖到桌宠身上时读取文本并交给 AI 解读；投喂动画与统计仍由 core 负责。",
        )

        self.progress = QSpinBox(self)
        self.progress.setRange(5, 120)
        self.progress.setSuffix(" 秒")
        self.progress.setMinimumWidth(96)
        self.progress.setKeyboardTracking(False)
        self.progress.setValue(self._initial["progress"])
        self.progress.valueChanged.connect(self._on_changed)
        card.add_row(
            "进度提示间隔",
            self.progress,
            "长文本解读期间每隔这么久冒一次进度气泡。",
        )

        self.record = make_checkbox(self)
        self.record.setChecked(self._initial["record"])
        self.record.toggled.connect(self._on_changed)
        card.add_row(
            "写入聊天记录",
            self.record,
            "关闭后只冒气泡，不把文件内容和解读写进该宠的会话。",
        )

        self.add_note(
            f"只读取文本/代码/配置类文件（{len(TEXT_EXTENSIONS)} 种后缀）；"
            f"扫描上限 {SCAN_FILE_LIMIT} 个文件 / {SCAN_TIME_BUDGET_S:.0f} 秒，"
            "单次最多读取 200000 字符。图片、PDF 等二进制文档暂不解读。"
        )
        self.add_note("本扩展绝不修改、移动或删除被拖入的文件。")

    def config(self):
        return self.host.config

    def _current(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "progress": int(self.progress.value()),
            "record": self.record.isChecked(),
        }

    def _apply(self) -> None:
        config = self.config()
        config.set("file_reader_enabled", self.enabled.isChecked())
        config.set("file_reader_progress_seconds", int(self.progress.value()))
        config.set("file_reader_record", self.record.isChecked())
        self.changed.emit()

    def _on_changed(self, _value=None) -> None:
        self._apply()

    def dirty(self) -> bool:
        return self._current() != self._initial

    def confirm_save(self) -> None:
        self._apply()
        self._initial = self._current()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.progress.blockSignals(True)
        self.record.blockSignals(True)
        self.enabled.setChecked(self._initial["enabled"])
        self.progress.setValue(self._initial["progress"])
        self.record.setChecked(self._initial["record"])
        self.enabled.blockSignals(False)
        self.progress.blockSignals(False)
        self.record.blockSignals(False)
        self._apply()

    def keywords(self) -> list[str]:
        return ["文件", "解读", "拖文件", "file", "文本", "附件"]
