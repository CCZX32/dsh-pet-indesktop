"""致谢刷新任务：正常发信号、取消后不再发、退出时统一取消。"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from petcore.community.service import RefreshReport
from petcore.ui.settings.credits_job import CommunityRefreshJob, cancel_all


class ImmediateService:
    def __init__(self) -> None:
        self.calls = 0

    def refresh(self, *, kinds, force, progress):
        self.calls += 1
        if progress:
            progress("ok")
        return RefreshReport(credits_ok=True, fans_ok=True, fan_total=1)


class BlockingService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def refresh(self, *, kinds, force, progress):
        self.started.set()
        self.release.wait(2.0)
        return RefreshReport(credits_ok=True)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_job_emits_done_from_a_worker_thread(app) -> None:
    service = ImmediateService()
    job = CommunityRefreshJob(service)
    spy = QSignalSpy(job.done)

    job.start()
    for _ in range(100):
        app.processEvents()
        time.sleep(0.02)
        if spy.count():
            break

    assert spy.count() == 1
    assert service.calls == 1


def test_cancel_suppresses_done_and_releases_the_thread(app) -> None:
    service = BlockingService()
    job = CommunityRefreshJob(service)
    done = QSignalSpy(job.done)
    failed = QSignalSpy(job.failed)

    job.start()
    assert service.started.wait(1.0) is True

    cancel_all(0.1)
    service.release.set()
    for _ in range(100):
        time.sleep(0.02)
        if not job.is_running():
            break

    assert done.count() == 0
    assert failed.count() == 0
    assert job.is_running() is False
