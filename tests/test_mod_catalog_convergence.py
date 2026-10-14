# -*- coding: utf-8 -*-
"""M1 回归：独立设置进程改 MOD 状态后，主进程的功能扩展宿主必须收敛。

实证过的缺陷：设置页跑在独立进程（默认开），那边启停/导入 MOD 之后主进程宿主
不知道——UI 显示已停用但 Runtime 还在跑；新装并启用的包要重启主进程才出现。

这里的两条用例都是**两个真实进程**：子进程（``tests/_feature_management_child.py``，
``role="settings"`` 的真宿主）真改账本并落修订令牌；主进程侧是真
``LocalFeatureRuntime(role="core")`` + 真 ``AppShell._install_config_watcher``
目录监视链。时序一律事件同步 + 宽预算，禁止固定 sleep（AGENTS.md CI 纪律）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from pet.config import Config
from pet.feature_management import LocalFeatureRuntime

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mods" / "hello-local"
OWNER = "demo.hello-local"
VERSION = "1.0.0"
LATE_OWNER = "demo.hello-late"

app = QApplication.instance() or QApplication([])


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


def _bare_shell(config: Config) -> AppShell:
    """最小 AppShell 桩（__new__ 绕过完整初始化，只接监视/收敛链路）。"""
    shell = AppShell.__new__(AppShell)
    shell.config = config
    shell._instances = []
    shell._settings_child_active = False
    shell._settings_launch_at = 0.0
    shell._config_watcher = None
    shell._config_reload_timer = None
    shell._settings_watch_timer = None
    shell._last_config_signature = None
    shell.feature_runtime = None
    return shell


def _built(tmp_path: Path) -> Path:
    from scripts.build_mod_example import build_example

    return build_example(EXAMPLE, tmp_path / "built")


def _install_main(runtime: LocalFeatureRuntime, tmp_path: Path):
    """主进程导入示例包（默认停用），把管理器交回。"""
    package = _built(tmp_path)
    owner = runtime.route(package)
    assert owner == OWNER
    manager = runtime.managers[OWNER]
    assert manager.submit_local_source(package, auto_apply=True, enabled=False)
    assert _wait(lambda: not manager.busy), "主进程导入没有收敛"
    return manager


def _run_child(document: dict) -> dict:
    """拉起真实子进程跑一个管理动作；返回它回报的 JSON。"""
    child = subprocess.run(
        [sys.executable, "-m", "tests._feature_management_child"],
        input=json.dumps(document),
        text=True,
        capture_output=True,
        timeout=120,
        cwd=ROOT,
    )
    assert child.returncode == 0, f"子进程失败: {child.stderr}"
    return json.loads(child.stdout)


def test_settings_process_disable_and_enable_converge_the_main_host(tmp_path):
    """子进程停用 → 主进程 Runtime 真停；再启用 → 主进程真起（双向收敛）。"""
    config = Config(base=tmp_path)
    runtime = LocalFeatureRuntime(config, role="core")
    shell = _bare_shell(config)
    shell.feature_runtime = runtime
    try:
        manager = _install_main(runtime, tmp_path)
        manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
        assert _wait(lambda: not manager.busy and runtime.host.enabled(OWNER))
        assert runtime.menu_owners() == (OWNER,)
        shell._install_config_watcher()

        result = _run_child({
            "base": str(tmp_path), "action": "enable", "owner": OWNER, "value": False,
        })
        assert result["status"] in ("completed", "idempotent"), result
        # 注意：host.enabled() 的授权回调查活账本，子进程一停用它就答 False——
        # 那**不是**收敛。收敛的判据是宿主状态机转到 disabled（Runtime 真停）。
        assert _wait(lambda: runtime.host.state(OWNER) == "disabled"), (
            "子进程停用后，主进程宿主状态没有收敛（Runtime 仍在跑）"
        )
        assert not runtime.host.enabled(OWNER)
        assert runtime.menu_owners() == ()

        result = _run_child({
            "base": str(tmp_path), "action": "enable", "owner": OWNER, "value": True,
        })
        assert result["status"] in ("completed", "idempotent"), result
        assert _wait(lambda: runtime.host.state(OWNER) == "enabled"), (
            "子进程重新启用后，主进程宿主状态没有收敛（Runtime 没有起来）"
        )
        assert runtime.host.enabled(OWNER)
        assert runtime.menu_owners() == (OWNER,)
    finally:
        shell._teardown_config_watcher()
        runtime.close()


def test_a_package_installed_enabled_elsewhere_appears_without_restart(tmp_path):
    """子进程新装并启用的包：主进程按账本重新发现 owner 并装载，不用重启。"""
    from tests._feature_import_package import build

    config = Config(base=tmp_path)
    runtime = LocalFeatureRuntime(config, role="core")
    shell = _bare_shell(config)
    shell.feature_runtime = runtime
    try:
        assert runtime.extensions() == {}
        shell._install_config_watcher()
        built, _zip = build(tmp_path / "late", owner=LATE_OWNER)

        result = _run_child({
            "base": str(tmp_path), "action": "install",
            "package": str(built), "enabled": True,
        })
        assert result["status"] in ("completed", "idempotent"), result
        assert result["owner"] == LATE_OWNER

        assert _wait(lambda: LATE_OWNER in runtime.extensions()), (
            "子进程新装的包没有出现在主进程宿主（要重启才出现）"
        )
        assert _wait(lambda: runtime.host.enabled(LATE_OWNER)), (
            "子进程新装并启用的包，主进程没有把它跑起来"
        )
        manager = runtime.managers[LATE_OWNER]
        assert manager.service.inspect().enabled is True
    finally:
        shell._teardown_config_watcher()
        runtime.close()
