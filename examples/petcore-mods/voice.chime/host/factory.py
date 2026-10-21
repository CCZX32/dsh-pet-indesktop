from __future__ import annotations

from datetime import datetime

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_checkbox


class ChimeRuntime:
    def __init__(self, context):
        self.context = context
        self._speech = None
        self._handle = None
        self._last_hour = None
        self.commands = {"now": self.speak_now}

    def _engine(self):
        if self._speech is None:
            try:
                from PySide6.QtTextToSpeech import QTextToSpeech

                self._speech = QTextToSpeech()
            except Exception:
                self._speech = False
        return self._speech or None

    def _text(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        return f"现在是 {now.hour} 点 {now.minute:02d} 分。"

    def _speak(self, text: str) -> None:
        engine = self._engine()
        if engine is not None:
            try:
                engine.say(text)
                return
            except Exception:
                pass
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say(text, duration_ms=5000)

    def speak_now(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is not None and not bool(config.get("voice_chime_enabled")):
            return
        self._speak(self._text())

    def _tick(self, _dt: float) -> None:
        config = getattr(self.context.host, "config", None)
        if config is None or not bool(config.get("voice_chime_enabled")):
            return
        now = datetime.now()
        key = now.strftime("%Y-%m-%d %H")
        if now.minute == 0 and self._last_hour != key:
            self._last_hour = key
            self._speak(self._text(now))

    def start(self) -> None:
        scheduler = getattr(self.context.ports, "scheduler", None)
        if scheduler is not None:
            self._handle = scheduler.call_every(30000, lambda: self._tick(30.0))

    def stop(self) -> None:
        if self._handle and getattr(self.context.ports, "scheduler", None) is not None:
            self.context.ports.scheduler.cancel(self._handle)
            self._handle = None
        if self._speech:
            try:
                self._speech.stop()
            except Exception:
                pass

    def close(self) -> None:
        self.stop()


class ChimePage(SettingsPage):
    title = "语音报时"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("voice_chime_enabled", False))
        card = self.section("整点报时")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用语音报时", self.enabled, "每个整点用系统 TTS 报时；不可用时降级为气泡。")
        self.add_note("这里使用 Qt 系统语音，不联网。右键「立即报时」可手动试听。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("voice_chime_enabled", self.enabled.isChecked())
        self.changed.emit()

    def dirty(self) -> bool:
        return self.enabled.isChecked() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.enabled.isChecked()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial)
        self.enabled.blockSignals(False)
        self.config().set("voice_chime_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["语音", "报时", "整点", "TTS", "voice", "chime"]


def create_host(_context):
    return FeatureDefinition(
        owner="voice.chime",
        contributions=(
            Contribution(
                kind="menu",
                id="now",
                data={"label": "立即报时", "command": "now", "order": 89, "icon": "chat"},
            ),
            Contribution(
                kind="settings_page",
                id="chime",
                data={"title": "语音报时", "order": 670, "icon": "chat"},
            ),
        ),
        runtime_factory=ChimeRuntime,
        settings_factory=ChimePage,
    )
