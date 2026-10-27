"""四个播放器的启动路径注册表：只认配置里的路径，不扫盘、不猜。

主分支会用一层浅扫去自动找安装路径（``pet/music_players.py``）；那套扫描要遍历
盘符、有几十毫秒到几秒的开销，还得处理"手填路径失效"的歧义。这里刻意收窄：
**用户没在设置里填路径就不启动**，气泡直接说明去哪儿填。键表只有这一份，
菜单、设置页与运行时都从 :data:`PLAYERS` 取。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

#: ``key -> (显示名, 可执行文件名)``；键同时是菜单命令 ``open_<key>`` 的后缀。
PLAYERS: dict[str, tuple[str, str]] = {
    "netease": ("网易云音乐", "cloudmusic.exe"),
    "qqmusic": ("QQ音乐", "QQMusic.exe"),
    "kugou": ("酷狗音乐", "KuGou.exe"),
    "soda": ("汽水音乐", "SodaMusic.exe"),
}

#: **识别用**的播放器可执行名表（小写、含 ``.exe``）。
#:
#: 与上面可启动的四个键**刻意分开**：启动需要用户填路径（不扫盘），而识别只要
#: 「这个进程是不是音乐播放器」。窗口标题源只认这张表里的人——把 VLC / mpv /
#: PotPlayer 放进来会让「用 mpv 看视频」被当成在放歌（误检），所以只收以听歌为
#: 主要用途的播放器。表外的应用不受影响（SMTC 主链路照旧，见
#: ``recognizer.decide`` 的「不猜」口径）。
KNOWN_MUSIC_EXES: frozenset[str] = frozenset(
    {
        "cloudmusic.exe",
        "qqmusic.exe",
        "kugou.exe",
        "sodamusic.exe",
        "foobar2000.exe",
        "aimp.exe",
        "winamp.exe",
        "musicbee.exe",
        "itunes.exe",
    }
)


def known_exe_names() -> frozenset[str]:
    """识别用播放器表（只读副本口径；调用方不要改）。"""
    return KNOWN_MUSIC_EXES


def _basename(value: object) -> str:
    name = str(value or "").strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1]
    return name.strip().lower()


def configured_exe_names(paths: object) -> frozenset[str]:
    """``music_player_paths`` 里配置的可执行名（小写含 ``.exe``）。

    用户显式填了路径的播放器一律算「已登记」——哪怕它不在
    :data:`KNOWN_MUSIC_EXES` 里（比如小众播放器），窗口标题源也会去读它。
    """
    if not isinstance(paths, Mapping):
        return frozenset()
    values = {_basename(path) for path in paths.values()}
    return frozenset(name for name in values if name)


def recognition_targets(paths: object, extras: object = "") -> frozenset[str]:
    """窗口标题源允许观察的可执行名 = 已知播放器 ∪ 用户配置 ∪ 额外识别名。"""
    names = set(KNOWN_MUSIC_EXES) | set(configured_exe_names(paths))
    for chunk in str(extras or "").replace("；", ",").replace("，", ",").replace("、", ",").split(","):
        name = _basename(chunk)
        if name:
            names.add(name if name.endswith(".exe") else f"{name}.exe")
    return frozenset(names)


def player_keys() -> tuple[str, ...]:
    """已注册播放器的键（注册表顺序）。"""
    return tuple(PLAYERS)


def player_label(player_key: str) -> str:
    return PLAYERS.get(str(player_key), (str(player_key), ""))[0]


def player_exe(player_key: str) -> str:
    """播放器的可执行文件名（用于在 SMTC 会话里认出它）。"""
    return PLAYERS.get(str(player_key), ("", ""))[1]


def configured_path(paths: object, player_key: str) -> str:
    """配置里该播放器的路径（``music_player_paths``）；没有就是空串。"""
    if not isinstance(paths, Mapping):
        return ""
    return str(paths.get(str(player_key)) or "").strip()


def launch(paths: object, player_key: str) -> tuple[bool, str]:
    """按配置的路径启动播放器；返回 ``(是否成功, 气泡文案)``。

    只在该键配了**真实存在的文件**时启动；没配、路径失效、启动异常都给一句
    可执行的原因，不静默失败。
    """
    key = str(player_key or "").strip()
    if key not in PLAYERS:
        return False, f"不认识的播放器：{key or '（空）'}"
    label = player_label(key)
    raw = configured_path(paths, key)
    if not raw:
        return False, f"还没有配置{label}的路径：设置 → 扩展管理 → 音乐"
    target = Path(raw).expanduser()
    try:
        exists = target.is_file()
    except OSError:
        exists = False
    if not exists:
        return False, f"{label}的路径不可用，请在设置里重新选择"
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(target)])
    except Exception:
        return False, f"启动{label}失败，请检查路径是否可执行"
    return True, f"正在打开{label}"
