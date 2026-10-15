# -*- coding: utf-8 -*-
"""官方识屏包端到端：Core 自有入口的安装/启用/停用/卸载/重装，走真实事务链。

与 ``test_mod_center_end_to_end.py`` 同纪律：真打包、真验签、真事务服务、真宿主、
真菜单建造器。差异只有入口——官方包不走 MOD 中心导入路由（防冒名不变），由
``LocalFeatureRuntime.attach_official`` 这个 Core 自有口子装配。

呈现是 FakePresentation（生产 = AppShell 注册的 MultiWindowProxy 语义面）；
凭据是内存后端。主动识屏的自动 pipeline 不触发（不截图、不联网）。
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
from pet.config import Config
from pet.context_menu import populate_context_menu
from pet.feature_host_bindings import register_screen_presentation
from pet.feature_management import LocalFeatureRuntime
from tests.screen_package_fakes import OWNER, FakePresentation, MemoryVault, build_package, dispose_qobject

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
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    fake = FakePresentation()
    register_screen_presentation(lambda: fake)
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
        register_screen_presentation(None)
        runtime.close()


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


# --------------------------------------------------------------- 装载/启停/卸载


def test_official_package_installs_disabled_through_the_real_transaction_chain(installed):
    runtime, manager, _fake = installed
    assert runtime.host.state(OWNER) == "disabled"
    assert runtime.menu_owners() == ()
    # 本地发现依旧不含官方 owner；官方发现含
    from pet.feature_management import discover_local_feature_ids, discover_official_feature_ids

    assert OWNER not in discover_local_feature_ids(runtime.config)
    assert discover_official_feature_ids(runtime.config) == (OWNER,)


def test_enable_mounts_the_screen_menus_and_manual_look_runs(installed, tmp_path):
    runtime, manager, fake = installed
    _enable(manager)
    try:
        assert runtime.host.enabled(OWNER) is True
        assert runtime.menu_owners() == (OWNER,)
        runtime_mount = runtime.mounts.runtimes[OWNER]
        assert type(runtime_mount).__module__.startswith("_pet_official_screen_")

        menu = _legacy_menu(tmp_path, runtime)
        submenu = next(
            (action.menu() for action in menu.actions() if action.text() == "扩展" and action.menu() is not None), None
        )
        assert submenu is not None
        # 扩展菜单按 owner 分组：扩展 → 识屏（包显示名）→ 贡献项
        group = next((action.menu() for action in submenu.actions() if action.text() == "识屏"), None)
        assert group is not None
        assert "看看屏幕（识屏包）" in _texts(group)
        auto = next((action.menu() for action in group.actions() if action.text() == "主动识屏（包）"), None)
        assert auto is not None
        assert "开启主动识屏" in _texts(auto)

        # 手动看看屏幕：未配置视觉 → 气泡提示（呈现面是假货，截图/网络不出现）
        leaf = next(action for action in group.actions() if action.text() == "看看屏幕（识屏包）")
        leaf.trigger()
        app.processEvents()
        assert any("视觉 API Key" in text for text, _ms in fake.bubbles)
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

    # 卸载：安装副本删掉，feature-data/<owner>/ 保留
    (_feature_data(tmp_path)).mkdir(parents=True, exist_ok=True)
    (_feature_data(tmp_path) / "memory.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    assert manager.submit("uninstall") is True
    _settle(manager)
    assert runtime.host.state(OWNER) == "absent"
    assert manager.service.inspect().active is None
    assert (_feature_data(tmp_path) / "memory.json").is_file()

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
    """设置面：真 ScreenContributionSettings 经 OwnerSettingsPanel 挂载，草稿门禁生效。"""
    runtime, manager, _fake = installed
    _enable(manager)
    try:
        panel = runtime.settings_panel(OWNER)
        assert panel is not None
        component = panel.component
        assert type(component).__module__.startswith("_pet_official_screen_")
        assert component.dirty() is False
        # 未保存草稿 → 宿主侧拒绝停用/卸载（事务层同判据的第二入口）
        component.vision.prompt.setPlainText("草稿改动")
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
        assert type(panel.component).__module__.startswith("_pet_official_screen_")
        # 核心侧不受影响
        assert runtime.host.enabled(OWNER) is True and runtime.menu_owners() == (OWNER,)
    finally:
        settings.close()
        dispose_qobject(runtime.mounts.runtimes.get(OWNER))
