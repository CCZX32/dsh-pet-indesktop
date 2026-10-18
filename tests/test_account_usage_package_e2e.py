# -*- coding: utf-8 -*-
"""账户用量包端到端：Core 自有入口的安装/启用/停用/卸载/重装（真事务链）。"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_management import LocalFeatureRuntime
from tests.account_usage_fakes import OWNER, MemoryVault, build_package

app = QApplication.instance() or QApplication([])


def _pump(predicate, *, timeout=30.0) -> bool:
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


def test_account_usage_install_enable_disable_uninstall_and_reinstall(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    data = Config(base=tmp_path).dir / "feature-data" / OWNER
    try:
        assert OWNER in set(runtime.official_packages())
        built = build_package(tmp_path / "pkg" / "built")

        manager, accepted = runtime.install_official(OWNER, built)
        assert accepted is True
        _settle(manager)
        info = manager.service.inspect()
        assert info.active == "1.0.0"
        assert info.enabled is False
        assert runtime.host.enabled(OWNER) is False

        assert runtime.set_official_enabled(OWNER, True) is True
        _settle(manager)
        assert runtime.host.enabled(OWNER) is True
        assert OWNER in runtime.menu_owners()

        assert runtime.set_official_enabled(OWNER, False) is True
        _settle(manager)
        assert runtime.host.enabled(OWNER) is False
        assert OWNER not in runtime.menu_owners()

        assert runtime.uninstall_official(OWNER) is True
        _settle(manager)
        assert manager.service.inspect().active is None
        assert OWNER in set(runtime.official_packages())
        # 卸载只删版本目录，个人数据根保留。
        assert data.is_dir()

        manager, accepted = runtime.install_official(OWNER, built, enabled=True)
        assert accepted is True
        _settle(manager)
        assert manager.service.inspect().active == "1.0.0"
        assert runtime.host.enabled(OWNER) is True
    finally:
        runtime.close()
