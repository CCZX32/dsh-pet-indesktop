# -*- coding: utf-8 -*-
"""「扩展」子菜单：两条拓扑共用的**唯一**追加函数。

**为什么是唯一一处**：本仓库有两条渲染拓扑，两条各有一个菜单建造缝——legacy/capture
的 ``pet/context_menu.py::populate_context_menu``（``PetWindow._show_context_menu`` 的
唯一入口）与 overlay 的 ``pet/sprite_menu_facade.py::build_sprite_full_menu``
（``ShellOverlayWindow.contextMenuEvent`` 的唯一入口）。扩展子菜单如果各写一份，两边
迟早分叉；所以两边各自只留一行 ``append_extension_submenu(menu, pet)``。

**为什么在 ``MENU_ACTIONS`` 注册表之外追加**：注册表是用户编排
（``context_menu_layout``）与设置页布局编辑器的**契约源**，往里塞随安装状态变化的条目
会污染那张表与它的用例；而且没装任何扩展的用户会白看到一个空的「扩展」占位。子菜单
因此在注册表之外按需追加：**没有挂载中的贡献就连子菜单都不出现**。撤销也是结构性的
——两个建造器都是即建即用，未挂载的 owner 根本不会被渲染。

**归属（D2 spec §7.2）**：MOD 宿主是**进程级单例**（``AppShell`` 持有，会话横跨菜单
关闭），贡献是 **owner 级不是 pet 级**（v1 不提供"操作任意桌宠窗口"，所以要 pet 作用域
就得开 ``mod/v2``）。于是「扩展」子菜单在被点的每一只宠的菜单里逐项相同——act on the
runtime, not on the pet。

**Core 侧复核**：``handle.active`` 由 Core 在渲染时先看一遍，作者没做复核的
``invoke()`` 也不会执行（见 ``tests/test_mod_menu.py`` 的陈旧句柄用例）。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMenu

from .context_menus.shared import add_submenu

_LOG = logging.getLogger(__name__)

__all__ = ["SUBMENU_TITLE", "append_extension_submenu", "feature_runtime_for", "move_before_quit"]

#: 顶层子菜单标题（「退出」之前的那一项）。
SUBMENU_TITLE = "扩展"
#: 顶层「退出」的文案（``move_before_quit`` 的插入锚点；两条拓扑都是这一个字面量）。
_QUIT_TITLE = "退出"


def feature_runtime_for(pet_like):
    """从菜单宿主对象上取进程级扩展宿主；取不到返回 ``None``（菜单保持原样）。

    宿主是长寿命对象（``AppShell`` 持有），菜单每次弹出即建即用——所以这里只是读一个
    已经在那儿的引用，绝不新建任何东西。窗口与 overlay 壳都直接带 ``feature_runtime``；
    ``SpriteMenuFacade`` 由它转发。
    """
    if pet_like is None:
        return None
    runtime = getattr(pet_like, "feature_runtime", None)
    if runtime is not None:
        return runtime
    for name in ("shell", "app", "instance"):
        runtime = getattr(getattr(pet_like, name, None), "feature_runtime", None)
        if runtime is not None:
            return runtime
    return None


def move_before_quit(menu: QMenu, action) -> None:
    """把新增项插到「退出」之前（保持"设置/退出这只 紧邻退出"的既有分组）。

    显式摘除再插入 = 确定性移动；菜单里没有「退出」时什么都不做。
    """
    for candidate in menu.actions():
        if candidate is action:
            continue
        if candidate.text() == _QUIT_TITLE:
            menu.removeAction(action)
            menu.insertAction(candidate, action)
            return


def append_extension_submenu(menu: QMenu, pet_like) -> QMenu | None:
    """把「扩展」子菜单追加到 ``menu``；没有可渲染的贡献时返回 ``None`` 且不动菜单。

    内容按 owner 分组：``owner`` 显示名一级、作者的贡献项二级。每一项都由
    ``Contribution.factory(child_menu, handle)`` 自己建（作者拿到菜单与**自己的**句柄）；
    作者没给 factory 或 factory 抛错时退回贡献 id 并置灰——一个坏掉的 MOD 绝不能让
    桌宠的右键菜单整个炸掉。
    """
    runtime = feature_runtime_for(pet_like)
    if runtime is None:
        return None
    try:
        owners = runtime.menu_owners()
    except Exception:
        _LOG.exception("extension menu owners unavailable")
        return None
    if not owners:
        return None
    submenu = add_submenu(menu, SUBMENU_TITLE)
    try:
        for owner in owners:
            _append_owner_group(submenu, runtime, owner)
    except Exception:
        # 半路失败：把子菜单收走，宁可没有「扩展」也不要一棵残缺的树。
        _LOG.exception("extension menu could not be built")
        menu.removeAction(submenu.menuAction())
        submenu.deleteLater()
        return None
    if not submenu.actions():
        menu.removeAction(submenu.menuAction())
        submenu.deleteLater()
        return None
    move_before_quit(menu, submenu.menuAction())
    return submenu


def _append_owner_group(parent: QMenu, runtime, owner: str) -> None:
    try:
        handles = runtime.host.registry.list(owner=owner, scope=runtime.scope, kind="menu")
    except Exception:
        _LOG.exception("extension contributions unavailable: %s", owner)
        return
    active = [handle for handle in handles if getattr(handle, "active", False)]
    if not active:
        return
    group = add_submenu(parent, _owner_label(runtime, owner))
    for handle in active:
        _append_contribution(group, handle)


def _owner_label(runtime, owner: str) -> str:
    """owner 的显示名（``manifest.name`` 或 owner 本身）；读不出就是 owner。"""
    display = getattr(runtime, "display_name", None)
    if not callable(display):
        return str(owner)
    try:
        return str(display(owner) or owner)
    except Exception:
        _LOG.debug("extension display name unavailable: %s", owner, exc_info=True)
        return str(owner)


def _append_contribution(group: QMenu, handle) -> None:
    """作者自建的那一项；factory 缺失/抛错一律退回贡献 id（置灰，不是静默消失）。"""
    factory = getattr(getattr(handle, "descriptor", None), "factory", None)
    if callable(factory):
        try:
            handle.create(group, handle)
            return
        except Exception:
            # 失败会让这个句柄所在的一批贡献一起失效（Core 侧 reject_batch）。
            _LOG.exception("extension contribution failed: %s", getattr(handle.descriptor, "id", "?"))
    action = group.addAction(str(getattr(handle.descriptor, "id", "?")))
    action.setEnabled(False)
    action.setToolTip("这个扩展项当前不可用。")
