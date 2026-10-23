"""语音报时设置页：开关、排期、台词、音色与密钥。

设置页是 Core 托管的受信 UI，允许用 QtWidgets 并直接写 ``host.config``；运行时
（``runtime.py``）只经只读 ``HostPorts.config`` 读同一批键。改动实时写进配置，
保存只负责落盘，取消/关闭把控件与配置一起回滚到打开时的快照。

音频后端、可用性与密钥状态一律经 ``HostPorts.speech`` 问 core：本页不读
``speech_*`` 配置键，也不接触任何网络/凭据实现。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from petcore.contracts.speech import SpeechError, SpeechRequest
from petcore.ui.settings.base import SettingsPage, make_checkbox

from . import quotes, schedule
from .runtime import ERROR_TEXT, PRECACHE_WINDOW_S

#: 内嵌密钥行展示的后端（与 core 的 provider 声明一致；没有该后端时整行隐藏）。
SECRET_PROVIDERS = (("doubao", "豆包"), ("mimo", "MiMo"))

CONFIG_KEYS = (
    "voice_chime_enabled",
    "voice_chime_schedule",
    "voice_chime_times",
    "voice_chime_show_bubble",
    "voice_chime_quotes",
    "voice_chime_anim",
    "voice_chime_provider",
    "voice_chime_voice",
    "voice_chime_rate",
    "voice_chime_volume",
)


def _as_flag(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "开", "开启"):
        return True
    if text in ("0", "false", "no", "off", "关", "关闭"):
        return False
    return default


def _as_number(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _reason_text(error) -> str:
    reason = str(getattr(error, "reason", "") or "unavailable")
    return ERROR_TEXT.get(reason, "语音合成失败")


class ChimePage(SettingsPage):
    title = "语音报时"
    speech_done = Signal(str)

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.group_heading("语音报时")
        self._secret_fields: dict[str, QLineEdit] = {}
        self._secret_status: dict[str, QLabel] = {}
        self._initial = self._values_from_config()

        timing = self.section("报时", level=3)
        self.enabled = make_checkbox(self)
        timing.add_row(
            "启用语音报时",
            self.enabled,
            "到点由 Core 语音合成后播放；关闭后不发任何请求。",
        )

        self.schedule = QComboBox(self)
        for key in schedule.SCHEDULES:
            self.schedule.addItem(schedule.SCHEDULE_LABELS[key], key)
        timing.add_row("报时频率", self.schedule, "整点、每 30/15/5 分钟、每分钟或自定义时间点。")

        self.times_edit = QLineEdit(self)
        self.times_edit.setPlaceholderText("如 08:00, 12:30, 21:00")
        self.times_edit.setMinimumWidth(240)
        timing.add_row(
            "自定义时间点",
            self.times_edit,
            "仅在报时频率选「自定义时间点」时生效；逗号分隔，写得不对的时间会被忽略。",
        )

        self.bubble = make_checkbox(self)
        timing.add_row(
            "同时显示气泡",
            self.bubble,
            "报时文字也会出现在桌宠气泡里；声音由 Core 的语音通道播放。",
        )

        self.animation = QLineEdit(self)
        self.animation.setPlaceholderText("如 悠闲哼歌；留空则不播放动画")
        timing.add_row("报时动画", self.animation, "报时瞬间播放一次动作动画；留空表示不动画。")

        script = self.section("台词", level=3)
        self.quotes_edit = QPlainTextEdit(self)
        self.quotes_edit.setPlaceholderText("一行一条；留空则使用内置中文台词库")
        self.quotes_edit.setMinimumHeight(120)
        script.add_row(
            "自定义台词",
            self.quotes_edit,
            "报时后念一句；每天换一套顺序，同一天不重复。留空使用内置库。",
            expand=True,
        )

        voice = self.section("声音", level=3)
        self.provider = QComboBox(self)
        self.provider.setMinimumWidth(220)
        voice.add_row(
            "合成后端",
            self.provider,
            "可用后端由 Core 的语音服务提供；未配置密钥的后端会回退到 Core 的默认链。",
        )

        self.voice_name = QLineEdit(self)
        self.voice_name.setPlaceholderText("留空 = 该后端的默认音色")
        voice.add_row("音色", self.voice_name, "填后端自己的音色名；留空跟随后端默认值。")

        self.rate = QDoubleSpinBox(self)
        self.rate.setRange(0.5, 2.0)
        self.rate.setSingleStep(0.1)
        self.rate.setDecimals(1)
        self.rate.setSuffix(" ×")
        voice.add_row("语速", self.rate, "1.0 是正常语速；0.5 最慢，2.0 最快。")

        self.volume = QDoubleSpinBox(self)
        self.volume.setRange(0.0, 1.0)
        self.volume.setSingleStep(0.1)
        self.volume.setDecimals(1)
        voice.add_row("音量", self.volume, "相对音量；系统音量仍然生效。")

        preview_row = QWidget(self)
        preview_layout = QHBoxLayout(preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        self.preview_button = QPushButton("试听", preview_row)
        self.preview_status = QLabel("", preview_row)
        self.preview_status.setObjectName("settingHint")
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_button)
        preview_layout.addWidget(self.preview_status, 1)
        voice.add_row("试听", preview_row, "按当前设置念一次现在的时间。", expand=True)

        secrets = self.section("密钥", level=3)
        for provider_id, label in SECRET_PROVIDERS:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            field = QLineEdit(row)
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText("只在保存时写入系统钥匙串")
            field.setMinimumWidth(200)
            button = QPushButton("保存", row)
            status = QLabel("", row)
            status.setObjectName("settingHint")
            button.clicked.connect(
                lambda _checked=False, pid=provider_id: self._save_secret(pid)
            )
            row_layout.addWidget(field, 1)
            row_layout.addWidget(button)
            row_layout.addWidget(status)
            self._secret_fields[provider_id] = field
            self._secret_status[provider_id] = status
            secrets.add_row(
                f"{label} 密钥",
                row,
                "只用于该后端的语音合成；保存后不回显，保存在系统钥匙串里。",
                expand=True,
            )

        self.add_note(
            f"报时前 {int(PRECACHE_WINDOW_S)} 秒会提前合成，到点直接出声；"
            "免打扰期间只跳过声音，不做补播。合成失败会在气泡里说明原因。"
        )

        self._fill_providers(self._initial["voice_chime_provider"])
        self._load_widgets(self._initial)
        self._refresh_secret_status()
        self._connect()
        self._refresh_time_enabled()

    # ------------------------------------------------------------ 配置
    def config(self):
        return self.host.config

    def _speech(self):
        ports = getattr(self.host, "ports", None)
        return getattr(ports, "speech", None)

    def _values_from_config(self) -> dict:
        config = self.config()
        return {
            "voice_chime_enabled": _as_flag(config.get("voice_chime_enabled", False), False),
            "voice_chime_schedule": schedule.normalize_schedule(
                config.get("voice_chime_schedule", "hourly")
            ),
            "voice_chime_times": list(
                schedule.parse_times(config.get("voice_chime_times", []))
            ),
            "voice_chime_show_bubble": _as_flag(
                config.get("voice_chime_show_bubble", True), True
            ),
            "voice_chime_quotes": quotes.normalize_quotes(
                config.get("voice_chime_quotes", [])
            ),
            "voice_chime_anim": str(config.get("voice_chime_anim", "悠闲哼歌") or "").strip(),
            "voice_chime_provider": str(config.get("voice_chime_provider", "") or "").strip(),
            "voice_chime_voice": str(config.get("voice_chime_voice", "") or "").strip(),
            "voice_chime_rate": _as_number(config.get("voice_chime_rate", 1.0), 1.0, 0.5, 2.0),
            "voice_chime_volume": _as_number(
                config.get("voice_chime_volume", 1.0), 1.0, 0.0, 1.0
            ),
        }

    def _collect(self) -> dict:
        return {
            "voice_chime_enabled": self.enabled.isChecked(),
            "voice_chime_schedule": schedule.normalize_schedule(
                self.schedule.currentData()
            ),
            "voice_chime_times": list(schedule.parse_times(self.times_edit.text())),
            "voice_chime_show_bubble": self.bubble.isChecked(),
            "voice_chime_quotes": quotes.normalize_quotes(self.quotes_edit.toPlainText()),
            "voice_chime_anim": self.animation.text().strip(),
            "voice_chime_provider": str(self.provider.currentData() or "").strip(),
            "voice_chime_voice": self.voice_name.text().strip(),
            "voice_chime_rate": round(float(self.rate.value()), 1),
            "voice_chime_volume": round(float(self.volume.value()), 1),
        }

    def _write_config(self, values: dict) -> None:
        config = self.config()
        for key in CONFIG_KEYS:
            config.set(key, values[key])

    def _load_widgets(self, values: dict) -> None:
        widgets = (
            self.enabled,
            self.schedule,
            self.times_edit,
            self.bubble,
            self.animation,
            self.quotes_edit,
            self.provider,
            self.voice_name,
            self.rate,
            self.volume,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.enabled.setChecked(bool(values["voice_chime_enabled"]))
            self.schedule.setCurrentIndex(
                max(0, self.schedule.findData(values["voice_chime_schedule"]))
            )
            self.times_edit.setText(", ".join(values["voice_chime_times"]))
            self.bubble.setChecked(bool(values["voice_chime_show_bubble"]))
            self.animation.setText(values["voice_chime_anim"])
            self.quotes_edit.setPlainText("\n".join(values["voice_chime_quotes"]))
            self._select_provider(values["voice_chime_provider"])
            self.voice_name.setText(values["voice_chime_voice"])
            self.rate.setValue(float(values["voice_chime_rate"]))
            self.volume.setValue(float(values["voice_chime_volume"]))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _select_provider(self, provider_id: str) -> None:
        index = self.provider.findData(provider_id)
        self.provider.setCurrentIndex(index if index >= 0 else 0)

    def _fill_providers(self, current: str) -> None:
        """后端下拉：第一项是「跟随 Core 设置」，其余由 Core 的语音端口声明。"""
        self.provider.blockSignals(True)
        try:
            self.provider.clear()
            self.provider.addItem("跟随 Core 设置", "")
            speech = self._speech()
            infos = ()
            if speech is not None:
                try:
                    infos = speech.providers()
                except Exception:  # noqa: BLE001 - 后端列表读不到就只留默认项
                    infos = ()
            for info in infos:
                provider_id = str(getattr(info, "id", "") or "").strip()
                if not provider_id:
                    continue
                label = str(getattr(info, "label", "") or provider_id)
                if not bool(getattr(info, "available", True)):
                    reason = str(getattr(info, "reason", "") or "")
                    label += "（未配置密钥）" if reason == "auth" else "（不可用）"
                self.provider.addItem(label, provider_id)
            if current and self.provider.findData(current) < 0:
                # 配置里记着的后端已不在清单里：保留一项，避免一打开就「脏」。
                self.provider.addItem(f"{current}（未识别）", current)
        finally:
            self.provider.blockSignals(False)

    # ------------------------------------------------------------ 保存语义
    def dirty(self) -> bool:
        return self._collect() != self._initial

    def confirm_save(self) -> None:
        values = self._collect()
        self._write_config(values)
        self._initial = values

    def discard_changes(self) -> None:
        self._load_widgets(self._initial)
        self._write_config(self._initial)
        self._refresh_time_enabled()
        self.preview_status.setText("")
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["语音", "报时", "整点", "台词", "音色", "试听", "chime", "voice"]

    # ------------------------------------------------------------ 交互
    def _connect(self) -> None:
        self.enabled.toggled.connect(self._on_edit)
        self.schedule.currentIndexChanged.connect(self._on_schedule_changed)
        self.times_edit.textChanged.connect(self._on_edit)
        self.bubble.toggled.connect(self._on_edit)
        self.animation.textChanged.connect(self._on_edit)
        self.quotes_edit.textChanged.connect(self._on_edit)
        self.provider.currentIndexChanged.connect(self._on_edit)
        self.voice_name.textChanged.connect(self._on_edit)
        self.rate.valueChanged.connect(self._on_edit)
        self.volume.valueChanged.connect(self._on_edit)
        self.preview_button.clicked.connect(self._preview)
        self.speech_done.connect(self._on_speech_done)

    def _on_edit(self, *_args) -> None:
        self._write_config(self._collect())
        self.changed.emit()

    def _on_schedule_changed(self, *_args) -> None:
        self._refresh_time_enabled()
        self._on_edit()

    def _refresh_time_enabled(self) -> None:
        self.times_edit.setEnabled(self.schedule.currentData() == "custom")

    def _refresh_secret_status(self) -> None:
        speech = self._speech()
        for provider_id, label in self._secret_status.items():
            if speech is None:
                label.setText("语音端口不可用")
                continue
            try:
                status = speech.secret_status(provider_id)
            except Exception as exc:  # noqa: BLE001 - 状态行不许把页面打崩
                label.setText(f"读取失败：{type(exc).__name__}")
                continue
            label.setText("已配置" if status.get("api_key") else "未配置")

    def _save_secret(self, provider_id: str) -> None:
        field = self._secret_fields[provider_id]
        value = field.text().strip()
        speech = self._speech()
        if speech is None:
            self.preview_status.setText("语音端口不可用：请更新 core 后再试")
            return
        try:
            speech.set_secret(provider_id, "api_key", value)
        except (SpeechError, ValueError) as exc:
            self.preview_status.setText(f"密钥保存失败：{exc}")
            return
        except Exception as exc:  # noqa: BLE001 - 钥匙串异常要可见
            self.preview_status.setText(f"密钥保存失败：{type(exc).__name__}")
            return
        field.clear()
        self._refresh_secret_status()
        self.preview_status.setText("密钥已存入系统钥匙串")

    def _preview(self) -> None:
        speech = self._speech()
        if speech is None:
            self.preview_status.setText("语音端口不可用：请更新 core 后再试")
            return
        now = datetime.now()
        values = self._collect()
        quote = schedule.pick_quote(
            quotes.pool(values["voice_chime_quotes"]),
            now,
            values["voice_chime_schedule"],
            values["voice_chime_times"],
        )
        request = SpeechRequest(
            text=quotes.spoken_text(now, quote),
            provider=values["voice_chime_provider"],
            voice=values["voice_chime_voice"],
            rate=values["voice_chime_rate"],
            volume=values["voice_chime_volume"],
        )
        self.preview_button.setEnabled(False)
        self.preview_status.setText("正在合成试听…")
        try:
            speech.speak(
                request,
                on_done=lambda result: self._emit_preview(
                    f"试听已开始（{getattr(result, 'voice', '') or '默认音色'}）"
                ),
                on_error=lambda error: self._emit_preview(
                    f"试听失败：{_reason_text(error)}"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 端口异常同样要可见
            self.preview_button.setEnabled(True)
            self.preview_status.setText(f"试听失败：{type(exc).__name__}")

    def _emit_preview(self, text: str) -> None:
        try:
            self.speech_done.emit(str(text))
        except RuntimeError:
            # 设置窗口在合成期间被销毁：信号对象已失效，丢弃结果即可。
            pass

    def _on_speech_done(self, text: str) -> None:
        self.preview_status.setText(text)
        self.preview_button.setEnabled(True)
