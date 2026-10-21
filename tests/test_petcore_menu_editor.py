from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.ui.menu_model import MenuItem, MenuModel
from petcore.ui.settings.menu_editor import MenuEditor


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class Host:
    def __init__(self, root: Path):
        self.config = Config(root)
        self.menu_model = MenuModel()
        self.reloaded = 0
        self.tray = None
        for item_id, label in (("a", "A"), ("b", "B"), ("c", "C")):
            self.menu_model.register(MenuItem(item_id, label, icon="application"))
        self.menu_model.set_availability({"a": True, "b": True, "c": True})

    def reload_menu(self):
        self.reloaded += 1


def _host(tmp_path: Path) -> Host:
    host = Host(tmp_path)
    host.config.set(
        "menu_layout",
        {
            "schema_version": 1,
            "layout_id": "petcore-default-v1",
            "nodes": [
                {"type": "action", "id": "a", "visible": True},
                {"type": "action", "id": "b", "visible": True},
                {"type": "action", "id": "c", "visible": False},
            ],
        },
    )
    return host


def test_editor_loads_layout_and_reads_visibility(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    editor = MenuEditor(host, host.menu_model)
    assert editor.tree.topLevelItemCount() == 3
    assert editor.tree.topLevelItem(1).text(0) == "B"
    assert editor.tree.topLevelItem(2).checkState(0) == Qt.CheckState.Unchecked


def test_move_and_checkbox_produce_new_order(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    editor = MenuEditor(host, host.menu_model)
    editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
    editor.move_selected(-1)
    editor.tree.topLevelItem(2).setCheckState(0, Qt.CheckState.Unchecked)
    nodes = editor.value()["nodes"]
    assert [node["id"] for node in nodes] == ["b", "a", "c"]
    assert nodes[2]["visible"] is False
    assert editor.is_dirty()


def test_alias_icon_submenu_and_separator(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    editor = MenuEditor(host, host.menu_model)
    editor.tree.setCurrentItem(editor.tree.topLevelItem(0))
    editor.rename_selected("主角色")
    editor.set_selected_icon("character")
    first = editor.value()["nodes"][0]
    assert first["alias"] == "主角色"
    assert first["icon"] == "character"

    editor.add_submenu("我的菜单")
    submenu = next(node for node in editor.value()["nodes"] if node["type"] == "submenu")
    assert submenu["label"] == "我的菜单"

    editor.insert_separator()
    types = [node["type"] for node in editor.value()["nodes"]]
    assert "separator" in types


def test_confirm_save_persists_and_reloads(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    editor = MenuEditor(host, host.menu_model)
    editor.tree.setCurrentItem(editor.tree.topLevelItem(0))
    editor.rename_selected("X")
    editor.confirm_save()
    saved = host.config.get("menu_layout")
    assert saved["nodes"][0]["alias"] == "X"
    assert host.reloaded == 1
    assert not editor.is_dirty()


def test_reset_default_keeps_mod_actions(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    host.menu_model.register(MenuItem("official.demo:hello", "打招呼", owner="official.demo"))
    host.menu_model.set_availability({"official.demo:hello": True})
    editor = MenuEditor(host, host.menu_model)
    editor.reset_default()
    hub = next(
        node for node in editor.value()["nodes"] if node.get("id") == "extensions_hub"
    )
    assert any(node.get("id") == "official.demo:hello" for node in hub["children"])


def test_discard_restores_initial_layout(qapp, tmp_path) -> None:
    host = _host(tmp_path)
    editor = MenuEditor(host, host.menu_model)
    editor.tree.setCurrentItem(editor.tree.topLevelItem(0))
    editor.rename_selected("临时")
    assert editor.is_dirty()
    editor.discard()
    assert editor.value()["nodes"][0].get("alias") is None
