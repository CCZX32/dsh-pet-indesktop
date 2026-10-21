from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.config import Config
from petcore.ui.app import CoreHost
from petcore.ui.pet_manager import PetManager

CLICK_TEXT = "点击回应"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def live_host(app, tmp_path: Path, monkeypatch):
    # 只跳过真实角色素材的扫描：CoreHost / FeatureManager / PetManager 全是真的。
    monkeypatch.setattr("petcore.content.collect.load_all", lambda **_kw: [])

    config = Config(tmp_path)
    config.set("click_talk_enabled", True)
    config.set("click_talk_texts", [CLICK_TEXT])
    # 配图概率默认 30%，随机出图时气泡 label 是空的；这条用例只验文字台词。
    config.set("self_talk_image_chance", 0)
    config.set("collision_sound", False)
    config.set("active_pets", [0, 1])
    Config(
        tmp_path,
        {
            "character": "fallback",
            "click_talk_enabled": True,
            "click_talk_texts": [CLICK_TEXT],
            "self_talk_image_chance": 0,
        },
        filename="config-pet-1.json",
    ).save()

    host = CoreHost(app, config, tmp_path, ())
    manager = PetManager(host, tmp_path, config)
    host.pets = manager
    character = host.character_for("fallback")
    primary = manager.create_primary(character)
    host.window = primary
    host.attach_window(primary)
    manager.restore()
    child = manager.window_for_slot(1)
    assert child is not None
    yield host, manager, primary, child
    host.features.stop()
    manager.shutdown()


def test_restored_child_gets_click_listeners(live_host) -> None:
    host, _manager, primary, child = live_host

    assert paths.pet_config_path(host.root, 1).exists()
    assert primary._click_listeners
    assert child._click_listeners, "restore() 产生的子宠必须补挂点击监听"


def test_click_talk_fires_for_primary_and_child(live_host) -> None:
    host, _manager, primary, child = live_host

    primary.config.set("click_talk_texts", ["主宠台词"])
    child.config.set("click_talk_texts", ["子宠台词"])
    for window, expected in ((primary, "主宠台词"), (child, "子宠台词")):
        host._active_window = window
        window.bubble.label.setText("")
        window._notify_click()
        assert window.bubble.label.text() == expected


def test_attach_window_is_idempotent_and_cancel_removes_the_listener(live_host) -> None:
    _host, manager, _primary, child = live_host
    interaction = manager.host.features.ports.interaction
    calls: list[object] = []

    cancel = interaction.on_click("test", lambda window: calls.append(window))
    interaction.attach_window(child)

    child._notify_click()
    assert calls == [child]

    interaction.attach_window(child)
    child._notify_click()
    assert calls == [child, child], "重复 attach 不得让一次点击触发两次"

    cancel()
    child._notify_click()
    assert calls == [child, child]


def test_reload_menu_reads_ui_font_size(live_host) -> None:
    host, _manager, primary, _child = live_host

    host.config.set("ui_font_size", 16)
    host.reload_menu(primary)
    assert host.menu_model._font_size == 16


def test_apply_live_settings_updates_menu_font(live_host) -> None:
    host, _manager, _primary, _child = live_host

    host.config.set("ui_font_size", 17)
    host.apply_live_settings()

    assert host.menu_model._font_size == 17
