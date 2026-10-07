# -*- coding: utf-8 -*-
"""设置页「音乐播放器路径」：控件创建 / 行装配 / 保存 / 后台自动检测。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算已无余量，
本组控件与行全部在此构建（与 ``settings_file_interpret.py`` 同口径）。

**为什么需要这个设置**：右键菜单「音乐 → 打开网易云/QQ音乐给主人放歌」需要知道
播放器装在哪。``pet/music_players.py`` 会先自动搜常见目录，但实测本机网易云在
``D:\\CloudMusic``、QQ音乐在 ``D:\\QQ音乐\\QQMusic``，都不在默认位置；搜不到时菜单项
置灰，提示是「可在配置文件中手动指定路径」——在本次之前**没有任何 UI 能写这个键**
（``music_players.clear_cache`` 的 docstring 一直登记着这个缺口）。

**自动检测为什么这么写**：目录浅扫实测 6s+，绝不能放 GUI 线程（曾把菜单冻住）。
这里复用 ``music_players`` 自己的后台预热与只读缓存：点按钮 → 幂等触发预热
→ 定时轮询只读缓存 → 出结果就回填并弹一次说明。轮询超时（默认 20s）也会收尾，
不会留一个永远转的定时器。
"""

from __future__ import annotations

import logging
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton

from . import music_players
from .settings_widgets import ResourcePathPicker, SettingRow, mark_main_pet_only

log = logging.getLogger("dsh-pet-standalone")

PLAYER_KEYS = ("netease", "qqmusic")
EXE_NAME_FILTER = "可执行文件 (*.exe);;所有文件 (*)"
DETECT_POLL_MS = 300
DETECT_TIMEOUT_SECONDS = 20.0
_PICKER_ATTR = {
    "netease": "music_player_netease_picker",
    "qqmusic": "music_player_qqmusic_picker",
}
_ROW_KEY = {
    "netease": "music_player_netease",
    "qqmusic": "music_player_qqmusic",
}

_DETECT_BUTTON_LABEL = "自动检测"


def create_music_player_controls(dialog) -> None:
    """创建两个路径选择器与「自动检测」按钮（幂等）。"""
    if getattr(dialog, "music_player_detect_btn", None) is not None:
        return
    configured = dialog.config.get("music_player_paths", {})
    configured = configured if isinstance(configured, dict) else {}
    for key in PLAYER_KEYS:
        label = music_players.player_label(key)
        picker = ResourcePathPicker(
            str(configured.get(key, "") or ""),
            name_filter=EXE_NAME_FILTER,
            dialog_title=f"选择{label}的程序",
            parent=dialog,
        )
        setattr(dialog, _PICKER_ATTR[key], picker)
    button = QPushButton(_DETECT_BUTTON_LABEL, dialog)
    button.setObjectName("musicPlayerDetectButton")
    button.clicked.connect(lambda: start_detect(dialog))
    dialog.music_player_detect_btn = button
    # 两个路径键都是**进程级**（不在 PER_SLOT_SETTING_KEYS，右键菜单读 host 配置面、
    # 由 _SpriteConfig 转发到主配置）：子宠页改了不生效 ⇒ 置灰。「自动检测」按钮只
    # 服务这两行（搜到的路径填进没人读的控件），一并置灰，免得留个点了没用的入口。
    mark_main_pet_only(
        dialog,
        *(getattr(dialog, _PICKER_ATTR[key]) for key in PLAYER_KEYS),
        button,
    )


def build_music_player_rows(dialog) -> list[SettingRow]:
    """本组的设置行（由「桌宠 · 音乐关联」组直接取用，不走 claim）。"""
    rows: list[SettingRow] = []
    for key in PLAYER_KEYS:
        label = music_players.player_label(key)
        rows.append(
            SettingRow(
                _ROW_KEY[key],
                f"{label}程序",
                f"{label}的安装位置（指向可执行文件）。留空 = 自动搜索常见安装目录；"
                "填了就以它为准（文件不存在时右键菜单会提示找不到，而不是偷偷回退）。",
                getattr(dialog, _PICKER_ATTR[key]),
                stacked=True,
            )
        )
    rows.append(
        SettingRow(
            "music_player_detect",
            "自动检测播放器",
            "在后台按常见目录名搜一遍（几个盘符 + 用户目录，最多三层），找到就填进上面两行；"
            "搜索在后台做，不会卡住设置页。",
            dialog.music_player_detect_btn,
        )
    )
    return rows


