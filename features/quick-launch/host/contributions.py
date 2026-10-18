# -*- coding: utf-8 -*-
"""快捷启动包的贡献描述：五个固定菜单槽 + 设置面板。"""

from __future__ import annotations

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.quick-launch"
SLOTS = 5


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def _menu_factory(index: int):
    def factory(menu, handle):
        from pet.context_menus.shared import add_action

        return add_action(
            menu,
            f"快捷启动 {index + 1}（包）",
            f"quick_launch_{index + 1}",
            lambda: _safe(handle),
            close_on_trigger=True,
        )

    return factory


def settings_factory(context, parent=None):
    from .contribution_settings import QuickLaunchSettings

    return QuickLaunchSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        tuple(
            Contribution(f"launch_{index + 1}", "menu", command=f"launch_{index + 1}", group="interaction", order=index * 10, factory=_menu_factory(index))
            for index in range(SLOTS)
        ),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
