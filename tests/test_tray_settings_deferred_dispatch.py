# -*- coding: utf-8 -*-
"""托盘「AI 设置 / 桌宠设置」入口：菜单先关、回调延到菜单跟踪会话之后。

背景：托盘菜单此前是裸 ``menu.addAction(text, callback)``——回调在原生菜单跟踪
会话里**内联执行**。macOS 的托盘菜单是 AppKit 原生 NSMenu，跟踪会话中新建/激活
窗口会被 AppKit 抑制（issue #4 家族：点了没反应，再点一次才对；右键菜单路径早已
用 ``close_on_trigger`` + ``exec()`` 返回后派发解决，托盘菜单没有 ``exec()``
收口点，故走 ``shared.run_after_menu_closed``：菜单先关、等它真的不在了再执行）。

验收口径：菜单可见期内回调不得执行；点击后菜单先关；菜单关闭后执行一次。
时序纪律：事件同步 + 宽预算轮询（``app.processEvents()``），不赌固定 sleep。
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from pet.app import AppShell
from pet.config import Config

app = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _entry(menu, label: str):
    for action in menu.actions():
        if action.text() == label:
            return action
    raise AssertionError(
        f"托盘菜单缺项 {label}；实际: {[a.text() for a in menu.actions()]}")


class _TrayWin:
    """建托盘所需的最小窗口桩（刻意非 QWidget：_build_tray 的调用方可能是替身）。"""

    def __init__(self, config):
        self.config = config
        self._speech_bubble = QWidget()
        self.hidden_bubbles = 0

    def icon_pixmap(self, _size: int = 64) -> QPixmap:
        return QPixmap(2, 2)

    def hide_speech_bubble(self) -> None:
        self.hidden_bubbles += 1

    def go_default_corner(self) -> None:  # pragma: no cover - 本用例不触发
        pass

    def set_mouse_through(self, on: bool) -> None:  # pragma: no cover
        self.config.set("mouse_through", bool(on))

    def isVisible(self) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def show(self) -> None:  # pragma: no cover
        pass

    def hide(self) -> None:  # pragma: no cover
        pass


def _legacy_tray(tmp_path, calls):
    shell = AppShell(app, Config(tmp_path), enable_chat=True)
    shell.instance.open_chat_settings = lambda: calls.append("ai")
    shell.instance.open_modern_settings = lambda: calls.append("pet")
    win = _TrayWin(Config(tmp_path))
    tray = shell._build_tray(win)
    menu = tray.contextMenu()
    assert menu is not None
    return shell, tray, menu


@pytest.mark.parametrize("label,expected", [("AI 设置", "ai"), ("桌宠设置", "pet")])
def test_legacy_tray_settings_entry_waits_for_menu_close(tmp_path, label, expected):
    """托盘这两个设置入口不得在菜单可见期内执行回调（macOS 首点被抑制）。"""
    calls: list = []
    _shell, tray, menu = _legacy_tray(tmp_path, calls)
    try:
        menu.show()
        app.processEvents()
        assert menu.isVisible(), "前提：菜单在显示态"

        _entry(menu, label).trigger()
        assert calls == [], f"{label}：菜单还开着，回调不许内联执行"
        assert not menu.isVisible(), f"{label}：点击后菜单必须先关"

        assert _wait_until(lambda: calls == [expected]), f"菜单关闭后必须执行一次，实际 {calls}"
    finally:
        tray.hide()
        menu.close()
        app.processEvents()


def test_overlay_tray_settings_entry_waits_for_menu_close(tmp_path):
    """overlay 拓扑的同一个入口（``OverlayShell._refresh_tray_menu``）同口径。"""
    from tests.test_overlay_spawn import _make_persistent_shell

    shell, _made = _make_persistent_shell(tmp_path)
    opened: list = []
    try:
        shell._instance.shell = SimpleNamespace(
            open_settings_process=lambda inst: (opened.append(inst), True)[1])
        menu = shell.tray.contextMenu()
        assert menu is not None
        menu.show()
        app.processEvents()
        assert menu.isVisible(), "前提：菜单在显示态"

        _entry(menu, "桌宠设置").trigger()
        assert opened == [], "菜单还开着，设置入口不许内联执行"
        assert not menu.isVisible(), "点击后菜单必须先关"
        assert _wait_until(lambda: len(opened) == 1), "菜单关闭后必须打开设置"
    finally:
        menu = shell.tray.contextMenu()
        if menu is not None:
            menu.close()
        shell._teardown_settings_command_watch()
        app.processEvents()
