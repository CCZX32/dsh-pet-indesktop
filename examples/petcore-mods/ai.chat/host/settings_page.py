"""AI 对话扩展的设置页。

这是 **受信 UI**：设置页由 Core 托管，允许通过 ``host.config``（ScopedConfig）
读写；运行时代码（``runtime.py``）不碰 Qt，只经 ``HostPorts.config`` 读配置。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from petcore.ui.chat.themes import theme_names
from petcore.ui.settings.base import SettingsPage, make_checkbox

_CUSTOM_BACKGROUND = "__custom__"
_HEX = QRegularExpression(r"^#[0-9a-fA-F]{6}$")


class AiChatPage(SettingsPage):
    title = "AI 对话"

    _KEYS = (
        "ai_service",
        "ai_model",
        "ai_system_prompt",
        "ai_vision_enabled",
        "ai_temperature",
        "ai_look_screen_auto_open",
        "chat_background",
        "chat_accent",
        "chat_follow_pet",
        "chat_always_on_top",
    )

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = {key: self.config().get(key) for key in self._KEYS}
        self._background_value = str(self._initial.get("chat_background") or "")

        card = self.section("模型")
        self.service_combo = QComboBox(self)
        self.service_combo.addItem("自动（第一个服务）", "")
        try:
            for meta in self.api().services():
                self.service_combo.addItem(meta.name or meta.service_id, meta.service_id)
        except Exception:
            pass
        index = self.service_combo.findData(str(self._initial.get("ai_service") or ""))
        self.service_combo.setCurrentIndex(index if index >= 0 else 0)
        self.service_combo.currentIndexChanged.connect(self._on_changed)
        card.add_row("对话服务", self.service_combo, "留空自动用「API 与账户」里的第一个服务。")

        self.model_edit = QLineEdit(self)
        self.model_edit.setPlaceholderText("留空用服务里的默认模型")
        self.model_edit.setText(str(self._initial.get("ai_model") or ""))
        self.model_edit.editingFinished.connect(self._on_changed)
        card.add_row("模型覆盖", self.model_edit, "只影响对话；截图提问会优先用视觉模型。")

        self.temperature_spin = QDoubleSpinBox(self)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(1)
        try:
            self.temperature_spin.setValue(float(self._initial.get("ai_temperature") or 0.7))
        except (TypeError, ValueError):
            self.temperature_spin.setValue(0.7)
        self.temperature_spin.valueChanged.connect(self._on_changed)
        card.add_row("温度", self.temperature_spin, "越高越发散，0.7 适合日常聊天。")

        card2 = self.section("人格与视觉")
        self.prompt_edit = QPlainTextEdit(self)
        self.prompt_edit.setPlaceholderText("留空使用默认人格")
        self.prompt_edit.setPlainText(str(self._initial.get("ai_system_prompt") or ""))
        self.prompt_edit.textChanged.connect(self._on_changed)
        card2.add_row("系统提示词", self.prompt_edit, "每次对话开头发给模型；支持 {name} 占位。")

        self.vision_check = make_checkbox(self)
        self.vision_check.setChecked(bool(self._initial.get("ai_vision_enabled", True)))
        self.vision_check.toggled.connect(self._on_changed)
        card2.add_row(
            "允许截图提问",
            self.vision_check,
            "截图只读取当前屏幕并直接发给模型，不写入磁盘。",
        )

        self.auto_open_check = make_checkbox(self)
        self.auto_open_check.setChecked(
            bool(self._initial.get("ai_look_screen_auto_open", False))
        )
        self.auto_open_check.toggled.connect(self._on_changed)
        card2.add_row(
            "看看屏幕后自动打开对话",
            self.auto_open_check,
            "默认只把结果同步进对话记录并用气泡回答；勾选后才主动唤出对话窗口。",
        )

        card3 = self.section("对话窗外观")
        self.background_combo = QComboBox(self)
        self._rebuild_background_options()
        self.background_combo.currentIndexChanged.connect(self._on_background_changed)
        card3.add_row(
            "背景",
            self.background_combo,
            "内置主题或本地图片；默认白色。改动会立即预览到已打开的对话窗。",
        )

        accent_row = QWidget(self)
        accent_layout = QHBoxLayout(accent_row)
        accent_layout.setContentsMargins(0, 0, 0, 0)
        accent_layout.setSpacing(6)
        self.accent_edit = QLineEdit(accent_row)
        self.accent_edit.setPlaceholderText("#326de6（留空用角色默认色）")
        self.accent_edit.setText(str(self._initial.get("chat_accent") or ""))
        self.accent_edit.setMaximumWidth(150)
        self.accent_edit.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"^#[0-9a-fA-F]{0,6}$|^$"), self.accent_edit
            )
        )
        self.accent_edit.editingFinished.connect(self._on_accent_finished)
        accent_layout.addWidget(self.accent_edit)
        self.accent_button = QPushButton("选择…", accent_row)
        self.accent_button.clicked.connect(self._pick_accent)
        accent_layout.addWidget(self.accent_button)
        self.accent_reset = QPushButton("默认", accent_row)
        self.accent_reset.clicked.connect(self._reset_accent)
        accent_layout.addWidget(self.accent_reset)
        accent_layout.addStretch(1)
        card3.add_row(
            "强调色",
            accent_row,
            "发送键、选中态与强调线；留空使用角色默认色，格式 #RRGGBB。",
        )

        self.follow_check = make_checkbox(self)
        self.follow_check.setChecked(bool(self._initial.get("chat_follow_pet", False)))
        self.follow_check.toggled.connect(self._on_changed)
        card3.add_row(
            "跟随桌宠",
            self.follow_check,
            "打开后对话窗跟着发起它的桌宠移动，优先停在桌宠右侧，放不下时切到左侧。",
        )

        self.on_top_check = make_checkbox(self)
        self.on_top_check.setChecked(
            bool(self._initial.get("chat_always_on_top", False))
        )
        self.on_top_check.toggled.connect(self._on_changed)
        card3.add_row(
            "对话窗置顶",
            self.on_top_check,
            "与标题栏的图钉按钮是同一个开关。",
        )

        self.add_note(
            "对话内容按桌宠 + 角色分别保存在本机 sessions/ 目录；密钥只在系统钥匙串。"
            "截图提问是独立的框选窗口，图片只在内存中流转，问答历史随当次采集结束。"
        )

    # ---------------------------------------------------------------- 外观控件
    def _rebuild_background_options(self) -> None:
        combo = self.background_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("默认（白色）", "")
        for key, label in theme_names():
            combo.addItem(f"内置 · {label}", f"builtin:{key}")
        value = str(self._background_value or "")
        if value and not value.startswith("builtin:"):
            combo.addItem(f"本地 · {Path(value).name}", value)
        combo.addItem("自定义图片…", _CUSTOM_BACKGROUND)
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _on_background_changed(self, _index: int) -> None:
        data = str(self.background_combo.currentData() or "")
        if data == _CUSTOM_BACKGROUND:
            path, _selected = QFileDialog.getOpenFileName(
                self,
                "选择对话窗背景",
                str(Path.home()),
                "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if not path:
                self._rebuild_background_options()
                return
            data = str(Path(path).resolve())
            self._background_value = data
            self._rebuild_background_options()
        else:
            self._background_value = data
        self._on_changed()

    def _accent_value(self) -> str:
        text = self.accent_edit.text().strip()
        if not text:
            return ""
        if not text.startswith("#"):
            text = "#" + text
        return text.lower() if _HEX.match(text).hasMatch() else ""

    def _on_accent_finished(self) -> None:
        text = self.accent_edit.text().strip()
        if text and not self._accent_value():
            self.accent_edit.setText(str(self._initial.get("chat_accent") or ""))
            return
        self._on_changed()

    def _pick_accent(self) -> None:
        current = self._accent_value() or "#326de6"
        color = QColorDialog.getColor(QColor(current), self, "选择强调色")
        if not color.isValid():
            return
        self.accent_edit.setText(color.name())
        self._on_changed()

    def _reset_accent(self) -> None:
        self.accent_edit.clear()
        self._on_changed()

    # ---------------------------------------------------------------- 数据
    def api(self):
        features = getattr(self.host, "features", None)
        ports = getattr(features, "ports", None)
        return getattr(ports, "api", None) if ports is not None else None

    def config(self):
        return self.host.config

    def apply_preview(self) -> None:
        chat = getattr(self.host, "chat", None)
        apply = getattr(chat, "apply_appearance", None)
        if not callable(apply):
            return
        apply(
            background=self._background_value,
            accent=self._accent_value(),
            always_on_top=bool(self.on_top_check.isChecked()),
            follow=bool(self.follow_check.isChecked()),
        )

    def _on_changed(self, *_args) -> None:
        config = self.config()
        config.set("ai_service", str(self.service_combo.currentData() or ""))
        config.set("ai_model", self.model_edit.text().strip())
        config.set("ai_system_prompt", self.prompt_edit.toPlainText().strip())
        config.set("ai_vision_enabled", bool(self.vision_check.isChecked()))
        config.set("ai_temperature", float(self.temperature_spin.value()))
        config.set("ai_look_screen_auto_open", bool(self.auto_open_check.isChecked()))
        config.set("chat_background", self._background_value)
        config.set("chat_accent", self._accent_value())
        config.set("chat_follow_pet", bool(self.follow_check.isChecked()))
        config.set("chat_always_on_top", bool(self.on_top_check.isChecked()))
        self.apply_preview()
        self.changed.emit()

    def dirty(self) -> bool:
        config = self.config()
        return any(
            str(config.get(key)) != str(value)
            for key, value in self._initial.items()
        )

    def _snapshot(self) -> dict:
        return {key: self.config().get(key) for key in self._KEYS}

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self._snapshot()

    def discard_changes(self) -> None:
        self._initial = self._snapshot()
        self._background_value = str(self._initial.get("chat_background") or "")
        self._rebuild_background_options()
        self.apply_preview()
        self.changed.emit()

    def keywords(self) -> list[str]:
        return [
            "AI",
            "对话",
            "聊天",
            "模型",
            "提示词",
            "温度",
            "截图",
            "视觉",
            "识屏",
            "看看屏幕",
            "截图提问",
            "自动打开",
            "背景",
            "主题",
            "强调色",
            "颜色",
            "跟随",
            "置顶",
            "chat",
        ]
