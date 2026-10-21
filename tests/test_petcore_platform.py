from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.config import Config
from petcore.platform import autostart, hotkey_spec
from petcore.platform.hotkeys import GlobalHotkeyService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_hotkey_spec_normalize_and_reject():
    assert hotkey_spec.normalize("ctrl+alt+p") == "Ctrl+Alt+P"
    assert hotkey_spec.normalize("P") == ""
    assert hotkey_spec.normalize("Ctrl+Alt") == ""
    assert hotkey_spec.display("") == "未设置"


def test_hotkey_service_registers_and_clears(app):
    calls = []

    class User32:
        def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):
            calls.append(("register", hotkey_id, modifiers, vk))
            return True

        def UnregisterHotKey(self, hwnd, hotkey_id):
            calls.append(("unregister", hotkey_id))
            return True

    service = GlobalHotkeyService(app, user32=User32(), supported=True)
    assert service.install()
    ok, message = service.apply("ctrl+alt+p", lambda: None)
    assert ok, message
    assert service.active_text == "Ctrl+Alt+P"
    assert calls[0][0] == "register"
    service.clear()
    assert service.active_text == ""
    assert calls[-1][0] == "unregister"
    service.uninstall()


def test_hotkey_service_reports_registration_failure(app):
    class User32:
        def RegisterHotKey(self, *args):
            return False

        def UnregisterHotKey(self, *args):
            return True

    service = GlobalHotkeyService(app, user32=User32(), supported=True)
    ok, message = service.apply("Ctrl+Alt+P", lambda: None)
    assert ok is False
    assert "占用" in message


def test_hotkey_service_is_unsupported_off_windows(app):
    service = GlobalHotkeyService(app, supported=False)
    ok, message = service.apply("Ctrl+Alt+P", lambda: None)
    assert ok is False
    assert "不支持" in message


def test_config_normalizes_hotkey(tmp_path):
    config = Config(tmp_path, {"hotkey_toggle_pet": "ctrl+shift+x"})
    assert config.get("hotkey_toggle_pet") == "Ctrl+Shift+X"


def test_autostart_command_uses_frozen_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\dsh-pet-core.exe")
    assert autostart.command_text() == r'"C:\Apps\dsh-pet-core.exe"'


def test_instance_roots_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    assert paths.data_root(instance="pet2") == tmp_path / "dsh-pet-core-pet2"
    assert paths.data_root(instance=None) == tmp_path / "dsh-pet-core"
    with pytest.raises(ValueError):
        paths.data_root(instance="bad name")


def test_provision_wrapper_calls_frameseq_pipeline(tmp_path, monkeypatch):
    from pet import frameseq_provision
    from petcore.media import provision

    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "idle.webm").write_bytes(b"")
    calls = []

    def fake_once(videos_dir, frameseq_root, **kwargs):
        calls.append((Path(videos_dir), Path(frameseq_root), kwargs))
        return SimpleNamespace(converted=2, retired=1)

    monkeypatch.setattr(frameseq_provision, "provision_once", fake_once)
    character = SimpleNamespace(
        root=tmp_path,
        animations=[SimpleNamespace(path=videos / "idle.webm")],
    )
    report = provision.provision_character(character, budget_seconds=5, migration_clips=1)
    assert report.converted == 2
    assert calls[0][0] == videos
    assert calls[0][1] == tmp_path / "frameseq"
    assert calls[0][2]["round_seconds"] == 5.0
    assert calls[0][2]["migration_clips"] == 1
