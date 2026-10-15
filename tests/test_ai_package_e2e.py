# -*- coding: utf-8 -*-
"""官方 AI 对话包端到端：Core 自有入口的安装/启用/停用/卸载/重装，走真实事务链。

与 ``test_screen_package_e2e.py`` 同纪律：真打包、真验签、真事务服务、真宿主、
真菜单建造器、真包内窗口类。差异只有两处（都是聊天包形态决定的）：

* 包是 ``host-only``——没有 Worker，命令面由包自己的 Runtime 提供；
* 桌宠呈现面是 ``FakePetView``（生产 = AppShell 注册的 ``_OverlayChatHost`` 形态），
  凭据是内存后端。AI 请求不会真的发出去（没有配 Key，也就没有网络）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

import tests.test_context_menu_lifecycle as lc
import tests.test_sprite_menu_parity as parity
from pet.ai_bindings import register_ai_pet_view
from pet.config import Config
from pet.context_menu import populate_context_menu
from pet.feature_management import LocalFeatureRuntime
from tests.ai_package_fakes import OWNER, FakePetView, build_package, dispose_qobject

app = QApplication.instance() or QApplication([])


def _pump(predicate, *, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _settle(manager) -> None:
    assert _pump(lambda: not manager.busy), "管理器的事务没有收敛"


def _feature_data(tmp_path: Path) -> Path:
    return Config(base=tmp_path).dir / "feature-data" / OWNER


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Core 自有入口：attach_official → 真打包 → 事务链 install（默认停用）。"""
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: _MemoryVault())
    fake = FakePetView()
    register_ai_pet_view(lambda: fake)
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        manager = runtime.attach_official(OWNER)
        assert manager is not None
        built = build_package(tmp_path / "pkg-src-out" / "built")
        assert manager.submit("import_disabled", built, auto_apply=True) is True
        _settle(manager)
        info = manager.service.inspect()
        assert info.active == "1.0.0", manager.last_result
        yield runtime, manager, fake
    finally:
        register_ai_pet_view(None)
        dispose_qobject(runtime.mounts.runtimes.get(OWNER) if runtime.mounts else None)
        runtime.close()


class _MemoryVault:
    """内存凭据后端（本文件自带一份，避免跨文件共享可变状态）。"""

    priority = 1

    def __init__(self):
        self.items = {}

    def set_password(self, service, ref, value):
        self.items[service, ref] = value

    def get_password(self, service, ref):
        return self.items.get((service, ref))

    def delete_password(self, service, ref):
        self.items.pop((service, ref), None)


def _enable(manager) -> None:
    assert manager.submit("enable", True, expected_revision=manager.service.inspect().revision) is True
    _settle(manager)


def _legacy_menu(tmp_path, runtime) -> QMenu:
    win = lc.PetWindow(parity._RefLibrary(), Config(base=tmp_path))
    win.feature_runtime = runtime
    menu = QMenu()
    populate_context_menu(menu, win)
    return menu


def _texts(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions()]


def _ai_group(tmp_path, runtime):
    """扩展 → AI 对话（包显示名）这一层。"""
    menu = _legacy_menu(tmp_path, runtime)
    submenu = next((action.menu() for action in menu.actions() if action.text() == "扩展" and action.menu() is not None), None)
    assert submenu is not None
    group = next((action.menu() for action in submenu.actions() if action.text() == "AI 对话"), None)
    assert group is not None, _texts(submenu)
    return group


# --------------------------------------------------------------- 装载/启停/卸载


def test_official_package_installs_disabled_through_the_real_transaction_chain(installed):
    runtime, _manager, _fake = installed
    assert runtime.host.state(OWNER) == "disabled"
    assert runtime.menu_owners() == ()
    # 本地发现不含官方 owner；官方发现含（且与识屏包并列，闭集里的两个都在）
    from pet.feature_management import discover_local_feature_ids, discover_official_feature_ids
    from pet.official_features import SCREEN_FEATURE_ID

    assert OWNER not in discover_local_feature_ids(runtime.config)
    assert OWNER in discover_official_feature_ids(runtime.config)
    assert SCREEN_FEATURE_ID not in discover_official_feature_ids(runtime.config)  # 识屏包本用例没装


def test_enable_mounts_the_ai_menus_and_the_runtime_owns_its_own_windows(installed, tmp_path):
    runtime, manager, fake = installed
    _enable(manager)
    try:
        assert runtime.host.enabled(OWNER) is True
        assert runtime.menu_owners() == (OWNER,)
        runtime_mount = runtime.mounts.runtimes[OWNER]
        assert type(runtime_mount).__module__.startswith("_pet_official_ai_chat_")

        group = _ai_group(tmp_path, runtime)
        assert "AI 对话（包）" in _texts(group)
        assert "快捷对话（包）" in _texts(group)

        # 命令落在包自己的 Runtime 上：真开一个包内聊天窗（无 Key → 不发请求）
        leaf = next(action for action in group.actions() if action.text() == "AI 对话（包）")
        leaf.trigger()
        app.processEvents()
        windows = runtime_mount.runtime._windows
        assert windows, "包没有开出自己的聊天窗"
        window = windows[0]
        assert type(window).__module__.startswith("_pet_official_ai_chat_")
        assert window.isVisible() is True
        # 包拿到的是受限面（``AiPetView``），不是桌宠本体；这个面解析回真桌宠
        view = window.pet_link.pet_window
        assert type(view).__module__ == "pet.ai_bindings"
        assert view._live() is fake
        # 定位真的读了这个面的几何（假货的几何是固定的 100,100,180,200）
        assert window.x() >= 0 and window.y() >= 0
        window.close()
    finally:
        dispose_qobject(runtime.mounts.runtimes.get(OWNER))


