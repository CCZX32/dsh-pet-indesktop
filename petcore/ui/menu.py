"""右键菜单的统一入口（层级与弹出）。

菜单是 ``Qt.Popup``，默认落在「普通窗口」层；而桌宠与气泡在置顶时都带
``WindowStaysOnTopHint``，气泡又常在菜单之后 ``raise_()``——于是气泡把菜单压住。
这里把菜单放进与桌宠相同的层：桌宠置顶时菜单也置顶，先于任何气泡的再次抬起。

所有会弹出「属于桌宠的」菜单的地方（桌宠右键、扩展的快捷启动菜单）都走这两个函数，
各自写一份 ``exec`` 只会把这套层级规则漏掉一半。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from .menu_actions import availability, core_items, install_core_menu

__all__ = [
    "availability",
    "core_items",
    "install_core_menu",
    "prepare_menu",
    "show_context_menu",
]


def prepare_menu(menu: QMenu, *, topmost: bool = False) -> QMenu:
    """把菜单放进桌宠所在的层（幂等；不影响 QMenu 的点击外部关闭行为）。"""
    if topmost:
        if not (menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
            menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        menu.raise_()
    return menu


def show_context_menu(menu: QMenu, pos, *, topmost: bool = False) -> None:
    """弹出菜单：先按桌宠的层级摆好，再 ``exec``（阻塞到菜单关闭）。"""
    if menu is None:
        return
    prepare_menu(menu, topmost=topmost)
    menu.exec(pos)
