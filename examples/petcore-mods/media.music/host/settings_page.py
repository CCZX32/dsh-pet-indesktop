"""音乐设置页：音乐信息、唱歌动画、歌词与四个播放器的路径（Qt 允许）。

改动实时写进 config（全局键），保存只负责落盘；取消/关闭时 ``discard_changes()``
把配置与控件一起回滚到打开设置时的快照（与其它扩展设置页同一口径）。

运行时只读配置，所以「歌词对齐」调出来的偏移是**本次运行**的会话状态；本页只显示
配置里的初值 ``music_lyric_offset_seconds``。
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from petcore.ui.settings.base import SettingsPage, make_checkbox

from . import now_playing, players
from .runtime import DEFAULTS


class MusicPage(SettingsPage):
    title = "音乐"
    detect_done = Signal(str)

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        config = self.config()

        # -------------------------------------------------------- 音乐信息
        card = self.section("音乐信息")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(bool(config.get("music_enabled", DEFAULTS["music_enabled"])))
        self.enabled.toggled.connect(lambda _checked=False: self._write("music_enabled", self.enabled.isChecked()))
        card.add_row(
            "启用音乐",
            self.enabled,
            "读取系统当前播放的曲目（SMTC）；关闭后不轮询、不发任何请求。",
        )

        self.sing = make_checkbox(self)
        self.sing.setChecked(bool(config.get("music_sing_enabled", DEFAULTS["music_sing_enabled"])))
        self.sing.toggled.connect(
            lambda _checked=False: self._write("music_sing_enabled", self.sing.isChecked())
        )
        card.add_row(
            "唱歌动画",
            self.sing,
            "播放音乐时循环播放「悠闲哼歌」；纯音乐不唱。",
        )

        self.grace = QSpinBox(self)
        self.grace.setRange(0, 120)
        self.grace.setSuffix(" 秒")
        self.grace.setValue(int(float(config.get("music_sing_grace_seconds", DEFAULTS["music_sing_grace_seconds"]))))
        self.grace.valueChanged.connect(
            lambda value: self._write("music_sing_grace_seconds", int(value))
        )
        card.add_row(
            "停止后保持",
            self.grace,
            "暂停或静音超过这个时间才停止唱歌动画；歌与歌之间的空隙不会打断。",
        )

        self.detect_button = QPushButton("检测当前播放", self)
        self.detect_button.clicked.connect(self._detect)
        card.add_row(
            "当前曲目",
            self.detect_button,
            "只在你点它时读一次系统媒体会话；读不到会说明原因。",
        )

        self.detect_status = QLabel("", self)
        self.detect_status.setObjectName("settingHint")
        self.detect_status.setWordWrap(True)
        card.add_row("检测结果", self.detect_status, "", expand=True)

        # -------------------------------------------------------- 歌词
        lyric_card = self.section("歌词")
        self.lyric = make_checkbox(self)
        self.lyric.setChecked(bool(config.get("music_lyric_enabled", DEFAULTS["music_lyric_enabled"])))
        self.lyric.toggled.connect(
            lambda _checked=False: self._write("music_lyric_enabled", self.lyric.isChecked())
        )
        lyric_card.add_row(
            "显示歌词",
            self.lyric,
            "每首歌在后台取一次歌词，之后按播放位置更新气泡；失败不重试。",
        )

        self.lead = QDoubleSpinBox(self)
        self.lead.setRange(-2.0, 3.0)
        self.lead.setDecimals(1)
        self.lead.setSingleStep(0.1)
        self.lead.setSuffix(" 秒")
        self.lead.setValue(float(config.get("music_lyric_lead_seconds", DEFAULTS["music_lyric_lead_seconds"])))
        self.lead.valueChanged.connect(
            lambda value: self._write("music_lyric_lead_seconds", round(float(value), 1))
        )
        lyric_card.add_row(
            "歌词提前量",
            self.lead,
            "正数让歌词提前出现（人耳对「歌词晚了」更敏感）。",
        )

        self.cache = QSpinBox(self)
        self.cache.setRange(10, 2000)
        self.cache.setSingleStep(10)
        self.cache.setSuffix(" 首")
        self.cache.setValue(int(float(config.get("music_lyric_cache_limit", DEFAULTS["music_lyric_cache_limit"]))))
        self.cache.valueChanged.connect(
            lambda value: self._write("music_lyric_cache_limit", int(value))
        )
        lyric_card.add_row(
            "歌词缓存上限",
            self.cache,
            "超出后按写入时间淘汰最旧的；缓存里只有歌词文本。",
        )

        self.offset_value = float(
            config.get("music_lyric_offset_seconds", DEFAULTS["music_lyric_offset_seconds"]) or 0.0
        )
        self.offset_label = QLabel(f"{self.offset_value:+.1f} 秒", self)
        self.offset_label.setObjectName("settingHint")
        lyric_card.add_row(
            "歌词偏移",
            self.offset_label,
            "右键菜单「音乐 → 歌词对齐」每次 +0.5 秒（本次运行有效）；这里是配置里的初值。",
        )

        self.browser = make_checkbox(self)
        self.browser.setChecked(
            bool(config.get("music_browser_media_enabled", DEFAULTS["music_browser_media_enabled"]))
        )
        self.browser.toggled.connect(
            lambda _checked=False: self._write("music_browser_media_enabled", self.browser.isChecked())
        )
        lyric_card.add_row(
            "浏览器媒体会话",
            self.browser,
            "浏览器会把网页视频也报成音乐；默认不参与歌词与唱歌。",
        )

        # -------------------------------------------------------- 播放器
        player_card = self.section("播放器")
        self.player = QComboBox(self)
        self.player.setMinimumWidth(180)
        self.player.addItem("（不指定）", "")
        for key in players.player_keys():
            self.player.addItem(players.player_label(key), key)
        index = self.player.findData(str(config.get("music_player", DEFAULTS["music_player"]) or ""))
        self.player.setCurrentIndex(index if index >= 0 else 0)
        self.player.currentIndexChanged.connect(
            lambda _index=0: self._write("music_player", str(self.player.currentData() or ""))
        )
        player_card.add_row(
            "默认播放器",
            self.player,
            "多个会话同时播放时优先跟随它；留空则跟随正在播放的那个。",
        )

        self.path_edits: dict[str, QLineEdit] = {}
        configured = config.get("music_player_paths", DEFAULTS["music_player_paths"])
        configured = configured if isinstance(configured, dict) else {}
        for key in players.player_keys():
            player_card.add_row(
                f"{players.player_label(key)}路径",
                self._path_row(key, str(configured.get(key) or "")),
                "留空 = 不启动；菜单「打开 …」只用这里配置的路径，不扫盘。",
                expand=True,
            )

        self.add_note(
            "隐私与网络：歌词只从公开接口取文本（网易云 / 酷狗，首选直连、单次预算 8 秒、"
            "响应上限 2 MB），不下载音频、不记录收听历史；失败一首歌只试一轮。"
        )

        self.detect_done.connect(self._on_detect_done)
        self._initial = self._snapshot()

    # ---------------------------------------------------------------- 配置

    def config(self):
        return self.host.config

    def _write(self, key: str, value) -> None:
        self.config().set(key, value)
        self.changed.emit()

    def _paths(self) -> dict[str, str]:
        raw = self.config().get("music_player_paths", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _snapshot(self) -> tuple:
        return (
            bool(self.enabled.isChecked()),
            bool(self.sing.isChecked()),
            int(self.grace.value()),
            bool(self.lyric.isChecked()),
            round(float(self.lead.value()), 1),
            int(self.cache.value()),
            bool(self.browser.isChecked()),
            str(self.player.currentData() or ""),
            tuple(
                (key, self.path_edits[key].text().strip())
                for key in players.player_keys()
                if key in self.path_edits
            ),
        )

    def dirty(self) -> bool:
        return self._snapshot() != self._initial

    def confirm_save(self) -> None:
        config = self.config()
        config.set("music_enabled", bool(self.enabled.isChecked()))
        config.set("music_sing_enabled", bool(self.sing.isChecked()))
        config.set("music_sing_grace_seconds", int(self.grace.value()))
        config.set("music_lyric_enabled", bool(self.lyric.isChecked()))
        config.set("music_lyric_lead_seconds", round(float(self.lead.value()), 1))
        config.set("music_lyric_cache_limit", int(self.cache.value()))
        config.set("music_browser_media_enabled", bool(self.browser.isChecked()))
        config.set("music_player", str(self.player.currentData() or ""))
        config.set("music_player_paths", dict(self._snapshot()[-1]))
        self._initial = self._snapshot()

    def discard_changes(self) -> None:
        values = self._initial
        mapping = {
            "music_enabled": values[0],
            "music_sing_enabled": values[1],
            "music_sing_grace_seconds": values[2],
            "music_lyric_enabled": values[3],
            "music_lyric_lead_seconds": values[4],
            "music_lyric_cache_limit": values[5],
            "music_browser_media_enabled": values[6],
            "music_player": values[7],
            "music_player_paths": {key: path for key, path in values[8] if path},
        }
        config = self.config()
        for key, value in mapping.items():
            config.set(key, value)

        for widget, value in (
            (self.enabled, values[0]),
            (self.sing, values[1]),
            (self.lyric, values[3]),
            (self.browser, values[6]),
        ):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        for widget, value in (
            (self.grace, int(values[2])),
            (self.cache, int(values[5])),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.lead.blockSignals(True)
        self.lead.setValue(float(values[4]))
        self.lead.blockSignals(False)
        self.player.blockSignals(True)
        index = self.player.findData(values[7])
        self.player.setCurrentIndex(index if index >= 0 else 0)
        self.player.blockSignals(False)
        for key, path in values[8]:
            edit = self.path_edits.get(key)
            if edit is not None:
                edit.blockSignals(True)
                edit.setText(path)
                edit.blockSignals(False)
        self.detect_status.setText("")
        self.changed.emit()

    def keywords(self) -> list[str]:
        return [
            "音乐",
            "播放",
            "暂停",
            "上一首",
            "下一首",
            "歌词",
            "唱歌",
            "网易云",
            "QQ音乐",
            "酷狗",
            "汽水",
            "music",
            "lyric",
        ]

    # ---------------------------------------------------------------- 控件

    def _path_row(self, key: str, value: str) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        edit = QLineEdit(value, row)
        edit.setPlaceholderText(f"{players.player_exe(key)} 的完整路径")
        edit.setMinimumWidth(260)
        edit.editingFinished.connect(lambda key=key: self._on_path_changed(key))
        browse = QPushButton("浏览…", row)
        browse.clicked.connect(lambda _checked=False, key=key: self._browse(key))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        self.path_edits[key] = edit
        return row

    def _on_path_changed(self, key: str) -> None:
        edit = self.path_edits.get(key)
        if edit is None:
            return
        text = edit.text().strip()
        paths = self._paths()
        if text:
            paths[key] = text
        else:
            paths.pop(key, None)
        self._write("music_player_paths", paths)

    def _browse(self, key: str) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            f"选择{players.player_label(key)}的程序",
            str(Path.home()),
            "程序 (*.exe);;所有文件 (*)",
        )
        if not path:
            return
        edit = self.path_edits.get(key)
        if edit is not None:
            edit.setText(path)
        self._on_path_changed(key)

    def _detect(self) -> None:
        self.detect_button.setEnabled(False)
        self.detect_status.setText("正在读取系统媒体会话…")
        browser_media = bool(self.browser.isChecked())

        def work() -> None:
            try:
                playback, reason = now_playing.read_playback_with_reason(
                    browser_media_enabled=browser_media
                )
            except Exception:
                playback, reason = None, "读取系统媒体信息失败。"
            if playback is None:
                text = reason or "没有读到正在播放的曲目。"
            else:
                state = "在播" if playback.playing else "已暂停"
                text = f"{playback.label()}（{state}）"
            try:
                self.detect_done.emit(text)
            except RuntimeError:
                # 设置窗口在读取期间被销毁：信号对象已失效，丢弃结果即可。
                pass

        threading.Thread(target=work, name="music-detect", daemon=True).start()

    def _on_detect_done(self, text: str) -> None:
        self.detect_status.setText(text)
        self.detect_button.setEnabled(True)
