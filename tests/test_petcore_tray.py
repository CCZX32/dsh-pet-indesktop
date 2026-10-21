from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petcore.ui.app import CoreHost


class FakeWindow:
    def __init__(self, visible: bool) -> None:
        self.visible = visible
        self.corner = False
        self.quit = False
        self.click_through = False
        self.said: list[str] = []

    def isVisible(self) -> bool:  # noqa: N802
        return self.visible

    def set_visible(self, value: bool) -> None:
        self.visible = bool(value)

    def return_corner(self) -> None:
        self.corner = True

    def quit_from_menu(self) -> None:
        self.quit = True

    def set_click_through(self, value: bool) -> None:
        self.click_through = bool(value)

    def say(self, text, duration_ms: int = 4000) -> None:
        del duration_ms
        self.said.append(str(text))


class FakePets:
    def __init__(self, windows) -> None:
        self.windows = dict(windows)

    def each(self):
        return [self.windows[slot] for slot in sorted(self.windows)]

    def set_visible_all(self, value: bool) -> None:
        for window in self.windows.values():
            window.set_visible(value)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _host(visible: bool = False):
    windows = {0: FakeWindow(visible), 1: FakeWindow(visible)}
    host = SimpleNamespace(
        pets=FakePets(windows),
        window=windows[0],
        tray=None,
        open_settings=lambda *a, **k: None,
        open_data_dir=lambda: None,
        reload_mods=lambda: None,
        quit_app=lambda: None,
    )
    host.toggle_all_visible = lambda: CoreHost.toggle_all_visible(host)
    host.populate_tray_menu = lambda menu: CoreHost.populate_tray_menu(host, menu)
    host.set_all_visible = lambda value: CoreHost.set_all_visible(host, value)
    host._toggle_one = lambda window: CoreHost._toggle_one(host, window)
    host._windows = lambda: CoreHost._windows(host)
    host.all_click_through = lambda: CoreHost.all_click_through(host)
    host.set_all_click_through = lambda value: CoreHost.set_all_click_through(host, value)
    return host, windows


def test_tray_menu_shows_the_pet_when_hidden(app) -> None:
    host, windows = _host(visible=False)
    menu = CoreHost.build_tray_menu(host)
    labels = [action.text() for action in menu.actions() if action.text()]
    assert labels[0] == "显示桌宠"
    menu.actions()[0].trigger()
    assert windows[0].isVisible() and windows[1].isVisible()


def test_tray_menu_hides_the_pet_when_visible(app) -> None:
    host, windows = _host(visible=True)
    menu = CoreHost.build_tray_menu(host)
    assert menu.actions()[0].text() == "隐藏桌宠"
    menu.actions()[0].trigger()
    assert not windows[0].isVisible() and not windows[1].isVisible()


def test_tray_menu_has_per_pet_controls_and_quit(app) -> None:
    host, windows = _host(visible=True)
    menu = CoreHost.build_tray_menu(host)
    labels = [action.text() for action in menu.actions()]
    assert "桌宠设置" in labels
    assert "打开数据目录" in labels
    assert "重新加载模块" not in labels
    assert "重新加载扩展" in labels
    assert labels[-1] == "退出"

    submenus = [action.menu() for action in menu.actions() if action.menu() is not None]
    assert len(submenus) == 2
    assert [action.text() for action in submenus[0].actions()] == ["隐藏", "回到右下角"]
    assert [action.text() for action in submenus[1].actions()] == ["隐藏", "回到右下角", "退出这只"]

    submenus[1].actions()[0].trigger()
    assert windows[1].isVisible() is False
    submenus[1].actions()[2].trigger()
    assert windows[1].quit is True


def test_tray_menu_rebuilds_actions_before_showing(app) -> None:
    host, windows = _host(visible=True)
    menu = CoreHost.build_tray_menu(host)
    assert menu.actions()[0].text() == "隐藏桌宠"

    windows[0].set_visible(False)
    windows[1].set_visible(False)
    menu.aboutToShow.emit()

    assert menu.actions()[0].text() == "显示桌宠"


def test_tray_menu_toggles_click_through_for_every_pet(app) -> None:
    host, windows = _host(visible=True)
    menu = CoreHost.build_tray_menu(host)
    action = next(item for item in menu.actions() if item.text() == "鼠标穿透")
    assert action.isCheckable() is True
    assert action.isChecked() is False

    action.trigger()
    assert all(window.click_through for window in windows.values())
    assert any("鼠标穿透" in text for text in windows[0].said)

    menu.aboutToShow.emit()
    checked = next(item for item in menu.actions() if item.text() == "鼠标穿透")
    assert checked.isChecked() is True
    checked.trigger()
    assert not any(window.click_through for window in windows.values())


def test_context_activation_does_not_replace_the_menu(app, monkeypatch) -> None:
    from petcore.ui.tray import TrayIcon

    calls = []
    tray = TrayIcon(lambda _parent: None, Path("missing.ico"), lambda: calls.append("toggle"))
    monkeypatch.setattr(tray, "refresh", lambda: calls.append("refresh"))
    tray._on_activated(tray.ActivationReason.Context)
    assert calls == []

    tray._on_activated(tray.ActivationReason.Trigger)
    assert calls == ["toggle"]
