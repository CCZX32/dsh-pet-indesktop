from __future__ import annotations

import logging
import random

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit, QSpinBox

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.media import talk_images
from petcore.ui.settings.base import SettingsPage, make_checkbox
from petcore.ui.settings.text_lines import format_lines, parse_lines

logger = logging.getLogger("petcore.features.self-talk")

#: 出图概率默认值（与 ``petcore.config.DEFAULTS["self_talk_image_chance"]`` 一致）。
DEFAULT_IMAGE_CHANCE = talk_images.image_chance({})


class SelfTalkRuntime:
    def __init__(self, context):
        self.context = context
        self._handle = None
        self._rng = random.Random()
        self.commands = {}

    def start(self) -> None:
        self._schedule()

    def _schedule(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is None or not bool(config.get("self_talk_enabled")):
            return
        low = float(config.get("self_talk_min") or 20)
        high = max(low, float(config.get("self_talk_max") or 60))
        delay_ms = int(self._rng.uniform(low, high) * 1000)
        self._handle = self.context.ports.scheduler.call_later(delay_ms, self._speak)

    def _speak(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is None or not bool(config.get("self_talk_enabled")):
            return
        try:
            texts = [
                str(item)
                for item in (config.get("self_talk_texts") or [])
                if str(item).strip()
            ]
            if not texts:
                return
            presentation = self.context.ports.presentation
            if presentation is None:
                return
            directory, images = talk_images.configured_images(config)
            chance = talk_images.image_chance(config, DEFAULT_IMAGE_CHANCE)
            choice = talk_images.pick_choice(self._rng, texts, images, chance)
            if choice is None:
                return
            kind, value = choice
            duration_ms = int(float(config.get("self_talk_duration") or 5) * 1000)
            shown = False
            if kind == "image":
                caption = self._rng.choice(texts)
                shown = self._show_image(
                    presentation,
                    value,
                    caption,
                    duration_ms,
                    talk_images.image_scale(config),
                )
            if not shown:
                text = value if kind == "text" else self._rng.choice(texts)
                presentation.say(text, duration_ms=duration_ms)
            logger.info(
                "self-talk kind=%s dir=%s images=%d shown=%s",
                kind,
                directory,
                len(images),
                shown,
            )
        except Exception:
            logger.exception("self-talk failed")
        finally:
            self._schedule()

    def _show_image(
        self,
        presentation,
        path,
        caption: str,
        duration_ms: int,
        scale: int,
    ) -> bool:
        show_image = getattr(presentation, "show_image", None)
        if not callable(show_image):
            return False
        try:
            return bool(
                show_image(
                    path,
                    caption,
                    duration_ms=duration_ms,
                    scale=scale / 100.0,
                )
            )
        except Exception:
            logger.exception("self-talk image failed: %s", path)
            return False

    def stop(self) -> None:
        if self._handle:
            self.context.ports.scheduler.cancel(self._handle)
            self._handle = None

    def close(self) -> None:
        self.stop()


class SelfTalkPage(SettingsPage):
    title = "自言自语"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = self._snapshot()
        card = self.section("节奏")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(bool(self.config().get("self_talk_enabled")))
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用自言自语气泡", self.enabled, "桌宠偶尔显示一条随机短句。")
        self.min_spin = QSpinBox(self)
        self.min_spin.setRange(1, 3600)
        self.min_spin.setSuffix(" 秒")
        self.min_spin.setValue(int(float(self.config().get("self_talk_min") or 20)))
        self.min_spin.valueChanged.connect(self._on_changed)
        card.add_row("最短间隔", self.min_spin, "上一条气泡消失后的最短空闲时间。")
        self.max_spin = QSpinBox(self)
        self.max_spin.setRange(1, 3600)
        self.max_spin.setSuffix(" 秒")
        self.max_spin.setValue(int(float(self.config().get("self_talk_max") or 60)))
        self.max_spin.valueChanged.connect(self._on_changed)
        card.add_row("最长间隔", self.max_spin, "上一条气泡消失后的最长空闲时间。")
        self.duration_spin = QSpinBox(self)
        self.duration_spin.setRange(1, 120)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setValue(int(float(self.config().get("self_talk_duration") or 5)))
        self.duration_spin.valueChanged.connect(self._on_changed)
        card.add_row("显示时间", self.duration_spin, "每条气泡保持显示的时间。")
        self.texts = QPlainTextEdit(self)
        self.texts.setPlaceholderText("每行一条台词")
        self.texts.setMinimumHeight(120)
        self.texts.setPlainText(format_lines(self.config().get("self_talk_texts") or []))
        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(250)
        self._text_timer.timeout.connect(self._on_changed)
        self.texts.textChanged.connect(lambda: self._text_timer.start())
        card.add_row("候选台词", self.texts, "每行一条；留空则不显示。", expand=True)

        self.add_note("配图目录、图片大小与出图概率在「互动与物理 → 彩蛋与配图」统一调整。")

    def config(self):
        return self.host.config

    def _snapshot(self) -> dict:
        config = self.config()
        return {
            "enabled": bool(config.get("self_talk_enabled")),
            "min": int(float(config.get("self_talk_min") or 20)),
            "max": int(float(config.get("self_talk_max") or 60)),
            "duration": int(float(config.get("self_talk_duration") or 5)),
            "texts": list(config.get("self_talk_texts") or []),
        }

    def _current(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "min": int(self.min_spin.value()),
            "max": int(self.max_spin.value()),
            "duration": int(self.duration_spin.value()),
            "texts": parse_lines(self.texts.toPlainText()),
        }

    def _on_changed(self, *_args) -> None:
        values = self._current()
        config = self.config()
        config.set("self_talk_enabled", values["enabled"])
        config.set("self_talk_min", values["min"])
        config.set("self_talk_max", max(values["min"], values["max"]))
        config.set("self_talk_duration", values["duration"])
        config.set("self_talk_texts", list(values["texts"]))
        runtime = getattr(self.host, "features", None)
        if runtime is not None:
            feature = runtime.features.get("fun.self-talk")
            if feature is not None and feature.runtime is not None:
                feature.runtime.stop()
                feature.runtime.start()
        self.changed.emit()

    def dirty(self) -> bool:
        return self._current() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self._snapshot()

    def discard_changes(self) -> None:
        config = self.config()
        config.set("self_talk_enabled", self._initial["enabled"])
        config.set("self_talk_min", self._initial["min"])
        config.set("self_talk_max", self._initial["max"])
        config.set("self_talk_duration", self._initial["duration"])
        config.set("self_talk_texts", list(self._initial["texts"]))
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial["enabled"])
        self.enabled.blockSignals(False)
        for spin, key in (
            (self.min_spin, "min"),
            (self.max_spin, "max"),
            (self.duration_spin, "duration"),
        ):
            spin.blockSignals(True)
            spin.setValue(self._initial[key])
            spin.blockSignals(False)
        self.texts.blockSignals(True)
        self.texts.setPlainText(format_lines(self._initial["texts"]))
        self.texts.blockSignals(False)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return [
            "自言自语",
            "气泡",
            "台词",
            "间隔",
            "配图",
            "图片",
            "self talk",
            "bubble",
        ]


def create_host(_context):
    return FeatureDefinition(
        owner="fun.self-talk",
        contributions=(
            Contribution(
                kind="settings_page",
                id="self_talk",
                data={"host_page": "interaction", "title": "自言自语", "order": 620, "icon": "chat"},
            ),
        ),
        runtime_factory=SelfTalkRuntime,
        settings_factory=SelfTalkPage,
    )
