# -*- coding: utf-8 -*-
"""日常台词包的贡献描述。"""

from __future__ import annotations

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.persona-phrases"


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def phrase_menu(menu, handle):
    from pet.context_menus.shared import add_action

    return add_action(menu, "今日台词（包）", "persona_phrase", lambda: _safe(handle), close_on_trigger=True)


def settings_factory(context, parent=None):
    from .contribution_settings import PersonaSettings

    return PersonaSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        (Contribution("today", "menu", command="today", group="interaction", factory=phrase_menu),),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
