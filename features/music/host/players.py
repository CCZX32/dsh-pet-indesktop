# -*- coding: utf-8 -*-
"""播放器发现（纯标准库、有界扫描、进程内缓存）。

包不导入 Core 的 ``music_players``：注册表与搜索都自带一份，范围也更保守——
只扫常见安装根目录的三层，不做全盘递归。找不到就返回 ``None``，由 Runtime 弹
一条可照做的提示。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

PLAYERS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "netease": ("网易云音乐", "cloudmusic.exe", ("CloudMusic", "网易云音乐", "Netease")),
    "qqmusic": ("QQ音乐", "QQMusic.exe", ("QQMusic", "QQ音乐")),
    "kugou": ("酷狗音乐", "KuGou.exe", ("KuGou", "KGMusic", "酷狗音乐")),
    "soda": ("汽水音乐", "SodaMusic.exe", ("SodaMusic", "Soda Music", "汽水音乐")),
}

_MAX_DEPTH = 3
_MAX_ENTRIES = 512

#: 版本化安装布局：这些父目录下再多看一层版本号子目录。
_VERSIONED_PARENTS = {"soda": ("Soda Music", "SodaMusic")}

_cache: dict[str, str | None] = {}


def _roots() -> tuple[Path, ...]:
    roots = [Path("D:/"), Path("C:/"), Path("C:/Program Files"), Path("C:/Program Files (x86)")]
    for variable in ("LOCALAPPDATA", "APPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    return tuple(root for root in roots if root.is_dir())


def _bounded_files(root: Path, depth: int = _MAX_DEPTH):
    """深度优先枚举，条目数与深度都有上界。"""
    stack = [(root, 0)]
    seen = 0
    while stack and seen < _MAX_ENTRIES:
        directory, level = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > _MAX_ENTRIES:
                break
            try:
                if entry.is_file():
                    yield entry
                elif entry.is_dir() and level < depth:
                    stack.append((entry, level + 1))
            except OSError:
                continue


def find_player(player_key: str, manual_path: str = "") -> str | None:
    if player_key not in PLAYERS:
        return None
    manual = str(manual_path or "").strip()
    if manual:
        path = Path(manual).expanduser()
        return str(path) if path.is_file() else None
    if player_key in _cache:
        return _cache[player_key]

    label, exe_name, parents = PLAYERS[player_key]
    found: str | None = None
    for root in _roots():
        for parent in parents:
            base = root / parent
            if not base.is_dir():
                continue
            target = base / exe_name
            if target.is_file():
                found = str(target)
                break
            if player_key in _VERSIONED_PARENTS and parent in _VERSIONED_PARENTS[player_key]:
                for candidate in _bounded_files(base, depth=1):
                    if candidate.name.lower() == exe_name.lower():
                        found = str(candidate)
                        break
            if found is None:
                for candidate in _bounded_files(base):
                    if candidate.name.lower() == exe_name.lower():
                        found = str(candidate)
                        break
            if found is not None:
                break
        if found is not None:
            break
    if found is None:
        _LOG.debug("没有找到播放器：%s", label)
    _cache[player_key] = found
    return found


def player_label(player_key: str) -> str:
    return PLAYERS.get(player_key, (player_key, "", ()))[0]
