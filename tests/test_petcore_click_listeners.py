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


def test_click_balance_bubble_comes_first_and_click_talk_follows(live_host, monkeypatch) -> None:
    """开「点击查看余额」时：余额气泡先冒，收起后才通知点击台词（不再先闪一条台词）。"""
    host, _manager, primary, _child = live_host
    host._active_window = primary
    balance_calls: list[tuple[int | None, bool]] = []
    monkeypatch.setattr(
        host,
        "request_balance",
        lambda slot=None, force=True: balance_calls.append((slot, force)),
        raising=False,
    )
    primary.config.set("click_show_balance", True)
    primary.config.set("click_talk_texts", ["余额之后的台词"])
    primary.bubble.label.setText("")

    primary._on_click()
    assert balance_calls == [(0, True)], "点击仍要触发余额请求"
    assert primary.bubble.label.text() == "", "台词不许抢在余额前面"

    # 宿主把余额气泡冒出来后通知窗口
    primary.bubble.show_text("余额 ¥1.00", primary.bubble_anchor_rect(), 6000)
    primary.notify_click_balance_presented()
    assert primary.bubble.label.text() == "余额 ¥1.00"

    primary.bubble.hide()  # 余额气泡收起 → 台词接上
    assert primary.bubble.label.text() == "余额之后的台词"


def test_cached_balance_shown_inside_the_request_still_queues_the_talk(live_host, monkeypatch) -> None:
    """缓存命中时余额气泡在 `request()` 里**同步**冒出（presented 早于排队建立）。"""
    host, _manager, primary, _child = live_host
    host._active_window = primary
    primary.config.set("click_show_balance", True)
    primary.config.set("click_talk_texts", ["缓存之后"])
    primary.bubble.label.setText("")

    def synchronous_request(slot=None, *, force=True):
        primary.bubble.show_text("余额 ¥1.00", primary.bubble_anchor_rect(), 6000)
        primary.notify_click_balance_presented()

    monkeypatch.setattr(host, "request_balance", synchronous_request, raising=False)
    primary._on_click()
    assert primary.bubble.label.text() == "余额 ¥1.00"
    primary.bubble.hide()
    assert primary.bubble.label.text() == "缓存之后"


def test_repeated_clicks_queue_a_single_click_talk(live_host, monkeypatch) -> None:
    """连点只排一条台词（跟着最后一次点击），气泡收起后只通知一次。"""
    host, _manager, primary, _child = live_host
    host._active_window = primary
    monkeypatch.setattr(host, "request_balance", lambda slot=None, force=True: None, raising=False)
    primary.config.set("click_show_balance", True)
    primary.config.set("click_talk_texts", ["只冒一次"])
    fired: list[int] = []
    primary.add_click_listener(lambda _window: fired.append(1))
    try:
        primary.bubble.label.setText("")
        primary._on_click()
        primary._on_click()
        primary._on_click()
        assert fired == []
        primary.bubble.show_text("余额 ¥1.00", primary.bubble_anchor_rect(), 6000)
        primary.notify_click_balance_presented()
        primary.bubble.hide()
        assert len(fired) == 1
        assert primary.bubble.label.text() == "只冒一次"
    finally:
        primary.remove_click_listener(fired.append)


def test_click_talk_falls_back_when_no_balance_bubble_ever_shows(live_host, monkeypatch) -> None:
    """余额结果一直不来（或免打扰把气泡拦了）时，兜底时限到了仍要冒台词。"""
    from PySide6.QtTest import QTest

    from petcore.ui.pet_window import PetWindow

    host, _manager, primary, _child = live_host
    host._active_window = primary
    monkeypatch.setattr(host, "request_balance", lambda slot=None, force=True: None, raising=False)
    monkeypatch.setattr(PetWindow, "CLICK_TALK_FALLBACK_MS", 40, raising=False)
    primary.config.set("click_show_balance", True)
    primary.config.set("click_talk_texts", ["兜底台词"])
    primary.bubble.label.setText("")

    primary._on_click()
    assert primary.bubble.label.text() == ""
    QTest.qWait(160)
    assert primary.bubble.label.text() == "兜底台词"


def test_click_talk_still_fires_when_the_host_cannot_show_balance(live_host, monkeypatch) -> None:
    """宿主没有余额回调时不许把台词扣住（主分支 `callable(...)` 的回落口径）。"""
    host, _manager, primary, _child = live_host
    host._active_window = primary
    monkeypatch.setattr(host, "request_balance", None, raising=False)
    primary.config.set("click_show_balance", True)
    primary.config.set("click_talk_texts", ["照常说话"])
    primary.bubble.label.setText("")

    primary._on_click()
    assert primary.bubble.label.text() == "照常说话"


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
