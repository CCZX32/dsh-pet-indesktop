# -*- coding: utf-8 -*-
"""节日提醒插件的清单与稳定 ID（轻量模块，不导入重服务）。"""

from __future__ import annotations

from ...config import FESTIVAL_LEGACY_CONFIG_MAP
from ...manifest import PluginManifest

FESTIVAL_PLUGIN_ID = "official.festival-reminder"

FESTIVAL_MANIFEST = PluginManifest(
    id=FESTIVAL_PLUGIN_ID,
    name="官方节日提醒",
    version="1.0.0",
    kind="in_process",
    api_version="1",
    core_requires=">=5.0.0,<6.0.0",
    dependencies=(),
    capabilities=(
        "notification.present",
        "speech.present",
        "settings.read",
        "settings.write",
        "scheduler.timer",
        "menu.contribute",
    ),
    entrypoint=None,
    default_enabled=False,
    legacy_config_map=FESTIVAL_LEGACY_CONFIG_MAP,
)

__all__ = ["FESTIVAL_MANIFEST", "FESTIVAL_PLUGIN_ID"]
