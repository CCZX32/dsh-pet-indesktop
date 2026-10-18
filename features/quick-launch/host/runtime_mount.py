# -*- coding: utf-8 -*-
"""快捷启动 Runtime：五个固定命令，各自打开用户在设置里指定的程序。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from .config import MAX_ENTRIES, LaunchConfig

_LOG = logging.getLogger(__name__)


def _open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - 用户在自己的设置里选择的程序
    else:
        subprocess.Popen([path])  # noqa: S603 - 同上


class QuickLaunchRuntime:
    def __init__(self, context):
        self.context = context
        self.config = LaunchConfig(context)
        self.commands = {f"launch_{index + 1}": (lambda index=index: self.launch(index)) for index in range(MAX_ENTRIES)}
        self._closed = False

    def launch(self, index: int) -> None:
        if self._closed:
            return
        self.config.reload()
        entry = self.config.entry(index)
        if entry is None:
            self._bubble(f"快捷启动 {index + 1} 还没有配置")
            return
        label, path = entry["label"], entry["path"]

        def work() -> None:
            if not Path(path).is_file():
                self._bubble(f"找不到{label}：请在 扩展设置 → 快捷启动 里检查路径")
                return
            try:
                _open_path(path)
            except Exception:
                _LOG.exception("快捷启动失败：%s", index + 1)
                self._bubble(f"启动{label}失败")
                return
            self._bubble(f"已打开{label}")

        threading.Thread(target=work, name=f"quick-launch-{index + 1}", daemon=True).start()

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
