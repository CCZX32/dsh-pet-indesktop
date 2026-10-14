# -*- coding: utf-8 -*-
"""D2 片 2：``FeatureManagementManager`` 与进程级功能扩展宿主。

这一片接的三条线，每条都在这里钉住：

1. **管理器是 MOD 中心看到的真值**（``DialogModHost.extensions()`` 不再恒空）；
2. **启停 / 卸载走片 1 的生命周期**：启用在宿主里挂上贡献、停用撤销贡献、卸载保留
   ``feature-data/<owner>/`` 且可重装；
3. **草稿门**：面板里有未保存编辑时，停用/卸载在事务层被 ``draft_blocked`` 挡住，
   状态与安装副本一个都不许动。

材料用仓库里**真的示例包**（``examples/mods/hello-local``）经 ``scripts/build_mod_example``
打成可导入目录——不是替身包，验签/指纹/清单全链真跑。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet.config import Config
from pet.feature_management import (
    FEATURE_CAPABILITIES,
    API_VERSION,
    FeatureManagementManager,
    LocalFeatureRuntime,
    LocalUserTrustSelfChecker,
)
from pet.plugins.feature_host import FeatureHost
from pet.settings_mod_panel import OwnerSettingsPanel

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mods" / "hello-local"
OWNER = "demo.hello-local"
VERSION = "1.0.0"

app = QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ 材料

def _built(tmp_path: Path) -> Path:
    from scripts.build_mod_example import build_example

    return build_example(EXAMPLE, tmp_path / "built")


def _config(tmp_path: Path) -> Config:
    return Config(base=tmp_path)


def _wait(predicate, *, timeout: float = 30.0) -> bool:
    """真事件循环 + 宽预算地等一个**状态**（不猜时序、不固定 sleep）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _runtime(tmp_path, *, role="core") -> LocalFeatureRuntime:
    return LocalFeatureRuntime(_config(tmp_path), role=role)


def _install(runtime, tmp_path, *, auto_apply=True) -> FeatureManagementManager:
    """导入示例包并把管理器交回（首次导入 = feature_route 建管理器 + 本地源导入）。"""
    package = _built(tmp_path)
    owner = runtime.route(package)
    assert owner == OWNER
    manager = runtime.managers[OWNER]
    assert manager.submit_local_source(package, auto_apply=auto_apply, enabled=False)
    assert _wait(lambda: not manager.busy), "导入没有收敛"
    return manager


# ------------------------------------------------------- 自检器：显式用户信任

def test_the_local_self_checker_is_explicit_trust_not_a_sandbox_claim(tmp_path):
    """它只复核验签与 worker 路径，**不**声称任何 OS 隔离（availability 恒 True）。"""
    from pet.plugins.package_trust import FeaturePackageVerifier

    verifier = FeaturePackageVerifier(
        core_version=_core_version(), api_version=API_VERSION, feature_id=OWNER,
        allowed_capabilities=FEATURE_CAPABILITIES, allow_local_packages=True, platform=sys.platform,
    )
    checker = LocalUserTrustSelfChecker(verifier)
    assert checker.available is True  # 默认的 fail-closed 不适用于本地用户信任路径
    descriptor = verifier.verify(_built(tmp_path))
    assert checker.check(descriptor).status == "ready"
    source = next((Path(EXAMPLE) / name for name in ("host", "settings.py")))
    assert source.exists()
    assert not hasattr(checker, "isolation_enforced")


def test_the_local_self_checker_refuses_a_swapped_package(tmp_path):
    from pet.plugins.package_trust import FeaturePackageVerifier

    package = _built(tmp_path)
    verifier = FeaturePackageVerifier(
        core_version=_core_version(), api_version=API_VERSION, feature_id=OWNER,
        allowed_capabilities=FEATURE_CAPABILITIES, allow_local_packages=True, platform=sys.platform,
    )
    descriptor = verifier.verify(package)
    (package / "host" / "factory.py").write_text("def create_host():\n    raise SystemExit\n", encoding="utf-8")
    result = LocalUserTrustSelfChecker(verifier).check(descriptor)
    assert result.status == "failed"
    assert result.reason == "self_check_verification_failed"


def _core_version() -> str:
    from pet import __version__

    return __version__


# --------------------------------------------------------------- 宿主装配

