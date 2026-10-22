"""media.music：当前播放 + 歌词 + 唱歌动画（feature mod 的装配点）。

运行时代码（``now_playing`` / ``lyrics`` / ``players`` / ``runtime``）不 import Qt；
只有本模块导入的设置页可以用 QtWidgets。菜单贡献与设置页一一对应：每条菜单都能在
本页找到落点（传输控制、歌词对齐、打开播放器）。
"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from . import players
from .runtime import MusicRuntime
from .settings_page import MusicPage

OWNER = "media.music"

__all__ = ["MusicPage", "MusicRuntime", "OWNER", "create_host"]

#: 传输与歌词菜单（顺序与主分支一致，后面接「打开播放器」）。
_TRANSPORT_MENU = (
    ("pause", "播放 / 暂停", "pause", 70, "play"),
    ("next", "下一首", "next", 71, "play"),
    ("prev", "上一首", "prev", 72, "play"),
    ("stop", "停止播放", "stop", 73, "pause"),
    ("lyric_align", "歌词对齐（+0.5 秒）", "lyric_align", 74, "chat"),
)


def _menu_contributions() -> tuple[Contribution, ...]:
    items = [
        Contribution(
            kind="menu",
            id=menu_id,
            data={"label": label, "command": command, "order": order, "icon": icon},
        )
        for menu_id, label, command, order, icon in _TRANSPORT_MENU
    ]
    for offset, key in enumerate(players.player_keys()):
        items.append(
            Contribution(
                kind="menu",
                id=f"open_{key}",
                data={
                    "label": f"打开{players.player_label(key)}",
                    "command": f"open_{key}",
                    "order": 80 + offset,
                    "icon": "application",
                },
            )
        )
    return tuple(items)


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=_menu_contributions()
        + (
            Contribution(
                kind="settings_page",
                id="music",
                data={"title": "音乐", "order": 680, "icon": "play"},
            ),
        ),
        runtime_factory=MusicRuntime,
        settings_factory=MusicPage,
    )
