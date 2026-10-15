# -*- coding: utf-8 -*-
"""官方识屏包·真实子进程：包内 Worker 入口经验签发射 + 租约交接的起停与观察。

不截图、不联网：只跑 ``observe_foreground``（只读前台窗口查询）。worker 是
**真** QProcess 子进程（``worker/entry.py`` → ``DSH_PET_CORE_ROOT`` 自举 →
``pet.workers.screen_entry`` 租约交接 → ``proactive_screen_worker`` 运行时）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import register_screen_presentation
from pet.feature_management import LocalFeatureRuntime
from pet.workers.supervisor import WorkerSupervisor
from tests.screen_package_fakes import OWNER, FakePresentation, MemoryVault, build_package, dispose_qobject

app = QApplication.instance() or QApplication([])

_READY_BUDGET_S = 60.0


def _wait_until(predicate, *, timeout: float = _READY_BUDGET_S):
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(int(timeout * 1000))
    loop.exec()
    poll.stop()
    deadline.stop()
    return bool(predicate())


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    """真事务链装 + 启用（worker_launch_factory 由 bind_verified_feature 注入）。"""
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    register_screen_presentation(lambda: FakePresentation())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    try:
        manager = runtime.attach_official(OWNER)
        built = build_package(tmp_path / "pkg" / "built")
        assert manager.submit("import_disabled", built, auto_apply=True) is True
        assert _wait_until(lambda: not manager.busy)
        assert manager.submit("enable", True, expected_revision=manager.service.inspect().revision) is True
        assert _wait_until(lambda: not manager.busy)
        assert runtime.host.enabled(OWNER) is True
        yield runtime
    finally:
        register_screen_presentation(None)
        runtime.close()


def test_packaged_worker_handshakes_observes_and_stops_over_the_verified_launch(enabled):
    runtime = enabled
    mount = runtime.mounts.runtimes[OWNER]
    adapter = mount.watcher._worker_adapter
    assert adapter is not None and adapter.mode == "auto"

    responses: list = []
    adapter.observation_ready.connect(responses.append)
    failures: list = []
    adapter.failed.connect(failures.append)
    try:
        assert adapter.start({"max_edge": 640, "jpeg_quality": 70, "frame_ttl": 5.0, "platform": os.sys.platform}) is True
        assert _wait_until(lambda: adapter.ready), adapter.diagnostics()
        request_id = adapter.observe_foreground(generation=7)
        assert request_id
        assert _wait_until(lambda: any(e.get("request_id") == request_id for e in responses))
        envelope = next(e for e in responses if e.get("request_id") == request_id)
        assert envelope["operation"] == "observe_foreground"
        assert envelope["status"] == "ok"
        assert envelope["generation"] == 7
        # 窗口载荷是有界字典（hwnd/pid/process/title/rect 白名单裁剪）
        window = envelope["result"].get("window")
        assert window is None or isinstance(window, dict)
        assert failures == []
    finally:
        adapter.stop()
        assert _wait_until(lambda: adapter.state == WorkerSupervisor.STOPPED, timeout=30.0)
        dispose_qobject(mount)
    assert adapter.supervisor.process is None


def test_the_worker_entry_is_fail_closed_without_a_handoff(tmp_path):
    """裸跑包内入口（无交接 token）必须 77 拒跑，绝不裸启截图/视觉运行时。"""
    import subprocess
    import sys

    built = build_package(tmp_path / "pkg" / "built")
    result = subprocess.run(
        [sys.executable, str(built / "worker" / "entry.py")],
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 77
