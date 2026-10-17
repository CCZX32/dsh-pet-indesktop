# -*- coding: utf-8 -*-
"""官方功能包的 Core 自有安装/启停/卸载入口（真事务链，不启 Worker）。"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_management import LocalFeatureRuntime
from tests.screen_package_fakes import OWNER, MemoryVault, build_package

app = QApplication.instance() or QApplication([])


def _pump(predicate, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    assert predicate()


def test_install_enable_uninstall_through_the_official_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        assert set(runtime.official_packages()) >= {OWNER}

        built = build_package(tmp_path / "pkg" / "built")
        manager, accepted = runtime.install_official(OWNER, built)
        assert accepted
        _pump(lambda: not manager.busy)

        info = manager.service.inspect()
        assert info.active is not None
        assert OWNER not in runtime.official_packages()

        assert runtime.set_official_enabled(OWNER, True)
        _pump(lambda: not manager.busy)
        assert runtime.host.enabled(OWNER) is True

        assert runtime.uninstall_official(OWNER)
        _pump(lambda: not manager.busy)
        assert manager.service.inspect().active is None
        assert OWNER in runtime.official_packages()
    finally:
        runtime.close()


def test_install_official_refuses_without_a_source(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        # No source tree / cache and no build permission: the caller gets a reason.
        monkeypatch.setattr(
            runtime,
            "official_source",
            lambda owner, allow_build=True: __import__(
                "pet.official_package_source", fromlist=["OfficialPackageSource"]
            ).OfficialPackageSource(owner, "absent", reason="没有随包来源"),
        )
        try:
            runtime.install_official(OWNER)
        except ValueError as exc:
            assert "没有随包来源" in str(exc)
        else:  # pragma: no cover - 失败路径必须如实抛
            raise AssertionError("缺少来源时必须拒绝")
    finally:
        runtime.close()
