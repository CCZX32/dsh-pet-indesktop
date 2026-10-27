from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QMenu

from petcore.ui.menu_model import MenuItem, MenuModel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_menu_icons_have_owned_submenus_and_reserved_geometry(app):
    parent = QMenu()
    model = MenuModel()
    model.register(MenuItem("settings", "设置", icon="settings"))
    model.register(MenuItem("child", "子项", icon="refresh"))
    menu = model.build_layout(
        [
            {
                "type": "submenu",
                "id": "group",
                "label": "工具",
                "icon": "application",
                "children": [{"type": "action", "id": "settings"}],
            },
            {"type": "action", "id": "child"},
        ],
        parent,
    )
    try:
        assert menu.parent() is parent
        submenu = menu.actions()[0].menu()
        assert submenu is not None
        assert submenu.parent() is menu
        # 图标槽位的真值走 QSS 的 `icon-size`（`QMenu::icon { left/width }` 被 Qt 忽略）。
        assert "icon-size: 18px" in menu.styleSheet()
        action = submenu.actions()[0]
        assert not action.icon().isNull()
        size = action.icon().actualSize(QSize(24, 24))
        assert size.width() > 0 and size.height() > 0
    finally:
        menu.deleteLater()
        parent.deleteLater()