def test_a_fresh_data_root_has_no_managers_and_a_ready_menu(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        assert runtime.extensions() == {}
        assert runtime.menu_owners() == ()  # 没装任何东西 ⇒ 菜单一个 owner 都不出
    finally:
        runtime.close()


def test_route_reads_the_bounded_manifest_and_builds_the_manager(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        before = set(sys.modules)
        owner = runtime.route(_built(tmp_path))
        assert owner == OWNER
        assert list(runtime.extensions()) == [OWNER]
        # 只读清单、**不导入**包代码（路由之后 sys.modules 里一个新命名空间都不该多）
        assert not {name for name in set(sys.modules) - before if name.startswith("_pet_official_screen")}
    finally:
        runtime.close()


def test_route_refuses_a_package_that_is_not_a_local_mod(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        junk = tmp_path / "junk"
        junk.mkdir()
        (junk / "manifest.json").write_text("{}", encoding="utf-8")
        assert runtime.route(junk) is None
        assert runtime.extensions() == {}
    finally:
        runtime.close()


# ----------------------------------------------- 导入 / 启用 / 停用 / 卸载

def test_import_installs_disabled_and_never_mounts_the_menu(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        info = manager.service.inspect()
        assert info.active == VERSION and info.enabled is False
        assert runtime.host.state(OWNER) == "disabled"
        assert runtime.host.enabled(OWNER) is False
        assert runtime.mounts.runtimes == {}  # 停用态：Runtime 根本没被构造
        assert runtime.menu_owners() == ()
    finally:
        runtime.close()


def test_enabling_mounts_the_contribution_and_the_command_runs(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        assert runtime.menu_owners() == (OWNER,)
        handle = runtime.host.menu(OWNER, runtime.scope, "hello")
        assert handle is not None and handle.active
        handle.invoke()
        data_root = Path(tmp_path) / "dsh-pet-standalone" / "feature-data" / OWNER
        assert json.loads((data_root / "memory.json").read_text(encoding="utf-8"))["greetings"] == 1
    finally:
        runtime.close()


def test_disabling_revokes_the_menu_and_old_handles_stop_executing(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        old = runtime.host.menu(OWNER, runtime.scope, "hello")
        assert old is not None and old.active

        manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and not runtime.host.enabled(OWNER))
        assert old.active is False
        assert runtime.host.menu(OWNER, runtime.scope, "hello") is None
        assert runtime.menu_owners() == ()
        # 停用不删安装副本
        assert manager.service.inspect().active == VERSION
    finally:
        runtime.close()


def test_enable_disable_enable_reuses_the_same_runtime_instance(tmp_path):
    """版本没变就不重造 Runtime（DLC 契约：``start/stop/start``，只有卸载才 close）。"""
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        first = runtime.mounts.runtimes[OWNER]
        manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and not runtime.host.enabled(OWNER))
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        assert runtime.mounts.runtimes[OWNER] is first
    finally:
        runtime.close()


def test_uninstall_keeps_personal_data_and_reinstall_works(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        handle = runtime.host.menu(OWNER, runtime.scope, "hello")
        handle.invoke()
        data_root = Path(tmp_path) / "dsh-pet-standalone" / "feature-data" / OWNER
        assert (data_root / "memory.json").is_file()

        manager.submit("uninstall")
        assert _wait(lambda: not manager.busy)
        assert manager.service.inspect().active is None
        assert runtime.host.state(OWNER) == "absent"
        assert handle.active is False
        # 个人数据保留（卸载只删安装副本）
        assert json.loads((data_root / "memory.json").read_text(encoding="utf-8"))["greetings"] >= 1
        # 版本目录已删
        assert not (manager.service.store.root / "versions" / VERSION).exists()

        package = _built(tmp_path / "again")
        assert manager.submit_local_source(package, auto_apply=True, enabled=False)
        assert _wait(lambda: not manager.busy)
        assert manager.service.inspect().active == VERSION
        assert runtime.host.state(OWNER) == "disabled"
    finally:
        runtime.close()


# ------------------------------------------------------------- 草稿门

def test_an_unsaved_draft_blocks_disable_and_the_state_is_untouched(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        panel = runtime.settings_panel(OWNER)
        assert isinstance(panel, OwnerSettingsPanel)
        assert panel.dirty() is False
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()

        before = manager.service.inspect()
        manager.submit("enable", False, expected_revision=before.revision)
        assert _wait(lambda: not manager.busy)
        assert manager.last_operation.status == "awaiting_confirmation"
        assert manager.last_operation.reason == "unsaved_settings"
        after = manager.service.inspect()
        assert after.enabled is True and after.revision == before.revision
        assert runtime.host.enabled(OWNER) is True
    finally:
        runtime.close()


def test_resolving_the_draft_reopens_the_gate(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        panel = runtime.settings_panel(OWNER)
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()
        assert runtime.lifecycle.drafts(OWNER)

        assert panel.discard_changes() is True
        panel.push_drafts()
        assert runtime.lifecycle.drafts(OWNER) == ()
        manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and not runtime.host.enabled(OWNER))
        assert manager.last_operation.status in ("completed", "idempotent")
    finally:
        runtime.close()


def test_the_host_itself_refuses_to_remove_an_owner_with_a_draft(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        panel = runtime.settings_panel(OWNER)
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()
        assert runtime.startup(OWNER).release() is False  # host.remove 的草稿闸门
        assert runtime.host.state(OWNER) == "enabled"
        assert runtime.host.enabled(OWNER) is True
    finally:
        runtime.close()


# --------------------------------------------------- 设置面板与宿主面

def test_the_settings_panel_is_disposed_when_the_owner_goes_away(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        panel = runtime.settings_panel(OWNER)
        assert runtime.panels[OWNER] is panel
        manager.submit("uninstall")
        assert _wait(lambda: not manager.busy)
        assert runtime.panels.get(OWNER) is None
    finally:
        runtime.close()


def test_the_settings_panel_is_reused_for_the_same_owner(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        first = runtime.settings_panel(OWNER)
        assert runtime.settings_panel(OWNER) is first
        # 别的页面刷新不许把这一份草稿层重建（"切 owner 才 dispose"）
        assert panel_is_alive(first)
    finally:
        runtime.close()


def panel_is_alive(panel) -> bool:
    import shiboken6

    return shiboken6.isValid(panel)


def test_the_settings_role_host_never_constructs_a_runtime(tmp_path):
    """settings 侧只 provide + 按需 settings_factory，永不构造 Runtime、永不启 Worker。"""
    runtime = _runtime(tmp_path, role="settings")
    try:
        manager = _install(runtime, tmp_path)
        assert runtime.mounts is None
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy)
        panel = runtime.settings_panel(OWNER)
        assert isinstance(panel, OwnerSettingsPanel)
        assert runtime.mounts is None  # 依然没有挂载面
        assert runtime.menu_owners() == ()
    finally:
        runtime.close()


def test_extensions_exposes_the_managers_the_mod_center_drives(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        registry = runtime.extensions()
        assert registry == {OWNER: manager}
        for name in ("service", "submit", "submit_local_source", "last_result", "result_ready", "state_changed"):
            assert hasattr(manager, name)
    finally:
        runtime.close()


def test_close_is_idempotent_and_stops_everything(tmp_path):
    runtime = _runtime(tmp_path)
    _install(runtime, tmp_path)
    manager = runtime.managers[OWNER]
    manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
    assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
    mounts = runtime.mounts
    runtime.close()
    runtime.close()
    assert mounts.runtimes == {}
    assert not runtime.host.enabled(OWNER)
    assert runtime.mounts is None


def test_recover_pending_is_replayed_for_a_discovered_owner(tmp_path):
    """启动时按安装状态账本发现 owner：被打断的事务在正常启动里重放（不是半装可用）。"""
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        assert manager.service.inspect().active == VERSION
    finally:
        runtime.close()
    # 换一个进程的等价物：新宿主按 plugins/<owner>/ 的状态账本重新发现并装载
    second = _runtime(tmp_path)
    try:
        assert list(second.extensions()) == [OWNER]
        assert second.host.state(OWNER) == "disabled"
        assert second.managers[OWNER].service.inspect().active == VERSION
    finally:
        second.close()


def test_an_unknown_owner_is_never_provided(tmp_path):
    """没有安装状态账本的 owner 不进宿主（发现判据是账本，不是目录存在与否）。"""
    runtime = _runtime(tmp_path)
    try:
        stray = Path(tmp_path) / "dsh-pet-standalone" / "plugins" / "demo.stray"
        stray.mkdir(parents=True)
        fresh = _runtime(tmp_path)
        assert fresh.extensions() == {}
        assert fresh.host.owners() == ()
        fresh.close()
    finally:
        runtime.close()


def test_a_host_without_managers_is_reported_as_empty_not_as_a_placeholder(tmp_path):
    """宿主面缺位时如实返回空注册表，不给占位管理器（控制器据此不列功能扩展行）。"""
    runtime = _runtime(tmp_path)
    try:
        assert runtime.extensions() == {}
        host = FeatureHost()
        manager = FeatureManagementManager(_config(tmp_path), host, OWNER)
        assert manager.last_result.status == "idempotent"
        assert manager.last_result.reason == "not_installed"
        manager.close()
    finally:
        runtime.close()


def test_settings_panel_needs_a_loaded_binding(tmp_path):
    """没有装载好的绑定时面板不可用（不许在没导入包的情况下假造一个空面板）。"""
    runtime = _runtime(tmp_path)
    try:
        assert runtime.settings_panel(OWNER) is None
    finally:
        runtime.close()


def test_the_panel_container_is_a_widget_the_domain_can_mount(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        panel = runtime.settings_panel(OWNER, parent=QWidget())
        assert isinstance(panel, QWidget)
    finally:
        runtime.close()


def test_submit_refuses_a_second_command_while_one_is_in_flight(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert manager.submit("inspect") is False  # 一次只跑一个
        assert _wait(lambda: not manager.busy)
    finally:
        runtime.close()


def test_an_unknown_command_is_reported_not_swallowed(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        seen = []
        manager.result_ready.connect(seen.append)
        assert manager.submit("no-such-command") is False
        assert [result.reason for result in seen] == ["management_command_invalid"]
    finally:
        runtime.close()


def test_the_host_draft_gate_survives_an_uninstall_and_reinstall(tmp_path):
    """闸门是**常设**登记：卸载重装之后第二次撤回仍然要被草稿挡住。

    回归背景：``FeatureHost.remove`` 一度把 ``_prepare``（before_remove 闸门）一起摘掉，
    而重装不会再走一遍 ``attach``（管理器还在），于是"卸载→重装→带草稿删除"这条路上
    宿主的第二道闸门静默消失——只剩下 GUI 预检与事务层那两道。
    """
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        manager.submit("uninstall")
        assert _wait(lambda: not manager.busy)
        assert manager.service.inspect().active is None

        assert manager.submit_local_source(_built(tmp_path / "again"), auto_apply=True, enabled=False)
        assert _wait(lambda: not manager.busy)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))

        panel = runtime.settings_panel(OWNER)
        panel.component.editor.setText("还没保存的编辑")
        panel.push_drafts()
        assert runtime.startup(OWNER).release() is False  # 第二道闸门仍在
        assert runtime.host.enabled(OWNER) is True
    finally:
        runtime.close()


def test_a_failed_apply_puts_the_old_version_back_in_the_host(tmp_path):
    """两段式的第二段失败时，第一段交还的宿主绑定必须装回来。

    卸载 / 更新 / 回滚是"先把宿主绑定交还、再落盘"的两段式：第一段成功而第二段失败
    （另一个进程在这个窗口里抢到版本租约、预检结论过期、状态读不到等），交还就成了
    净损失——菜单与设置在界面上消失，直到重启才回来。这里只注入事务层的失败结论
    （真机上要第二个进程持有租约才会出现那条 ``version_in_use``，见
    ``tests/test_feature_package_transactions.py``），其余全走生产代码。
    """
    runtime = _runtime(tmp_path)
    try:
        manager = _install(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        assert runtime.menu_owners() == (OWNER,)
        before = manager.service.inspect()

        def failing_apply(plan, **kwargs):
            return manager._result("awaiting_release", reason="version_in_use", plan=plan, blocked_versions=(VERSION,))

        original = manager.service.apply
        manager.service.apply = failing_apply
        try:
            manager.submit("uninstall")
            assert _wait(lambda: not manager.busy)
        finally:
            manager.service.apply = original

        # 用户看到的是失败：版本与安装状态一个都没动
        assert manager.last_operation.status == "awaiting_release"
        assert manager.last_operation.reason == "version_in_use"
        after = manager.service.inspect()
        assert (after.active, after.revision) == (before.active, before.revision)
        # 而宿主里那份绑定已经装回来了：菜单与设置还在，状态仍是启用
        assert runtime.host.state(OWNER) == "enabled"
        assert runtime.host.enabled(OWNER) is True
        assert runtime.menu_owners() == (OWNER,)
        assert runtime.host.menu(OWNER, runtime.scope, "hello") is not None
        assert manager.last_result.status in ("completed", "idempotent")
    finally:
        runtime.close()
