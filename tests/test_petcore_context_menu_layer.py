"""右键菜单的层级：桌宠置顶时菜单也必须置顶，否则会被气泡压住。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

from petcore.ui.menu import prepare_menu, show_context_menu


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_prepare_menu_moves_the_menu_into_the_pet_layer(app) -> None:
    menu = QMenu()
    prepare_menu(menu, topmost=True)

    assert menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_prepare_menu_leaves_a_normal_pet_untouched(app) -> None:
    """桌宠不置顶时菜单也不该置顶：否则它会压在别的应用之上。"""
    menu = QMenu()
    prepare_menu(menu, topmost=False)

    assert not (menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    menu.deleteLater()
    app.processEvents()


def test_show_context_menu_tolerates_a_missing_menu(app) -> None:
    """测试替身把 ``build_menu`` 打成 ``None`` 时不许炸（旧代码直接 exec）。"""
    show_context_menu(None, None, topmost=True)