def browser_media_supported() -> bool:
    """「浏览器媒体会话参与歌词」是否在本平台可用——SMTC 是 Windows 专属。"""
    return sys.platform == "win32"


def browser_media_rows(dialog) -> list[SettingRow]:
    """「浏览器媒体会话参与歌词」设置行（**仅 Windows**）。

    SMTC 是 Windows 专属能力：非 Windows 上这个开关既无效也不该出现
    （SETTINGS-CHANGE-GATES §4「永久不支持的能力不创建控件」）。控件本体也只在
    Windows 创建（``settings_pet_controls``），所以这里以「控件在不在」为准——
    与 ``cursor_hidden_passthrough`` 的处置一致，不会出现"控件在、行不在"的
    游离开关（那会被孤儿开关测试拦下）。

    hint 里如实写清代价：浏览器把网页视频也上报成音乐类型，开着就会对着视频
    显示「我在唱」并取词；网页版音乐平台需要它才有歌词。
    """
    check = getattr(dialog, "music_browser_media_check", None)
    if check is None or not browser_media_supported():
        return []
    # 与 foobar 两键同规（同一 _SOURCE_SWITCHES 组、同一读取形态）：进程级歌词源
    # 开关，子宠页写了不生效 ⇒ 置灰。控件本体建在 settings_pet_controls。
    mark_main_pet_only(dialog, check)
    return [
        SettingRow(
            "music_browser_media",
            "浏览器媒体会话参与歌词",
            "关闭时，浏览器（Edge、Chrome、Firefox 等）里播放的内容不会被当作正在"
            "播放的歌曲——浏览器把网页视频也上报成音乐类型，开着会对着视频显示"
            "「我在唱」并取词。网页版音乐平台（如网页版网易云）需要打开它才能显示歌词。",
            check,
        )
    ]


def foobar_lyrics_supported() -> bool:
    """「foobar2000 歌词」是否在本平台可用——窗口标题源走 Win32 窗口枚举。"""
    return sys.platform == "win32"


def foobar_lyrics_rows(dialog) -> list[SettingRow]:
    """「foobar2000 歌词」两行（**仅 Windows**，与 browser_media_rows 同规）。

    行文案里必须如实写清三条，否则用户会以为是"功能坏了"：

    1. **推荐路线**是给 foobar 装 SMTC 组件（如 foo_mediacontrol）——那条路走现有
       的 SMTC 采样，比窗口标题可靠得多；本开关是给不想装组件的人用的替代路线。
    2. 窗口标题分辨不出播放状态：foobar 开着但没在播时，可能仍显示上一首。
    3. 只在没有其它播放器（SMTC 在播会话）时才生效，不会抢走正在听的那首歌。
    """
    check = getattr(dialog, "foobar_lyrics_check", None)
    edit = getattr(dialog, "foobar_title_format_edit", None)
    if check is None or edit is None or not foobar_lyrics_supported():
        return []
    # 两个键都是**进程级**（不在 PER_SLOT_SETTING_KEYS，歌词源解析读主配置）：
    # 子宠页改了不生效，如实置灰（控件本体建在 settings_pet_controls）。
    mark_main_pet_only(dialog, check, edit)
    return [
        SettingRow(
            "foobar_lyrics",
            "foobar2000 歌词",
            "foobar2000 默认不向系统上报播放信息，这里改为读它的窗口标题，只在"
            "没有其它播放器在播时生效。更可靠的路线是给 foobar 装支持系统媒体控制"
            "（SMTC）的组件（如 foo_mediacontrol）——装好后本开关不需要打开。"
            "已知局限：窗口标题分辨不出它是否在播，foobar 没在播时可能仍显示上一首。",
            check,
        ),
        SettingRow(
            "foobar_title_format",
            "foobar2000 窗口标题格式",
            "留空 = 自动（歌名与歌手顺序不可知时不猜，两种顺序都能搜到）。若歌词"
            "对不上，把 foobar「显示 → 默认用户界面 → 窗口标题」里的那串原样填进来"
            "（例如 %artist% - %title%），就能精确切分歌名与歌手。",
            edit,
            stacked=True,
        ),
    ]


