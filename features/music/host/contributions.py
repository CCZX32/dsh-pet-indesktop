# -*- coding: utf-8 -*-
"""音乐启动器包的贡献描述：四个播放器菜单 + 设置面板。"""

from __future__ import annotations

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.music"

_PLAYERS = (
    ("netease", "网易云音乐"),
    ("qqmusic", "QQ音乐"),
    ("kugou", "酷狗音乐"),
    ("soda", "汽水音乐"),
)


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def _menu_factory(key: str, label: str):
    def factory(menu, handle):
        from pet.context_menus.shared import add_action

        return add_action(menu, f"{label}（包）", f"music_{key}", lambda: _safe(handle), close_on_trigger=True)

    return factory


def settings_factory(context, parent=None):
    from .contribution_settings import MusicSettings

    return MusicSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        tuple(
            Contribution(key, "menu", command=key, group="interaction", order=index * 10, factory=_menu_factory(key, label))
            for index, (key, label) in enumerate(_PLAYERS)
        ),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
