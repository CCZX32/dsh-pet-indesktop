# -*- coding: utf-8 -*-
"""右键菜单「网络信息」入口的接线契约（issue #172）。

覆盖：注册表三件套（label/icon/默认布局节点）、显隐门（``network_info_menu_enabled``
默认开、关掉即不可用）、两套建造器共用的建造函数、AppShell 接线与弹窗单例。

真实菜单树端的覆盖在既有套件里（不在这里重复造 stub）：
``tests/test_menu_layout.py::test_default_layout_populates_real_qmenu_hierarchy``
断言现代菜单「工具与帮助」里有这一项；``tests/test_sprite_menu_parity.py``
的 legacy/modern 树比对与 REQUIRED_LABELS 逐项包含它，并覆盖点击路由。

弹窗在本文件里一律替换成不发真实请求的替身（真探针的真实取数由实机验证覆盖）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import network_info_dialog as dialog_mod
from pet.config import Config
from pet.context_menus import registry as registry_mod
from pet.context_menus.shared import add_network_info, network_info_menu_enabled
from pet.menu_layout import load_default_menu_layout

app = QApplication.instance() or QApplication([])


class _Cfg:
    def __init__(self, values: dict):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Pet:
    def __init__(self, values: dict | None = None, *, with_callback: bool = True):
        self.cfg = _Cfg(values or {})
        self.calls = 0
        if with_callback:
            self.on_network_info = self._open

    def _open(self):
        self.calls += 1


def _labels(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _find(menu, label: str):
    for action in menu.actions():
        if action.text() == label:
            return action
    raise AssertionError(f"菜单缺项 {label}；实际 = {_labels(menu)}")


# ---------------------------------------------------------------- 注册表契约
def test_registry_declares_label_icon_and_layout_node():
    assert registry_mod.ACTION_LABELS["network_info"] == "网络信息"
    assert registry_mod.ACTION_ICONS["network_info"] == "web"
    assert "network_info" in registry_mod.MENU_ACTIONS.ids

    def ids(nodes) -> list[str]:
        found = []
        for node in nodes:
            if node.get("type") == "action":
                found.append(str(node.get("id")))
            found.extend(ids(node.get("children", [])))
        return found

    assert "network_info" in ids(load_default_menu_layout().get("nodes", []))


def test_gate_default_on_and_missing_callback_counts_as_unavailable():
    assert network_info_menu_enabled(_Pet()) is True
    assert network_info_menu_enabled(_Pet({"network_info_menu_enabled": False})) is False
    assert network_info_menu_enabled(object()) is True  # 无 cfg 的宿主按默认开

    assert "network_info" in registry_mod.MENU_ACTIONS.available_ids(_Pet())
    assert "network_info" not in registry_mod.MENU_ACTIONS.available_ids(
        _Pet({"network_info_menu_enabled": False}))
    assert "network_info" not in registry_mod.MENU_ACTIONS.available_ids(
        _Pet(with_callback=False))


def test_availability_helper_matches_registry_gate():
    """两套 facade 的显隐判定同源：注册表 available 与建造器走同一个函数。"""
    def available(pet) -> bool:
        return "network_info" in registry_mod.MENU_ACTIONS.available_ids(pet)

    for pet in (_Pet(), _Pet({"network_info_menu_enabled": False}),
                _Pet(with_callback=False)):
        assert available(pet) is registry_mod._network_info_available(pet)


# ---------------------------------------------------------------- 建造函数
def test_add_network_info_builds_action_with_click_callback():
    pet = _Pet()
    menu = QMenu()
    try:
        action = add_network_info(menu, pet, icons=False)
        assert action is not None
        assert action.text() == "网络信息"
        assert action.property("closeOnTrigger") is True
        action.trigger()
        assert pet.calls == 1
    finally:
        menu.close()
        app.processEvents()


def test_add_network_info_returns_none_when_hidden_or_no_callback():
    """legacy 建造器直接调它：关掉设置或无回调时不得留下点了没反应的项。"""
    for pet in (_Pet({"network_info_menu_enabled": False}),
                _Pet({"network_info_menu_enabled": True}, with_callback=False)):
        menu = QMenu()
        try:
            assert add_network_info(menu, pet) is None
            assert _labels(menu) == []
        finally:
            menu.close()
            app.processEvents()


def test_add_network_info_uses_semantic_vector_icon():
    from pet.context_menus.icons import vector_menu_icon

    pet = _Pet()
    menu = QMenu()
    try:
        action = add_network_info(menu, pet, icons=True)
        expected = vector_menu_icon(menu, "web")
        assert not action.icon().isNull()
        assert action.icon().pixmap(16, 16).toImage() == expected.pixmap(16, 16).toImage()
    finally:
        menu.close()
        app.processEvents()


# ---------------------------------------------------------------- AppShell 接线
class _QuietDialog(dialog_mod.NetworkInfoDialog):
    """不发真实请求的弹窗替身（只验证接线与单例语义）。"""

    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)
        self.refreshed = 0

    def refresh(self) -> None:  # 真探针要发外网请求，测试里一律跳过
        self.refreshed += 1


@pytest.fixture
def quiet_dialog(monkeypatch):
    monkeypatch.setattr(dialog_mod, "NetworkInfoDialog", _QuietDialog)


def test_wire_window_injects_network_info_callback(tmp_path, quiet_dialog):
    from pet.app import AppShell

    shell = AppShell(app, Config(tmp_path))

    class _Win:
        pass

    win = _Win()
    shell.instance._wire_window(win)
    assert callable(getattr(win, "on_network_info", None))


def test_open_network_info_is_single_process_level_dialog(tmp_path, quiet_dialog):
    from pet.app import AppShell

    shell = AppShell(app, Config(tmp_path))
    try:
        shell.open_network_info()
        dialog = shell.network_info_dialog
        assert isinstance(dialog, _QuietDialog)
        assert dialog.refreshed == 1, "弹窗显示时应当取一次数据"
        shell.open_network_info()
        assert shell.network_info_dialog is dialog, "非模态单例：再次点击复用同一窗"
    finally:
        if shell.network_info_dialog is not None:
            shell.network_info_dialog.close()
            shell.network_info_dialog = None