def save_music_player_settings(dialog) -> None:
    """写回 ``music_player_paths``；两项都留空 = 回到自动搜索，并清掉路径缓存。"""
    if getattr(dialog, "music_player_detect_btn", None) is None:
        return
    paths = {}
    for key in PLAYER_KEYS:
        value = getattr(dialog, _PICKER_ATTR[key]).text().strip()
        if value:
            paths[key] = value
    previous = dialog.config.get("music_player_paths", {})
    if not isinstance(previous, dict):
        previous = {}
    dialog.config.set("music_player_paths", paths)
    if paths != previous:
        # 路径变了：让右键菜单下次拿到确定态（自动搜索的负缓存也要作废）。
        music_players.clear_cache()


# 「音乐关联」域里两个**来源开关**的控件名 → 配置键。控件在
# pet/settings_pet_controls 里按平台条件创建（非 Windows 为 None）。
_SOURCE_SWITCHES = (
    ("music_browser_media_check", "music_browser_media_enabled"),
    ("foobar_lyrics_check", "foobar_lyrics_enabled"),
)


def save_source_settings(dialog) -> None:
    """写回歌词来源开关与 foobar 窗口标题格式串。

    集中在这里的原因与控件/行同源：``modern_settings_dialog._save`` 的行数预算已无
    余量，这一组键的写回语义（"控件不存在就整键跳过"，非 Windows 上没有该控件）
    放进对话框本体只会多出几行重复的 getattr 样板。
    """
    for attr, key in _SOURCE_SWITCHES:
        widget = getattr(dialog, attr, None)
        if widget is not None:
            dialog.config.set(key, widget.isChecked())
    edit = getattr(dialog, "foobar_title_format_edit", None)
    if edit is not None:
        dialog.config.set("foobar_title_format", edit.text().strip())


def start_detect(dialog, *, warm=None, lookup=None) -> None:
    """「自动检测」入口：后台预热 + 定时轮询回填（GUI 线程只读缓存，不扫盘）。"""
    warm = warm or music_players.warm_cache_async
    dialog._music_detect_lookup = lookup
    dialog._music_detect_deadline = time.monotonic() + DETECT_TIMEOUT_SECONDS
    dialog._music_detect_results = {}
    for key in PLAYER_KEYS:
        warm(key, "")

    button = dialog.music_player_detect_btn
    button.setEnabled(False)
    button.setText("检测中…")

    timer = getattr(dialog, "_music_detect_timer", None)
    if timer is None:
        timer = QTimer(dialog)
        timer.setInterval(DETECT_POLL_MS)
        timer.timeout.connect(lambda: poll_detect(dialog))
        dialog._music_detect_timer = timer
    timer.start()
    poll_detect(dialog)


def poll_detect(dialog) -> None:
    """轮询一次：有冷缓存就继续等，出结果（或超时）就回填并收尾。"""
    lookup = getattr(dialog, "_music_detect_lookup", None) or music_players.cached_player
    results: dict[str, str] = getattr(dialog, "_music_detect_results", {})
    pending = False
    for key in PLAYER_KEYS:
        state, path = lookup(key, "")
        if path:
            results[key] = path
        elif state == music_players.CACHED_COLD:
            pending = True
    if pending and time.monotonic() < getattr(dialog, "_music_detect_deadline", 0.0):
        return

    timer = getattr(dialog, "_music_detect_timer", None)
    if timer is not None:
        timer.stop()
    button = dialog.music_player_detect_btn
    button.setEnabled(True)
    button.setText(_DETECT_BUTTON_LABEL)

    for key, path in results.items():
        getattr(dialog, _PICKER_ATTR[key]).setText(path)
    if results:
        log.info("音乐播放器路径自动检测：找到 %s", results)
    else:
        log.info("音乐播放器路径自动检测：未找到任何播放器")
    _report_results(dialog, results)


def _report_results(dialog, results: dict[str, str]) -> None:
    lines = []
    for key in PLAYER_KEYS:
        label = music_players.player_label(key)
        path = results.get(key)
        lines.append(f"{label}：{path}" if path else f"{label}：未找到")
    QMessageBox.information(
        dialog,
        "自动检测播放器",
        "\n".join(lines) + "\n\n没找到的可以点右侧「选择…」手动指定程序位置。",
    )
