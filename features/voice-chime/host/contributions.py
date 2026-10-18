# -*- coding: utf-8 -*-
"""语音报时包的贡献描述：一个手动报时菜单 + 设置面板。"""

from __future__ import annotations

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.voice-chime"


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def chime_menu(menu, handle):
    from pet.context_menus.shared import add_action

    return add_action(menu, "立即报时（包）", "voice_chime_package", lambda: _safe(handle), close_on_trigger=True)


def settings_factory(context, parent=None):
    from .contribution_settings import VoiceChimeSettings

    return VoiceChimeSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        (Contribution("now", "menu", command="now", group="interaction", factory=chime_menu),),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
