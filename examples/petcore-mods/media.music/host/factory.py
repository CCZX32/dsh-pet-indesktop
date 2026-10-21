from __future__ import annotations

import sys

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_checkbox

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002


def press_media_key(key: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


class MusicRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {
            "pause": lambda: self._press(VK_MEDIA_PLAY_PAUSE, "播放/暂停"),
            "next": lambda: self._press(VK_MEDIA_NEXT_TRACK, "下一首"),
            "prev": lambda: self._press(VK_MEDIA_PREV_TRACK, "上一首"),
            "stop": lambda: self._press(VK_MEDIA_STOP, "停止"),
            "lyric_align": self._lyric_align,
        }

    def _enabled(self) -> bool:
        config = getattr(self.context.host, "config", None)
        return config is None or bool(config.get("music_enabled", True))

    def _press(self, key: int, label: str) -> None:
        if not self._enabled():
            return
        presentation = self.context.ports.presentation
        if press_media_key(key):
            if presentation is not None:
                presentation.notify("音乐", label)
        elif presentation is not None:
            presentation.notify("音乐", "当前平台不支持系统媒体键。")

    def _lyric_align(self) -> None:
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.notify("歌词对齐", "当前 core 版本未接入歌词对齐；先提供系统媒体键控制。")

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class MusicPage(SettingsPage):
    title = "音乐"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("music_enabled", True))
        card = self.section("系统媒体键")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用音乐控制", self.enabled, "通过 Windows 系统媒体键控制当前播放器；不读取歌名/歌词。")
        self.add_note("右键菜单的播放/暂停、上一首、下一首、停止会发送系统媒体键。歌词对齐留待后续接入 SMTC。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("music_enabled", self.enabled.isChecked())
        self.changed.emit()

    def dirty(self) -> bool:
        return self.enabled.isChecked() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.enabled.isChecked()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial)
        self.enabled.blockSignals(False)
        self.config().set("music_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["音乐", "播放", "暂停", "上一首", "下一首", "歌词", "music", "media"]


def create_host(_context):
    return FeatureDefinition(
        owner="media.music",
        contributions=(
            Contribution(
                kind="menu",
                id="pause",
                data={"label": "播放 / 暂停", "command": "pause", "order": 70, "icon": "play"},
            ),
            Contribution(
                kind="menu",
                id="next",
                data={"label": "下一首", "command": "next", "order": 71, "icon": "play"},
            ),
            Contribution(
                kind="menu",
                id="prev",
                data={"label": "上一首", "command": "prev", "order": 72, "icon": "play"},
            ),
            Contribution(
                kind="menu",
                id="stop",
                data={"label": "停止播放", "command": "stop", "order": 73, "icon": "pause"},
            ),
            Contribution(
                kind="menu",
                id="lyric_align",
                data={"label": "歌词对齐", "command": "lyric_align", "order": 74, "icon": "chat"},
            ),
            Contribution(
                kind="settings_page",
                id="music",
                data={"title": "音乐", "order": 680, "icon": "play"},
            ),
        ),
        runtime_factory=MusicRuntime,
        settings_factory=MusicPage,
    )
