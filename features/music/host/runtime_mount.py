# -*- coding: utf-8 -*-
"""音乐启动器 Runtime：四个命令，各自在后台线程里发现并启动播放器。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

from .config import MusicConfig
from .players import find_player, player_label

_LOG = logging.getLogger(__name__)


def _open_path(path: str) -> None:
    """启动用户自己安装的播放器（受控路径，来自包自己的搜索/手填）。"""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - 路径来自受控播放器注册表
    else:
        subprocess.Popen([path])  # noqa: S603 - 同上


class MusicRuntime:
    def __init__(self, context):
        self.context = context
        self.config = MusicConfig(context)
        self.commands = {key: (lambda key=key: self.launch(key)) for key in ("netease", "qqmusic", "kugou", "soda")}
        self._closed = False

    def launch(self, player_key: str) -> None:
        if self._closed:
            return
        label = player_label(player_key)
        manual = self.config.manual_path(player_key)

        def work() -> None:
            try:
                exe = find_player(player_key, manual)
            except Exception:
                _LOG.exception("播放器发现失败：%s", player_key)
                self._bubble(f"找不到{label}：可在 扩展设置 → 音乐启动器 里指定程序位置")
                return
            if not exe:
                self._bubble(f"找不到{label}：可在 扩展设置 → 音乐启动器 里指定程序位置")
                return
            try:
                _open_path(exe)
            except Exception:
                _LOG.exception("播放器启动失败：%s", player_key)
                self._bubble(f"启动{label}失败")
                return
            self._bubble(f"已打开{label}")

        threading.Thread(target=work, name=f"music-launch-{player_key}", daemon=True).start()

    def _bubble(self, text: str) -> None:
        if self._closed:
            return
        presentation = self.context.presentation
        if presentation is not None:
            presentation.show_bubble(str(text), duration_ms=3000)

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
