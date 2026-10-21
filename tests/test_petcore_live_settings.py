from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.engine.geometry import SCALE_MAX, SCALE_MIN
from petcore.ui.app import CoreHost
from petcore.ui.pet_window import PetWindow


class RecordingWindow:
    def __init__(self):
        self.calls = []
        self.character = "shenshen"
        self.character_id = "shenshen"
        self.scale = 0.72
        self.always_on_top = True
        self.click_through = False
        self.state = SimpleNamespace(scale=self.scale)

    def set_character(self, character_id, *, persist=True):
        self.character = character_id
        self.character_id = character_id
        self.calls.append(("set_character", character_id, persist))

    def set_scale(self, scale, *, persist=True):
        self.scale = scale
        self.state.scale = scale
        self.calls.append(("set_scale", scale, persist))

    def set_always_on_top(self, value, *, persist=True):
        self.always_on_top = bool(value)
        self.calls.append(("set_always_on_top", bool(value), persist))

    def set_click_through(self, value, *, persist=True):
        self.click_through = bool(value)
        self.calls.append(("set_click_through", bool(value), persist))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_config_clamps_scale_to_ten_and_three_hundred_percent(tmp_path):
    config = Config(tmp_path, {"scale": 9.0})
    assert config.get("scale") == SCALE_MAX
    config.set("scale", 0.01)
    assert config.get("scale") == SCALE_MIN
    config.set("scale", 2.5)
    snapshot = config.snapshot()
    config.set("scale", 1.0)
    config.restore(snapshot)
    assert config.get("scale") == 2.5


def test_pet_window_live_scale_does_not_touch_disk(app, tmp_path):
    config = Config(tmp_path)
    window = PetWindow(config, tmp_path, SimpleNamespace())
    try:
        window.set_scale(1.5, persist=False)
        assert window.state.scale == 1.5
        assert config.get("scale") == 1.5
        assert not config.path.exists()

        window.set_scale(9.0, persist=False)
        assert window.state.scale == SCALE_MAX

        window.set_scale(1.25)
        assert config.path.exists()
        assert Config.load(tmp_path).get("scale") == 1.25
    finally:
        window.shutdown()


def _host_for_live_applies(tmp_path):
    host = CoreHost.__new__(CoreHost)
    host.config = Config(tmp_path)
    host.window = RecordingWindow()
    return host


def test_apply_live_settings_only_touches_changed_values(tmp_path):
    host = _host_for_live_applies(tmp_path)
    CoreHost.apply_live_settings(host)
    assert host.window.calls == []

    host.config.set("scale", 2.0)
    host.config.set("click_through", True)
    CoreHost.apply_live_settings(host)

    assert ("set_scale", 2.0, False) in host.window.calls
    assert ("set_click_through", True, False) in host.window.calls
    assert not any(call[0] == "set_character" for call in host.window.calls)
    assert not any(call[0] == "set_always_on_top" for call in host.window.calls)


def test_apply_live_settings_switches_character_and_topmost(tmp_path):
    host = _host_for_live_applies(tmp_path)
    host.config.set("character", "other")
    host.config.set("always_on_top", False)
    CoreHost.apply_live_settings(host)

    assert ("set_character", "other", False) in host.window.calls
    assert ("set_always_on_top", False, False) in host.window.calls


def test_apply_live_settings_is_safe_without_window(tmp_path):
    host = CoreHost.__new__(CoreHost)
    host.config = Config(tmp_path)
    host.window = None
    CoreHost.apply_live_settings(host)
