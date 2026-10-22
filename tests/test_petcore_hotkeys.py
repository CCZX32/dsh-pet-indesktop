"""全局快捷键：四条并存、命名注销、配置键映射与命令分发。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.platform.hotkeys import GlobalHotkeyService
from petcore.ui.app import HOTKEY_COMMANDS, HOTKEY_CONFIGS, CoreHost


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class RecordingUser32:
    def __init__(self) -> None:
        self.registered: list[tuple[int, int, int]] = []
        self.unregistered: list[int] = []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):  # noqa: N802 - Win32
        self.registered.append((int(hotkey_id), int(modifiers), int(vk)))
        return True

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802 - Win32
        self.unregistered.append(int(hotkey_id))
        return True


def test_named_hotkeys_coexist_and_clear_independently(app) -> None:
    user32 = RecordingUser32()
    service = GlobalHotkeyService(app, user32=user32, supported=True)
    assert service.install()

    assert service.apply("Ctrl+Alt+P", lambda: None)[0]
    assert service.apply("Ctrl+Alt+L", lambda: None, name="look_screen")[0]
    assert service.apply("Ctrl+Alt+S", lambda: None, name="screen_capture")[0]

    ids = [entry[0] for entry in user32.registered]
    assert len(ids) == 3 and len(set(ids)) == 3
    assert service.active_texts() == {
        "toggle_pet": "Ctrl+Alt+P",
        "look_screen": "Ctrl+Alt+L",
        "screen_capture": "Ctrl+Alt+S",
    }

    service.clear("look_screen")
    assert "look_screen" not in service.active_texts()
    assert set(service.active_texts()) == {"toggle_pet", "screen_capture"}
    assert len(user32.unregistered) == 1

    service.clear()
    assert service.active_texts() == {}
    assert service.active_text == ""
    service.uninstall()


def test_reapplying_the_same_name_replaces_registration(app) -> None:
    user32 = RecordingUser32()
    service = GlobalHotkeyService(app, user32=user32, supported=True)
    assert service.apply("Ctrl+Alt+P", lambda: None)[0]
    assert service.apply("Ctrl+Shift+P", lambda: None)[0]
    assert service.active_text == "Ctrl+Shift+P"
    assert len(user32.registered) == 2
    assert len(user32.unregistered) == 1


def test_invalid_text_means_unbound_not_failure(app) -> None:
    user32 = RecordingUser32()
    service = GlobalHotkeyService(app, user32=user32, supported=True)
    ok, message = service.apply("P", lambda: None)  # 没有修饰键
    assert (ok, message) == (True, "")
    assert service.active_texts() == {}
    assert user32.registered == []


def test_core_host_maps_kind_to_config_key_and_command(tmp_path: Path) -> None:
    assert HOTKEY_CONFIGS["open_chat"] == "hotkey_open_chat"
    assert HOTKEY_COMMANDS["look_screen"] == ("ai.chat", "look_screen")

    class FakeService:
        def __init__(self) -> None:
            self.applied: list[tuple[str, str]] = []

        def apply(self, text, _callback, *, name="toggle_pet"):
            self.applied.append((text, name))
            return True, ""

    host = object.__new__(CoreHost)
    host.config = Config(tmp_path)
    host.hotkeys = FakeService()
    host._active_window = None
    host.window = None

    assert CoreHost.set_hotkey(host, "Ctrl+Alt+K", kind="open_chat")[0] is True
    assert host.config.get("hotkey_open_chat") == "Ctrl+Alt+K"
    assert host.hotkeys.applied[-1] == ("Ctrl+Alt+K", "open_chat")

    calls: list[tuple[str, str]] = []
    host.run_feature_command = lambda owner, command, slot=None: calls.append(
        (owner, command)
    )
    CoreHost._hotkey_callback(host, "screen_capture")()
    assert calls == [("ai.chat", "screen_capture")]


def test_unknown_hotkey_kind_is_rejected(tmp_path: Path) -> None:
    host = object.__new__(CoreHost)
    host.config = Config(tmp_path)
    host.hotkeys = None
    ok, message = CoreHost.set_hotkey(host, "Ctrl+Alt+X", kind="nope")
    assert ok is False
    assert "未知" in message
