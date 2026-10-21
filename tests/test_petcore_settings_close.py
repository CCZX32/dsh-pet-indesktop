from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from petcore.config import Config
from petcore.contracts.host import HostPorts
from petcore.mods.feature import FeatureManager
from petcore.ui.settings.dialog import SettingsDialog


class FakeWindow:
    def __init__(self) -> None:
        self.scale = 0.72
        self.character = "shenshen"
        self.click_through = False
        self.always_on_top = True
        self.visible = True
        self.edge_probe = False

    def set_character(self, character_id, *, persist=True):
        self.character = character_id

    def set_scale(self, scale, *, persist=True):
        self.scale = float(scale)

    def set_click_through(self, value, *, persist=True):
        self.click_through = bool(value)

    def set_always_on_top(self, value, *, persist=True):
        self.always_on_top = bool(value)

    def set_visible(self, visible):
        self.visible = bool(visible)

    def set_edge_probe_enabled(self, enabled, *, persist=True):
        self.edge_probe = bool(enabled)

    def isVisible(self):
        return self.visible

    def say(self, text, *args, **kwargs):
        return None


class FakeHost:
    def __init__(self, root: Path) -> None:
        self.config = Config(root)
        self.root = root
        self.window = FakeWindow()
        self.load_result = None
        self.diagnostics: list[str] = []
        self.mod_dirs = ()
        self.settings_pages = None
        self.features = FeatureManager(HostPorts(), host=self)
        self.diagnostics.extend(self.features.load_builtin_features())

    def characters(self):
        return []

    def character_for(self, character_id):
        return None

    def build_menu(self, parent=None):
        return None

    def open_data_dir(self):
        return None

    def reload_mods(self):
        return None

    def apply_live_settings(self):
        window = self.window
        window.set_scale(float(self.config.get("scale") or 0.72), persist=False)
        window.set_click_through(bool(self.config.get("click_through")), persist=False)
        window.set_always_on_top(bool(self.config.get("always_on_top")), persist=False)

    def set_hotkey(self, text, *, persist=True):
        return True, ""

    def quit_app(self):
        return None


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _page(dialog: SettingsDialog, title: str) -> QWidget:
    for index in range(dialog.stack.count()):
        page = dialog.stack.widget(index)
        if getattr(page, "title", "") == title:
            return page
    raise AssertionError(f"missing settings page: {title}")


def test_close_saves_changed_setting(app, tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    dialog = SettingsDialog(host)
    dialog.show()
    appearance = _page(dialog, "外观与交互")

    appearance.scale_spin.setValue(150)
    dialog._apply_live()
    assert not (tmp_path / "config.json").exists()

    dialog.close()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert host.config.get("scale") == 1.5
    assert host.window.scale == 1.5
    assert Config.load(tmp_path).get("scale") == 1.5


def test_reject_restores_snapshot_and_keeps_disk_untouched(app, tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")

    appearance.scale_spin.setValue(150)
    dialog._apply_live()
    assert host.config.get("scale") == 1.5

    dialog.reject()

    assert host.config.get("scale") == 0.72
    assert host.window.scale == 0.72
    assert appearance.scale_spin.value() == 72
    assert not (tmp_path / "config.json").exists()


def test_close_disposes_embedded_pages(app, tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    assert interaction._embedded_pages

    dialog.close()

    assert interaction._embedded_pages == []


def test_ui_font_size_drives_settings_and_menu_typography(app, tmp_path: Path) -> None:
    from petcore.ui.menu_model import MenuItem, MenuModel
    from petcore.ui.settings.style import stylesheet

    assert "font-size: 27px" in stylesheet(False, 18)
    assert "font-size: 17px" in stylesheet(False, 18)
    assert "font-size: 19px" in stylesheet(False, 10)

    host = FakeHost(tmp_path)
    host.config.set("ui_font_size", 18)
    dialog = SettingsDialog(host)
    try:
        assert "font-size: 27px" in dialog.styleSheet()
    finally:
        dialog.close()

    model = MenuModel()
    model.register(MenuItem("a", "A"))
    model.set_font_size(18)
    assert "font-size: 18px" in model.build().styleSheet()

