# -*- coding: utf-8 -*-
"""语音报时 Runtime：调度在包内，合成/播放/免打扰交给 Core 唯一音频通道。"""

from __future__ import annotations

from datetime import datetime

from .config import VoiceConfig
from .schedule import clock_sentence, pick_quote, seconds_until_next


class VoiceChimeRuntime:
    def __init__(self, context):
        self.context = context
        self.config = VoiceConfig(context)
        self.commands = {"now": self.speak_now}
        self._timer = None
        self._armed = False
        self._closed = False

    def speak_now(self) -> None:
        if self._closed:
            return
        self.config.reload()
        self._emit(datetime.now())

    def _emit(self, now: datetime) -> None:
        text = clock_sentence(now) + pick_quote(now, self.config.quotes_zh, self.config.quotes_en)
        if self.config.show_bubble and self.context.presentation is not None:
            self.context.presentation.show_bubble(text, duration_ms=6000)
        audio = self.context.audio
        if audio is not None:
            audio.speak(text)

    def _schedule_next(self) -> None:
        self._cancel_timer()
        if self._closed or not self._armed or not self.config.enabled:
            return
        scheduler = self.context.scheduler
        if scheduler is None:
            return
        delay = seconds_until_next(datetime.now(), self.config.schedule, self.config.custom_times)
        self._timer = scheduler.call_later(int(delay * 1000), self._fire)

    def _fire(self) -> None:
        if self._closed or not self._armed:
            return
        self._timer = None
        self.config.reload()
        self._emit(datetime.now())
        self._schedule_next()

    def _cancel_timer(self) -> None:
        if self._timer is not None and self.context.scheduler is not None:
            self.context.scheduler.cancel(self._timer)
        self._timer = None

    def start(self) -> None:
        if self._closed:
            return
        self.config.reload()
        self._armed = True
        self._schedule_next()

    def stop(self) -> None:
        self._armed = False
        self._cancel_timer()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._armed = False
        self._cancel_timer()
        scheduler = self.context.scheduler
        if scheduler is not None:
            scheduler.close()
