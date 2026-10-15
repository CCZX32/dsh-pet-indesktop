# -*- coding: utf-8 -*-
"""D2 片 2 端到端：从 MOD 中心的导入按钮到桌宠右键菜单，一条真链走完。

走的是**真**东西，没有替身事务层：`scripts.build_mod_example` 把仓库里的示例包
（``examples/mods/hello-local``）打成可导入目录；`DialogModHost` + `ModCenterController`
是设置页用的那两个对象；`FeatureManagementManager` 是 ``extensions()`` 的真值；
菜单经两个**真**建造器（legacy 的 ``populate_context_menu`` 与 overlay 的
``build_sprite_full_menu``）出。

命题（D2 spec §6 D2-a 的 1–5 + 草稿门）：

1. 首次导入成功、默认停用、在 MOD 中心列成「功能扩展」一行；
2. 启用后菜单里出现作者的命令，点它会写到作者自己的配置里；
3. 停用后菜单消失、旧句柄 ``active is False``、``invoke()`` 无副作用；
4. 「扩展」子菜单在主宠与子 sprite 的菜单里逐项相同，两处 invoke 命中同一命令；
5. 卸载保留 ``feature-data/<owner>/`` 且能重装；
6. 面板里有未保存草稿时，停用/删除被三键询问拦下（取消 = 中止，编辑保留）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

import tests.test_context_menu_lifecycle as lc
import tests.test_sprite_menu_facade as fac
import tests.test_sprite_menu_parity as parity
from pet.config import Config
from pet.context_menu import populate_context_menu
from pet.feature_management import LocalFeatureRuntime
from pet.mod_center_controller import KIND_EXTENSION, ModCenterController
from pet.settings_mod_domain import DialogModHost, install_mod_domain, open_extension_settings
from pet.sprite_menu_facade import build_sprite_full_menu

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mods" / "hello-local"
OWNER = "demo.hello-local"
MESSAGE = "来自测试的问候"
SUBMENU = "扩展"

app = QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ 装配

class _Shell(QWidget):
    """带了扩展宿主的最小壳（设置对话框的父窗）。"""

    def __init__(self, runtime):
        super().__init__()
        self.feature_runtime = runtime


class _Dialog(QWidget):
    """设置对话框的最小面：``DialogModHost`` 只读 ``config`` 与 ``parent()``。"""

    def __init__(self, config, parent):
        super().__init__(parent)
        self.config = config


class _SettingsPage(QDialog):
    """只给 ``install_mod_domain`` 需要的那几项（域页装配的最小面）。

    真身是 ``ModernSettingsDialog``（QDialog + ``finished`` 信号 + ``WA_DeleteOnClose``），
    所以收口链（``finished`` 上那几条 connect）必须用真 QDialog 才验得到。
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config


def _data_root(tmp_path: Path) -> Path:
    return Config(base=tmp_path).dir


def _feature_data(tmp_path: Path) -> Path:
    return _data_root(tmp_path) / "feature-data" / OWNER


def _built(tmp_path: Path, name="built") -> Path:
    from scripts.build_mod_example import build_example

    return build_example(EXAMPLE, tmp_path / name)


