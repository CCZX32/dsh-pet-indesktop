from __future__ import annotations

import logging
import random

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.media import talk_images
from petcore.ui.settings.base import SettingsPage, make_checkbox
from petcore.ui.settings.text_lines import format_lines, parse_lines

logger = logging.getLogger("petcore.features.click-talk")


class ClickTalkRuntime:
    def __init__(self, context):
        self.context = context
        self._cancel = None
        self._rng = random.Random()
        self.commands = {}

    def start(self) -> None:
        interaction = getattr(self.context.ports, "interaction", None)
        if interaction is not None:
            self._cancel = interaction.on_click(self.context.owner, self._on_click)

    def _on_click(self, _window) -> None:
        config = getattr(_window, "config", None) or getattr(self.context.host, "config", None)
        if config is None or not bool(config.get("click_talk_enabled")):
            return
        texts = [
            str(item)
            for item in (config.get("click_talk_texts") or [])
            if str(item).strip()
        ]
        if not texts:
            texts = [
                str(item)
                for item in (config.get("self_talk_texts") or [])
                if str(item).strip()
            ]
        if not texts:
            return
        presentation = self.context.ports.presentation
        binder = getattr(presentation, "for_window", None)
        if callable(binder):
            presentation = binder(_window)
        if presentation is None:
            return
        try:
            directory, images = talk_images.configured_images(config)
            chance = talk_images.image_chance(config)
            choice = talk_images.pick_choice(self._rng, texts, images, chance)
            shown = False
            if choice is not None and choice[0] == "image":
                caption = self._rng.choice(texts)
                show_image = getattr(presentation, "show_image", None)
                if callable(show_image):
                    shown = bool(
                        show_image(
                            choice[1],
                            caption,
                            duration_ms=3200,
                            scale=talk_images.image_scale(config) / 100.0,
                        )
                    )
                text = caption
            else:
                text = choice[1] if choice is not None else self._rng.choice(texts)
            if not shown:
                presentation.say(text, duration_ms=3200, force=True)
            logger.info(
                "click-talk kind=%s dir=%s images=%d shown=%s",
                choice[0] if choice else "none",
                directory,
                len(images),
                shown,
            )
        except Exception:
            logger.exception("click-talk failed")
            try:
                presentation.say(self._rng.choice(texts), duration_ms=3200, force=True)
            except Exception:
                logger.debug("click-talk fallback failed", exc_info=True)

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    def close(self) -> None:
        self.stop()


class ClickTalkPage(SettingsPage):
    title = "点击台词"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = self._snapshot()
        card = self.section("点击反馈")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(bool(self.config().get("click_talk_enabled")))
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("点击时随机说话", self.enabled, "点击桌宠时在气泡里显示一条随机台词。")
        self.texts = QPlainTextEdit(self)
        self.texts.setPlaceholderText("每行一条台词")
        self.texts.setMinimumHeight(120)
        self.texts.setPlainText(format_lines(self.config().get("click_talk_texts") or []))
        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(250)
        self._text_timer.timeout.connect(self._on_changed)
        self.texts.textChanged.connect(lambda: self._text_timer.start())
        card.add_row("候选台词", self.texts, "每行一条；留空则不显示。", expand=True)
        self.add_note("与「自言自语」独立：这里只响应点击，不会定时冒泡。")

    def config(self):
        return self.host.config

    def _snapshot(self) -> dict:
        return {
            "enabled": bool(self.config().get("click_talk_enabled")),
            "texts": list(self.config().get("click_talk_texts") or []),
        }

    def _current(self) -> dict:
        return {"enabled": self.enabled.isChecked(), "texts": parse_lines(self.texts.toPlainText())}

    def _on_changed(self, *_args) -> None:
        values = self._current()
        config = self.config()
        config.set("click_talk_enabled", values["enabled"])
        config.set("click_talk_texts", list(values["texts"]))
        self.changed.emit()

    def dirty(self) -> bool:
        return self._current() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self._snapshot()

    def discard_changes(self) -> None:
        config = self.config()
        config.set("click_talk_enabled", self._initial["enabled"])
        config.set("click_talk_texts", list(self._initial["texts"]))
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial["enabled"])
        self.enabled.blockSignals(False)
        self.texts.blockSignals(True)
        self.texts.setPlainText(format_lines(self._initial["texts"]))
        self.texts.blockSignals(False)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["点击", "台词", "气泡", "click talk", "bubble"]


def create_host(_context):
    return FeatureDefinition(
        owner="fun.click-talk",
        contributions=(
            Contribution(
                kind="settings_page",
                id="click_talk",
                data={"host_page": "interaction", "title": "点击台词", "order": 610, "icon": "chat"},
            ),
        ),
        runtime_factory=ClickTalkRuntime,
        settings_factory=ClickTalkPage,
    )
