# -*- coding: utf-8 -*-
"""官方节日提醒 in-process 插件（Phase 2 的唯一具名消费者）。

包本身保持轻量：清单与 ID 直接可用，插件类按需惰性导出——导入本包不应把
``pet.festival_service`` 与其五份文案表（约 2.95MB）带进启动路径。
"""

from __future__ import annotations

from .manifest import FESTIVAL_MANIFEST, FESTIVAL_PLUGIN_ID

__all__ = ["FESTIVAL_MANIFEST", "FESTIVAL_PLUGIN_ID", "FestivalReminderPlugin"]


def __getattr__(name: str):
    if name == "FestivalReminderPlugin":
        from .plugin import FestivalReminderPlugin

        return FestivalReminderPlugin
    raise AttributeError(name)
