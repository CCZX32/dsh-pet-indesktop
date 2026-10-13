# -*- coding: utf-8 -*-
"""「截图」右键菜单接线：注册项、模板位置、三条文案与可用性（offscreen）。

菜单是本片唯一的产品入口（全局热键是后续片），所以这里钉死三件事：

1. **它真的在树上**：注册表有 ``screen_capture`` 这一项、默认模板把它排在
   「看看屏幕」之后（都是屏幕类入口），老用户布局（模板里没这个节点）也会被
   合并策略补上——不然"升级后入口不见了"；
2. **三条叶子各自的可用性如实**：本地 OCR 引擎没接上就置灰 + 写明原因
   （``CONTEXT.md`` 的 Runtime Disabled：留位置、解释原因，不是消失）；
   没有聊天能力时「问答」整条不出现（Capability Unavailable）；
3. **点击路由到宿主**：三条叶子各自打到 ``on_screen_capture_ocr / _translate /
   _ask``，名字对不上就是"入口在、点了没反应"。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from pet import menu_layout  # noqa: E402
from pet.context_menu import populate_context_menu  # noqa: E402
from pet.context_menus import registry as registry_mod  # noqa: E402
from pet.context_menus import shared as shared_mod  # noqa: E402
from pet.screen_capture import actions as actions_mod  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_os_touching_menus(monkeypatch):
    """默认菜单里另有开机自启/角色清单两处系统面：按 test_menu_layout 的既有口径
    打桩，免得测截图入口时先在别的入口上炸。"""
    from pet import catalog
    from pet.context_menus import shared as menu_shared

    monkeypatch.setattr(menu_shared.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(catalog, "list_available_characters", lambda: ["shenshen"])


class _FakeConfig:
    def __init__(self) -> None:
        self.values = {
            "context_menu_layout": None,
            "context_menu_appearance": {"theme": "light"},
            "character": "shenshen",
            "agent_link": {},
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self) -> None:
        return None


class _FakePet:
    """只提供截图三入口的宿主替身（其余菜单项靠 ``__getattr__`` 兜底）。

    数值/清单属性照抄 ``tests/test_menu_layout.py`` 的 FakePet：默认菜单的其它
    建造器（播放速率 / 动画分类 / 大小 / 桌宠控制）会读它们，替身缺一个就会在
    别处先炸，测不到本片要验的东西。
    """

    playback_speed = scale = 1.0
    drag_physics = no_move = mouse_through = False
    idles = ["待机"]
    turns = moves = clicks = acts = []

    def __init__(self, *, chat: bool = True, surfaces: bool = True) -> None:
        self.cfg = _FakeConfig()
        self.calls: list[str] = []
        if surfaces:
            self.on_screen_capture_ocr = lambda: self.calls.append("ocr")
            self.on_screen_capture_translate = lambda: self.calls.append("translate")
            # 无聊天能力时宿主给的问答回调是 None（与 PetWindow/SpriteMenuFacade 同形）
            self.on_screen_capture_ask = (
                (lambda: self.calls.append("ask")) if chat else None
            )

    def icon_pixmap(self, size: int = 64):
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap(size, size)
        pixmap.fill()
        return pixmap

    def __getattr__(self, name):
        if name.startswith("on_screen_capture_"):
            raise AttributeError(name)   # 宿主没接这套面
        return lambda *args, **kwargs: None


def _screen_capture_menu(pet=None) -> QMenu:
    menu = QMenu()
    populate_context_menu(menu, pet or _FakePet())
    action = next(
        (item for item in menu.actions() if item.text() == "截图"), None
    )
    assert action is not None, "截图子菜单没出现在右键菜单上"
    submenu = action.menu()
    assert submenu is not None, "截图必须是子菜单（三个功能挂它下面）"
    return submenu


def test_registry_registers_the_screen_capture_group():
    assert "screen_capture" in registry_mod.MENU_ACTIONS.ids
    assert registry_mod.ACTION_LABELS["screen_capture"] == "截图"
    assert registry_mod.ACTION_ICONS["screen_capture"] == "screen"


def test_default_layout_puts_the_group_right_after_look_screen():
    layout = menu_layout.load_default_menu_layout("modern-default-v1")
    ids = [
        node.get("id") for node in layout["nodes"]
        if isinstance(node, dict) and node.get("type") == "action"
    ]
    assert "screen_capture" in ids
    assert ids.index("screen_capture") == ids.index("look_screen") + 1


def test_saved_user_layout_gets_the_new_entry_merged_in(tmp_path):
    """老用户布局（存盘时还没有截图）必须被合并策略补上，不许静默消失。"""
    old_layout = {
        "schema_version": 1,
        "layout_id": "user",
        "nodes": [
            {"type": "action", "id": "ojingjing", "visible": True},
            {"type": "action", "id": "look_screen", "visible": True},
            {"type": "action", "id": "modern_settings", "visible": True},
            {"type": "action", "id": "quit", "visible": True},
        ],
    }
    result = menu_layout.resolve_menu_layout(
        old_layout,
        registered_actions=registry_mod.MENU_ACTIONS.ids,
        available_actions=registry_mod.MENU_ACTIONS.ids,
    )
    ids = [node.get("id") for node in result.nodes]
    assert "screen_capture" in ids
    assert ids.index("screen_capture") == ids.index("look_screen") + 1


def test_three_leaves_are_reachable_with_their_own_callbacks(monkeypatch):
    monkeypatch.setattr(actions_mod, "ocr_engine_available", lambda: True)
    monkeypatch.setattr(actions_mod, "translation_engine_available", lambda: True)
    pet = _FakePet()
    submenu = _screen_capture_menu(pet)
    labels = [action.text() for action in submenu.actions() if not action.isSeparator()]
    assert labels == ["提取文字", "翻译", "问答"]

    for label in labels:
        action = next(item for item in submenu.actions() if item.text() == label)
        assert action.isEnabled() is True
        action.trigger()
    assert pet.calls == ["ocr", "translate", "ask"]


def test_leaves_explain_why_they_are_greyed_out_before_the_engines_land(monkeypatch):
    """引擎/通道没到位时留位置 + 写明原因，绝不假装能做（点了没反应是缺陷）。"""
    monkeypatch.setattr(actions_mod, "ocr_engine_available", lambda: False)
    monkeypatch.setattr(actions_mod, "translation_engine_available", lambda: False)
    submenu = _screen_capture_menu()
    leaves = {action.text(): action for action in submenu.actions() if not action.isSeparator()}

    assert leaves["提取文字"].isEnabled() is False
    assert "尚未接入" in leaves["提取文字"].toolTip()
    assert leaves["翻译"].isEnabled() is False
    assert "后续片" in leaves["翻译"].toolTip()
    # 「问答」不依赖本地引擎：通道在就可用
    assert leaves["问答"].isEnabled() is True


def test_leaves_turn_enabled_once_the_engines_are_wired(monkeypatch):
    monkeypatch.setattr(actions_mod, "ocr_engine_available", lambda: True)
    monkeypatch.setattr(actions_mod, "translation_engine_available", lambda: True)
    submenu = _screen_capture_menu()
    leaves = [action for action in submenu.actions() if not action.isSeparator()]
    assert [action.isEnabled() for action in leaves] == [True, True, True]
    # 可用态不再挂"为什么用不了"的说明（QAction 的 tooltip 缺省回落到文案本身）
    assert all("尚未接入" not in action.toolTip() for action in leaves)
    assert all("后续片" not in action.toolTip() for action in leaves)


def test_ask_leaf_disappears_without_a_chat_capability():
    """能力不可用 = 整条不出现（无聊天变体下不许留个点了没反应的问答）。"""
    submenu = _screen_capture_menu(_FakePet(chat=False))
    labels = [action.text() for action in submenu.actions() if not action.isSeparator()]
    assert labels == ["提取文字", "翻译"]


def test_group_is_hidden_when_the_host_has_no_screen_capture_surface():
    """宿主没接这套回调（纯桌宠变体）= 能力不可用 → 整组不出现。"""
    menu = QMenu()
    populate_context_menu(menu, _FakePet(surfaces=False))
    assert "截图" not in [action.text() for action in menu.actions()]


def test_real_hosts_expose_the_three_entries():
    """三条入口在两个真实宿主上都接了线（只查菜单树会漏：两边同时缺也"自证"通过）。

    单窗拓扑 = ``PetWindow``；sprite 拓扑 = ``OverlayShell``（``SpriteMenuFacade``
    只是每次右键重建的转发面，真正的长期宿主是壳）。三个名字缺任何一个，
    菜单上那组就会因为"能力不可用"整组消失，而只比对菜单树的用例抓不到。
    """
    from pet.overlay_shell import OverlayShell
    from pet.sprite_menu_facade import SpriteMenuFacade
    from pet.window import PetWindow

    names = ("on_screen_capture_ocr", "on_screen_capture_translate", "on_screen_capture_ask")
    for host in (PetWindow, OverlayShell, SpriteMenuFacade):
        for name in names:
            assert isinstance(getattr(host, name, None), property), (
                f"{host.__name__}.{name} 没接线")


def test_disabled_reason_constants_are_shared_with_the_builder():
    """置灰原因只有一份真值（注册表/建造器不再各写一套文案）。"""
    assert "尚未接入" in shared_mod.SCREEN_CAPTURE_OCR_DISABLED_REASON
    assert "后续片" in shared_mod.SCREEN_CAPTURE_TRANSLATE_DISABLED_REASON


def test_menu_and_panel_read_the_same_reason_objects():
    """菜单 tooltip 与结果浮层状态行必须是**同一个字符串**，不是两份同文复印件。

    两份字面量的下场：改一处漏一处 → 菜单说"引擎尚未接入"，点下去浮层说的是另一句。
    所以这里断的是身份（``is``）而不是"内容相等"。
    """
    assert shared_mod.SCREEN_CAPTURE_OCR_DISABLED_REASON is actions_mod.OCR_PENDING_REASON
    assert (shared_mod.SCREEN_CAPTURE_TRANSLATE_DISABLED_REASON
            is actions_mod.TRANSLATION_PENDING_REASON)
    from pet.screen_capture import reasons

    assert reasons.OCR_PENDING_REASON is actions_mod.OCR_PENDING_REASON
