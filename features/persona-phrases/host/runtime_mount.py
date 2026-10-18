# -*- coding: utf-8 -*-
"""日常台词 Runtime：一条 ``today`` 命令，按日期取一句并可选朗读。"""

from __future__ import annotations

from datetime import datetime

from .config import PersonaConfig
from .phrases import pick_phrase


class PersonaRuntime:
    def __init__(self, context):
        self.context = context
        self.config = PersonaConfig(context)
        self.commands = {"today": self.today}
        self._closed = False

    def today(self) -> None:
        if self._closed:
            return
        # 设置面板保存后无需重装/重启：命令入口现读一次偏好。
        self.config.reload()
        text = pick_phrase(datetime.now(), self.config.custom_phrases)
        if self.context.presentation is not None:
            self.context.presentation.show_bubble(text, duration_ms=5000)
        if self.config.speak and self.context.audio is not None:
            self.context.audio.speak(text)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        scheduler = self.context.scheduler
        if scheduler is not None:
            scheduler.close()
