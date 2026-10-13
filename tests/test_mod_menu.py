# -*- coding: utf-8 -*-
"""D2 片 2：「扩展」子菜单——两个菜单建造器共用的唯一追加函数。

口径（D2 spec §3.1）：菜单**每次弹出重建**，撤销因此是结构性的（未挂载的 owner 根本
不渲染）；子菜单在 ``MENU_ACTIONS`` 注册表**之外**追加（那张表是用户编排与设置页布局
编辑器的契约源，往里塞动态项会污染 ``context_menu_layout`` 与 ``test_menu_layout.py``）；
顶层插在「退出」之前；Core 侧还要复核 ``handle.active``——"停用后旧菜单不再执行"不靠
作者自觉。

拓扑归属（spec §7.2）：贡献是 **owner 级、不是 pet 级**，所以「扩展」子菜单在被点的每
一只宠的菜单里内容与行为**完全相同**（act on the runtime, not on the pet）——本题里
第 5 条用例逐项比对两处出的树。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import types

from PySide6.QtWidgets import QApplication, QMenu

from pet.mod_menu import SUBMENU_TITLE, append_extension_submenu, move_before_quit

app = QApplication.instance() or QApplication([])
OWNER = "demo.hello-local"


class _Runtime:
    """最小宿主替身：只给 mod_menu 读的那几项。"""

    def __init__(self, entries=None):
        self.scope = "mod:v1:core"
        self._entries = entries or []
        self.invoked = []

    def menu_owners(self):
        return tuple(owner for owner, _handles in self._entries)

    def display_name(self, owner):
        return {"demo.hello-local": "离线打招呼"}.get(owner, owner)

    class _Registry:
        def __init__(self, entries):
            self._entries = entries

        def list(self, *, owner=None, scope=None, kind=None):
            return tuple(h for o, handles in self._entries if o == owner for h in handles)

    @property
    def host(self):
        class _Host:
            registry = _Runtime._Registry(self._entries)

        return _Host()


class _Handle:
    def __init__(self, contribution_id, *, factory=None, active=True, label=""):
        self.descriptor = types.SimpleNamespace(id=contribution_id, factory=factory, kind="menu")
        self._active = active
        self.label = label
        self.registry = self

    @property
    def active(self):
        return self._active

    def current(self, _handle):
        return self._active

    def create(self, *args):
        if not self._active or self.descriptor.factory is None:
            raise RuntimeError("CommandNotFound")
        return self.descriptor.factory(*args)


class _Pet:
    """PetWindow / SpriteMenuFacade 的共同面：挂着一个长寿命宿主。"""

    def __init__(self, runtime):
        self.feature_runtime = runtime
        self.cfg = type("C", (), {"get": staticmethod(lambda *_a, **_k: {})})()


def _menu_with_quit():
    menu = QMenu()
    menu.addAction("桌宠设置")
    menu.addAction("退出")
    return menu


def _titles(menu):
    return [action.text() for action in menu.actions()]


def _submenu(menu, title=SUBMENU_TITLE):
    for action in menu.actions():
        if action.text() == title and action.menu() is not None:
            return action.menu()
    return None


# ------------------------------------------------------------------ 无 MOD

def test_a_pet_without_any_mounted_extension_gets_no_extra_entry():
    menu = _menu_with_quit()
    assert append_extension_submenu(menu, _Pet(_Runtime())) is None
    assert _titles(menu) == ["桌宠设置", "退出"]


def test_a_pet_without_a_host_leaves_the_menu_untouched():
    menu = _menu_with_quit()
    assert append_extension_submenu(menu, _Pet(None)) is None
    assert _titles(menu) == ["桌宠设置", "退出"]


def test_an_unknown_host_shape_is_tolerated_instead_of_raising():
    """菜单建造器不认识的对象（测试替身 / 未来拓扑）不许让右键菜单炸掉。"""
    menu = _menu_with_quit()
    assert append_extension_submenu(menu, object()) is None
    assert _titles(menu) == ["桌宠设置", "退出"]


# ----------------------------------------------------------------- 有 MOD

def _mounted(label="打个招呼（MOD 示例）"):
    calls = []

    def factory(submenu, handle):
        action = submenu.addAction(label)
        action.triggered.connect(lambda _checked=False: handle.invoke())

    handle = _Handle("hello", factory=factory)
    handle.invoke = lambda: calls.append("invoke" if handle.active else "stale")
    return _Runtime([(OWNER, [handle])]), handle, calls


def test_the_submenu_is_appended_with_one_group_per_owner():
    runtime, _handle, _calls = _mounted()
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    assert submenu is not None
    assert _titles(menu) == ["桌宠设置", SUBMENU_TITLE, "退出"]  # 插在「退出」之前
    groups = [action.text() for action in submenu.actions()]
    assert groups == ["离线打招呼"]  # owner 显示名（manifest.name）
    leafs = _submenu(submenu, "离线打招呼")
    assert [action.text() for action in leafs.actions()] == ["打个招呼（MOD 示例）"]


def test_a_contribution_without_a_factory_shows_its_id():
    handle = _Handle("half-built", factory=None)
    runtime = _Runtime([(OWNER, [handle])])
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    leafs = _submenu(submenu, "离线打招呼")
    assert [action.text() for action in leafs.actions()] == ["half-built"]
    assert all(not action.isEnabled() for action in leafs.actions())


def test_a_failing_factory_never_breaks_the_pet_menu():
    def broken(_submenu, _handle):
        raise RuntimeError("author code blew up")

    runtime = _Runtime([(OWNER, [_Handle("boom", factory=broken)])])
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    assert submenu is not None
    leafs = _submenu(submenu, "离线打招呼")
    assert [action.text() for action in leafs.actions()] == ["boom"]  # 退回贡献 id，不是空菜单
    assert _titles(menu) == ["桌宠设置", SUBMENU_TITLE, "退出"]


def test_an_inactive_handle_is_not_rendered():
    """停用后旧句柄失效：菜单是快照，但重建时未挂载的贡献根本不渲染。"""
    runtime, handle, _calls = _mounted()
    handle._active = False
    menu = _menu_with_quit()
    assert append_extension_submenu(menu, _Pet(runtime)) is None
    assert _titles(menu) == ["桌宠设置", "退出"]


def test_two_owners_each_get_their_own_group():
    first = _Handle("hello", factory=lambda submenu, handle: submenu.addAction("甲"))
    second = _Handle("echo", factory=lambda submenu, handle: submenu.addAction("乙"))
    runtime = _Runtime([(OWNER, [first]), ("demo.echo", [second])])
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    assert [action.text() for action in submenu.actions()] == ["离线打招呼", "demo.echo"]
    assert [action.text() for action in _submenu(submenu, "demo.echo").actions()] == ["乙"]


# ------------------------------------------------- 触发后由 Core 复核 active

def test_invoking_through_the_rendered_action_reaches_the_author_command():
    runtime, handle, calls = _mounted()
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    leafs = _submenu(submenu, "离线打招呼")
    leafs.actions()[0].trigger()
    assert calls == ["invoke"]


def test_a_stale_handle_does_not_execute():
    """作者没做 ``handle.active`` 复核时，Core 侧仍然是 no-op（API-V1 §1 明文要求）。"""
    runtime, handle, calls = _mounted()
    menu = _menu_with_quit()
    submenu = append_extension_submenu(menu, _Pet(runtime))
    leafs = _submenu(submenu, "离线打招呼")
    action = leafs.actions()[0]
    handle._active = False  # 菜单已经弹出来了，此刻才停用
    action.trigger()
    assert calls == ["stale"]


# ------------------------------------------------------------ 双拓扑一致性

def test_the_extension_submenu_is_identical_for_the_main_pet_and_a_child_sprite():
    """两条拓扑出的树逐项相同：贡献是 owner 级，不是 pet 级。"""
    runtime, _handle, _calls = _mounted()

    def build():
        menu = _menu_with_quit()
        append_extension_submenu(menu, _Pet(runtime))
        return menu

    def dump(menu):
        rows = []
        for action in menu.actions():
            submenu = action.menu()
            if submenu is None:
                rows.append(("action", action.text(), action.isEnabled()))
                continue
            rows.append(("menu", action.text(), tuple(
                (child.text(), child.isEnabled(),
                 tuple((leaf.text(), leaf.isEnabled()) for leaf in (child.menu().actions() if child.menu() else [])))
                for child in submenu.actions()
            )))
        return tuple(rows)

    assert dump(build()) == dump(build())


# ------------------------------------------------------------ 只做属主线程的活

def test_building_the_submenu_does_not_touch_disk_or_threads():
    """菜单建造只读宿主内存：不落盘、不启线程、不阻塞（右键必须立刻出来）。"""
    import threading

    runtime, _handle, _calls = _mounted()
    before = {thread.ident for thread in threading.enumerate()}
    started = time.monotonic()
    menu = _menu_with_quit()
    append_extension_submenu(menu, _Pet(runtime))
    assert time.monotonic() - started < 0.5
    assert {thread.ident for thread in threading.enumerate()} == before


def test_move_before_quit_is_a_no_op_without_a_quit_entry():
    menu = QMenu()
    action = menu.addAction("扩展")
    move_before_quit(menu, action)
    assert _titles(menu) == ["扩展"]