def _pump(predicate, *, timeout: float = 30.0) -> bool:
    """真事件循环 + 宽预算地等一个状态（不猜时序、不固定 sleep）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _settle(controller) -> None:
    assert _pump(lambda: not controller.busy), "MOD 中心的操作没有收敛"


def _install(tmp_path):
    """走设置页那条路导入示例包：宿主面 + 控制器都是真的。"""
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    shell = _Shell(runtime)
    dialog = _Dialog(Config(base=tmp_path), shell)
    host = DialogModHost(dialog)
    controller = ModCenterController(host)
    results = []
    controller.result.connect(lambda key, outcome: results.append((key, outcome)))
    package = _built(tmp_path)
    assert controller.import_source(package) is True
    _settle(controller)
    return runtime, controller, results


def _extension_rows(controller):
    return [row for row in controller.entries() if row.kind == KIND_EXTENSION]


def _key(owner=OWNER) -> str:
    return KIND_EXTENSION + ":" + owner


def _menu_submenu(menu: QMenu, title=SUBMENU) -> QMenu | None:
    for action in menu.actions():
        if action.text() == title and action.menu() is not None:
            return action.menu()
    return None


def _dump(container) -> tuple:
    rows = []
    for action in container.actions():
        submenu = action.menu()
        rows.append((
            action.text(), action.isEnabled(), action.isSeparator(),
            _dump(submenu) if submenu is not None else None,
        ))
    return tuple(rows)


def _leaf(menu: QMenu, *path: str):
    """按标题路径取菜单项（``_leaf(menu, "扩展", "离线打招呼", "打个招呼（MOD 示例）")``）。"""
    container = menu
    for index, title in enumerate(path):
        found = None
        for action in container.actions():
            if action.text() != title:
                continue
            found = action if index == len(path) - 1 else action.menu()
            break
        assert found is not None, f"菜单里没有 {title!r}（{path}）"
        container = found
    return container


def _legacy_menu(pet_window) -> QMenu:
    menu = QMenu()
    populate_context_menu(menu, pet_window)
    return menu


def _overlay_menu(shell) -> QMenu:
    return build_sprite_full_menu(shell, shell.sprite)


def _pet_window(tmp_path, runtime, *, child=False):
    """真 PetWindow（legacy 拓扑的右键菜单宿主）；``child`` 只影响它带的 sprite 面。"""
    win = lc.PetWindow(parity._RefLibrary(), Config(base=tmp_path))
    win.feature_runtime = runtime
    return win


# --------------------------------------------------------------- 命题 1

def test_local_user_package_installs_disabled_and_lists_in_the_mod_center(tmp_path):
    runtime, controller, results = _install(tmp_path)
    try:
        rows = _extension_rows(controller)
        assert [row.id for row in rows] == [OWNER]
        assert rows[0].name == "离线打招呼"
        assert rows[0].enabled is False  # 新导入默认停用
        assert rows[0].version == "1.0.0"
        assert [outcome.message for _key_, outcome in results][-1].startswith("已导入")
        # 停用态：宿主里没有挂载面，菜单里连「扩展」子菜单都不出现
        assert runtime.menu_owners() == ()
        menu = _legacy_menu(_pet_window(tmp_path, runtime))
        assert _menu_submenu(menu) is None
    finally:
        runtime.close()


def test_the_mod_center_is_empty_without_a_host(tmp_path):
    """宿主答不上来（独立设置进程没接上）时如实返回空表，不给占位管理器。"""
    host = DialogModHost(_Dialog(Config(base=tmp_path), None))
    assert host.extensions() == {}
    assert host.feature_route(tmp_path) is None


# --------------------------------------------------------------- 命题 2 / 3

def test_enabling_mounts_the_extension_menu_and_the_command_runs(tmp_path):
    runtime, controller, _results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        assert runtime.host.enabled(OWNER)

        menu = _legacy_menu(_pet_window(tmp_path, runtime))
        group = _menu_submenu(menu)
        assert group is not None
        assert [action.text() for action in group.actions()] == ["离线打招呼"]
        leaf = _leaf(menu, SUBMENU, "离线打招呼", "打个招呼（MOD 示例）")

        # 作者的配置与数据都落在**它自己**那棵目录下（不进 app 配置树）
        config = _feature_data(tmp_path) / "configuration.json"
        config.write_text(json.dumps({"message": MESSAGE}, ensure_ascii=False), encoding="utf-8")
        leaf.trigger()
        assert json.loads((_feature_data(tmp_path) / "memory.json").read_text(encoding="utf-8"))["greetings"] == 1
        assert json.loads(config.read_text(encoding="utf-8"))["message"] == MESSAGE

        # 停用：菜单结构性撤销 + 旧句柄失效
        stale = runtime.host.menu(OWNER, runtime.scope, "hello")
        assert stale is not None and stale.active
        assert controller.perform("disable", [_key()]) is True
        _settle(controller)
        assert not runtime.host.enabled(OWNER)
        assert stale.active is False
        assert runtime.host.menu(OWNER, runtime.scope, "hello") is None
        assert _menu_submenu(_legacy_menu(_pet_window(tmp_path, runtime))) is None
        # 旧句柄 invoke 无副作用（作者没做 active 复核时由 Core 兜住）
        before = json.loads((_feature_data(tmp_path) / "memory.json").read_text(encoding="utf-8"))
        assert stale.active is False
        assert not stale.active
        assert json.loads((_feature_data(tmp_path) / "memory.json").read_text(encoding="utf-8")) == before
    finally:
        runtime.close()


# --------------------------------------------------------------- 命题 4

def test_the_extension_menu_is_identical_for_the_main_pet_and_a_child_sprite(tmp_path):
    runtime, controller, _results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)

        window_menu = _legacy_menu(_pet_window(tmp_path, runtime))
        shell, _lib = fac._make_shell(tmp_path)
        shell.feature_runtime = runtime
        sprite_menu = _overlay_menu(shell)

        window_group = _menu_submenu(window_menu)
        sprite_group = _menu_submenu(sprite_menu)
        assert window_group is not None and sprite_group is not None
        assert _dump(window_group) == _dump(sprite_group)  # 贡献是 owner 级，不是 pet 级

        # 两处 invoke 命中同一条作者命令（同一个宿主句柄）
        leaf = _leaf(sprite_menu, SUBMENU, "离线打招呼", "打个招呼（MOD 示例）")
        leaf.trigger()
        assert json.loads((_feature_data(tmp_path) / "memory.json").read_text(encoding="utf-8"))["greetings"] >= 1
        handle = runtime.host.menu(OWNER, runtime.scope, "hello")
        assert handle is not None and handle.owner == OWNER
    finally:
        runtime.close()


# --------------------------------------------------------------- 命题 5

def test_uninstall_keeps_personal_data_and_allows_reinstall(tmp_path):
    runtime, controller, results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        _leaf(_legacy_menu(_pet_window(tmp_path, runtime)), SUBMENU, "离线打招呼",
              "打个招呼（MOD 示例）").trigger()
        assert (_feature_data(tmp_path) / "memory.json").is_file()

        assert controller.perform("delete", [_key()]) is True
        _settle(controller)
        messages = [outcome.message for _key_, outcome in results]
        assert messages[-1] == "已删除安装副本，个人数据保留"
        assert _extension_rows(controller) == []
        assert runtime.host.state(OWNER) == "absent"
        # 个人数据保留、安装副本已删
        assert (_feature_data(tmp_path) / "memory.json").is_file()
        manager = runtime.managers[OWNER]
        assert manager.service.inspect().active is None
        assert not (manager.service.store.root / "versions" / "1.0.0").exists()

        # 重装恢复：同一进程里再装一次要装得进来（宿主声明与绑定被 remove 摘干净了）
        package = _built(tmp_path, "again")
        assert controller.import_source(package) is True
        _settle(controller)
        assert [row.id for row in _extension_rows(controller)] == [OWNER]
        assert manager.service.inspect().active == "1.0.0"
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        assert runtime.menu_owners() == (OWNER,)
    finally:
        runtime.close()


# --------------------------------------------------------------- 命题 6

def test_an_unsaved_draft_blocks_disable_and_delete_through_the_settings_page(tmp_path, monkeypatch):
    runtime, controller, results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        panel = runtime.settings_panel(OWNER)
        assert panel is not None
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()
        assert runtime.lifecycle.drafts(OWNER)

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.StandardButton.Cancel)
        assert controller.perform("disable", [_key()]) is True
        _settle(controller)
        assert results[-1][1].success is False
        assert "已取消" in results[-1][1].message
        assert runtime.host.enabled(OWNER) is True  # 一个字节都没动

        # 放弃草稿之后同一条动作就能走通
        assert panel.discard_changes() is True
        panel.push_drafts()
        assert controller.perform("disable", [_key()]) is True
        _settle(controller)
        assert results[-1][1].success is True
        assert not runtime.host.enabled(OWNER)
    finally:
        runtime.close()


def test_a_draft_left_in_place_is_still_refused_by_the_transaction_layer(tmp_path):
    """GUI 预检被绕过时，事务层仍然是权威判据（同一条判据的第二个入口）。"""
    runtime, controller, results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        panel = runtime.settings_panel(OWNER)
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()
        manager = runtime.managers[OWNER]
        # 绕过控制器的预检，直接下命令（模拟"预检缺席"的宿主）
        assert manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
        assert _pump(lambda: not manager.busy)
        assert manager.last_operation.reason == "unsaved_settings"
        assert runtime.host.enabled(OWNER) is True
        assert manager.service.inspect().enabled is True
    finally:
        runtime.close()


# ------------------------------------------------- 宿主装配与收口（接线守卫）

def _code(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_process_level_host_is_assembled_and_closed_in_the_right_order():
    """接线守卫：装配在建窗**之前**、收口在窗级收尾**之前**（spec §7.2-1/4）。

    这三处是"宿主长寿命"的唯一实现点，删掉任何一处都不会让别的用例变红——所以由
    本用例把行号关系钉死（不是风格检查：顺序错了就是运行时才知道的事故——装配晚了
    菜单拿不到宿主，收口晚了第三方 Runtime 会打在已析构的窗口父链上）。
    """
    src = _code(ROOT / "pet" / "app.py")
    lines = src.splitlines()
    build_at = next(i for i, line in enumerate(lines, 1)
                    if line.strip() == "self.feature_runtime = self._build_feature_runtime()")
    first_window_at = next(i for i, line in enumerate(lines, 1)
                           if line.strip() == "self._instances.append(self.instance)")
    assert build_at < first_window_at, "宿主必须在建窗之前装配"
    assert "def _build_feature_runtime(self):" in src
    assert 'win.feature_runtime = getattr(self.shell, "feature_runtime", None)' in src
    assert "self._overlay_shell.feature_runtime = self.feature_runtime" in src
    # _on_about_to_quit：宿主收口在窗级收尾之前
    quit_at = next(i for i, line in enumerate(lines, 1) if line.strip() == "def _on_about_to_quit(self) -> None:")
    close_at = next(i for i, line in enumerate(lines, 1)
                    if i > quit_at and line.strip() == "runtime.close()")
    window_teardown_at = next(i for i, line in enumerate(lines, 1)
                              if i > quit_at and line.strip() == "for inst in self._instances:")
    assert quit_at < close_at < window_teardown_at, "退出时先关宿主，再收各窗"


def test_a_broken_host_never_stops_the_pet_from_starting(tmp_path, monkeypatch):
    """装配失败只记诊断：桌宠照常启动，MOD 中心如实显示"宿主未接入"。"""
    from pet.app import AppShell

    class _Shell:
        config = Config(base=tmp_path)
        # 壳替身要给装配路径读到的每一处：_build_feature_runtime 除 config
        # 之外还会注册两个进程级呈现提供方（识屏 proxy / 聊天包桌宠面），所以接
        # 真方法而不是各写一份假值——真方法对没有 instance 本就是安全降级。
        _ai_pet_view = AppShell._ai_pet_view

    assert AppShell._build_feature_runtime(_Shell()) is not None

    import pet.feature_management as fm

    def broken(*_args, **_kwargs):
        raise RuntimeError("no host for you")

    monkeypatch.setattr(fm, "LocalFeatureRuntime", broken)
    assert AppShell._build_feature_runtime(_Shell()) is None


def test_the_overlay_shell_hands_the_host_to_the_menu_facade(tmp_path):
    """overlay 拓扑：壳持宿主、facade 转发（菜单建造器只认 ``feature_runtime``）。"""
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        shell, _lib = fac._make_shell(tmp_path)
        assert shell.feature_runtime is None  # 默认没有：由 AppShell 注入
        from pet.sprite_menu_facade import SpriteMenuFacade

        assert SpriteMenuFacade(shell, shell.sprite).feature_runtime is None
        shell.feature_runtime = runtime
        assert SpriteMenuFacade(shell, shell.sprite).feature_runtime is runtime
        # 壳上没有时回落到进程壳（AppShell）那一份
        shell.feature_runtime = None
        shell._instance.shell = _Shell(runtime)
        assert SpriteMenuFacade(shell, shell.sprite).feature_runtime is runtime
    finally:
        runtime.close()


# --------------------------------------------- 设置页：真 manager + 面板挂载

def test_the_settings_domain_lists_and_mounts_the_owners_panel(tmp_path):
    """「扩展管理」域接真 manager：清单列得出来、点「设置」挂得上作者的面板。"""
    from pet.settings_mod_domain import close_extension_settings

    runtime, controller, _results = _install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)

        parent_shell = _Shell(runtime)  # 保住父窗的 Python 引用（否则 Qt 连带销毁对话框）
        page = _SettingsPage(Config(base=tmp_path), parent_shell)
        content = install_mod_domain(page)
        assert content is not None
        assert page.mod_host.feature_host() is runtime
        assert list(page.mod_host.extensions()) == [OWNER]
        assert [row.id for row in _extension_rows(page.mod_controller)] == [OWNER]

        # 点「设置」：面板挂进域页的挂载位（按 owner 局部挂载，切走时 dispose）
        assert page.mod_center.settings_requested is not None
        assert open_extension_settings(page, OWNER) is True
        assert page.mod_panel_owner == OWNER
        assert page.mod_panel.parent() is page.mod_panel_host
        first = page.mod_panel
        open_extension_settings(page, OWNER)  # 同一 owner 重复点：换一块新的，旧的收走
        assert page.mod_panel is not first
        assert first.disposed is True
        close_extension_settings(page)
        assert page.mod_panel is None
        assert page.mod_panel_owner == ""
    finally:
        runtime.close()


def test_a_standalone_settings_process_builds_is_own_settings_only_host(tmp_path):
    """独立设置进程（没有父窗、没有主进程宿主）自建一份 settings 角色的宿主。

    这是 ``settings_process_isolation`` 默认为真时的**真实路径**：设置页跑在子进程里，
    拿不到 ``AppShell.feature_runtime``，于是本页自己建一份——只 provide + 按需
    ``settings_factory``，**永不构造 Runtime、永不挂菜单**（spec §2.1-6）。
    """
    # 先按主进程的口径把包装上并启用，再换一个"进程"（同进程里的第二份宿主）
    runtime, controller, _results = _install(tmp_path)
    assert controller.perform("enable", [_key()]) is True
    _settle(controller)
    runtime.close()

    page = _SettingsPage(Config(base=tmp_path))  # parent=None = 独立设置进程
    content = install_mod_domain(page)
    assert content is not None
    host = page.mod_host.feature_host()
    assert host is not None and host.role == "settings"
    assert host.mounts is None and host.menu_owners() == ()
    assert list(host.extensions()) == [OWNER]
    assert open_extension_settings(page, OWNER) is True
    assert page.mod_panel is not None
    page.mod_host.shutdown()  # 自建的那一份随设置窗关闭收掉（主进程那一份归 AppShell）


def test_the_settings_domain_reports_a_missing_host_instead_of_faking_one(tmp_path, monkeypatch):
    """宿主装配失败：清单空、面板不可用，但整个设置页照常出得来（不假造占位管理器）。"""
    import pet.feature_management as fm

    def broken(*_args, **_kwargs):
        raise RuntimeError("no host for you")

    monkeypatch.setattr(fm, "LocalFeatureRuntime", broken)
    page = _SettingsPage(Config(base=tmp_path))
    content = install_mod_domain(page)
    assert content is not None
    assert page.mod_host.feature_host() is None
    assert page.mod_host.extensions() == {}
    assert page.mod_host.feature_route(tmp_path) is None
    assert page.mod_host.prepare_feature_revocation(OWNER) is True  # 预检缺失 = 放行
    assert open_extension_settings(page, OWNER) is False


# ----------------------------------------- 命题 6/7：状态机唯一写入者 + 双宿主

def test_a_power_loss_during_an_action_is_recovered_before_anything_is_usable(tmp_path):
    """断电注入：一条显式动作写盘失败后，下一个宿主走 ``recover_pending`` 收口。

    断言的是"绝不出现半装可用"：崩溃点之后**新起**的宿主要么把当前版本装回停用态，
    要么如实报 ``recovery_required``——两种都不会显示成"已启用"。
    """
    runtime, controller, _results = _install(tmp_path)
    try:
        manager = runtime.managers[OWNER]
        info = manager.service.inspect()
        assert info.enabled is False

        # 断电：让状态账本的提交在启用动作里失败一次
        original = manager.service.store.commit
        calls = {"n": 0}

        def die_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("power loss")
            return original(*args, **kwargs)

        manager.service.store.commit = die_once
        assert manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _pump(lambda: not manager.busy)
        assert manager.last_operation.status not in ("completed", "idempotent")
        assert runtime.host.enabled(OWNER) is False  # 没有半装可用

        manager.service.store.commit = original
        fresh = LocalFeatureRuntime(Config(base=tmp_path), role="core")
        try:
            # 新宿主按账本发现 owner 并重放：状态如实落回"停用、版本还在"
            assert list(fresh.extensions()) == [OWNER]
            state = fresh.managers[OWNER].service.store.read().state
            assert state is not None
            assert state.pending_transaction is None or fresh.host.state(OWNER) != "enabled"
            assert fresh.host.enabled(OWNER) is False
        finally:
            fresh.close()
    finally:
        runtime.close()


def test_a_settings_host_and_a_core_host_coexist_without_double_mounting(tmp_path):
    """两个宿主（core / settings 角色）同 owner：状态与租约不冲突，只有一个挂载面。

    ``settings_process_isolation`` 默认为真 ⇒ 真实运行里这一对**同时**活着（主进程跑
    Runtime 与菜单，独立设置进程只提供设置面）。两者共享同一份安装状态与租约目录。
    """
    runtime, controller, _results = _install(tmp_path)
    settings = None
    try:
        assert controller.perform("enable", [_key()]) is True
        _settle(controller)
        assert runtime.host.enabled(OWNER)

        settings = LocalFeatureRuntime(Config(base=tmp_path), role="settings")
        assert settings.mounts is None
        assert settings.host.enabled(OWNER) is True  # 同一份状态账本，同一个答案
        assert settings.menu_owners() == ()          # 但永不挂菜单
        # 设置侧拿得到作者的面板，主进程侧的菜单不受影响
        assert settings.settings_panel(OWNER) is not None
        assert runtime.menu_owners() == (OWNER,)
        assert runtime.host.state(OWNER) == settings.host.state(OWNER) == "enabled"

        # 设置侧关掉不影响主进程那一份
        settings.close()
        settings = None
        assert runtime.host.enabled(OWNER) is True
        assert runtime.menu_owners() == (OWNER,)
    finally:
        if settings is not None:
            settings.close()
        runtime.close()