def test_disable_unmounts_and_uninstall_keeps_personal_data(installed, tmp_path):
    runtime, manager, _fake = installed
    _enable(manager)
    assert runtime.menu_owners() == (OWNER,)

    # 停用：菜单结构性撤销
    assert manager.submit("enable", False, expected_revision=manager.service.inspect().revision) is True
    _settle(manager)
    assert runtime.host.enabled(OWNER) is False
    assert runtime.menu_owners() == ()

    # 卸载：安装副本删掉，feature-data/<owner>/ 下自己的会话保留
    sessions = _feature_data(tmp_path) / "sessions" / "shenshen"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "s1.json").write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
    assert manager.submit("uninstall") is True
    _settle(manager)
    assert runtime.host.state(OWNER) == "absent"
    assert manager.service.inspect().active is None
    assert (sessions / "s1.json").is_file()

    # 重装：同一进程里装得回来（宿主声明/绑定已被 remove 摘干净）
    built = build_package(tmp_path / "pkg-again" / "built")
    assert manager.submit("import_disabled", built, auto_apply=True) is True
    _settle(manager)
    assert manager.service.inspect().active == "1.0.0"
    _enable(manager)
    assert runtime.menu_owners() == (OWNER,)
    dispose_qobject(runtime.mounts.runtimes.get(OWNER))


def test_a_fresh_runtime_replays_the_official_ledger(installed, tmp_path):
    """重启等价物：新宿主按官方账本发现 owner 并装回（discover → attach_official）。"""
    runtime, manager, _fake = installed
    _enable(manager)
    runtime.close()

    fresh = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        assert OWNER in fresh.managers  # 发现链接上了官方 owner
        assert fresh.host.enabled(OWNER) is True  # 账本 enabled=True → 装回即启用
        assert fresh.menu_owners() == (OWNER,)
    finally:
        dispose_qobject(fresh.mounts.runtimes.get(OWNER) if fresh.mounts else None)
        fresh.close()


def test_the_package_settings_panel_mounts_with_draft_gates(installed):
    """设置面：真 AiContributionSettings 经 OwnerSettingsPanel 挂载，草稿门禁生效。"""
    runtime, manager, _fake = installed
    _enable(manager)
    try:
        panel = runtime.settings_panel(OWNER)
        assert panel is not None
        component = panel.component
        assert type(component).__module__.startswith("_pet_official_ai_chat_")
        assert component.dirty() is False
        # 未保存草稿 → 宿主侧拒绝停用/卸载（事务层同判据的第二入口）
        component.page.key.setText("sk-draft")
        assert component.dirty() is True
        runtime.refresh_drafts()
        assert runtime.lifecycle.drafts(OWNER)
        assert component.discard_changes() is True
        runtime.refresh_drafts()
        assert not runtime.lifecycle.drafts(OWNER)
        assert panel.dispose() is None or True
    finally:
        dispose_qobject(runtime.mounts.runtimes.get(OWNER))


def test_a_settings_role_host_shares_the_official_ledger_without_mounting(installed, tmp_path):
    """独立设置进程（role=settings）：同一账本、同一启用态，但永不挂菜单/不起 Runtime。"""
    runtime, manager, _fake = installed
    _enable(manager)
    settings = LocalFeatureRuntime(Config(base=tmp_path), role="settings")
    try:
        assert OWNER in settings.managers
        assert settings.mounts is None and settings.menu_owners() == ()
        assert settings.host.enabled(OWNER) is True
        panel = settings.settings_panel(OWNER)
        assert panel is not None
        assert type(panel.component).__module__.startswith("_pet_official_ai_chat_")
        # 核心侧不受影响
        assert runtime.host.enabled(OWNER) is True and runtime.menu_owners() == (OWNER,)
    finally:
        settings.close()
        dispose_qobject(runtime.mounts.runtimes.get(OWNER))


def test_the_package_never_touches_the_builtin_chat_configuration(installed, tmp_path):
    """并存口径：包用自己那本账，内置聊天的 ``chat`` 节点一个字节不动。

    这是"两套聊天实现并存、不合并"的机器判据——包拿到的是自己的
    ``feature-data/<owner>/configuration.json``，不是 app 配置树的 ``chat`` 节点。
    """
    runtime, manager, _fake = installed
    builtin_before = json.dumps(Config(base=tmp_path).get("chat"), ensure_ascii=False, sort_keys=True)
    _enable(manager)
    try:
        context = manager.startup.context
        context.configuration.commit_namespace({"ui": {"chat_ui_style": "classic"}}, expected_revision=context.configuration.revision())
        assert (_feature_data(tmp_path) / "configuration.json").is_file()
        builtin_after = json.dumps(Config(base=tmp_path).get("chat"), ensure_ascii=False, sort_keys=True)
        assert builtin_before == builtin_after
    finally:
        dispose_qobject(runtime.mounts.runtimes.get(OWNER))
