from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from petcore.ui.ports import QtConfigPort, QtScheduler


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, timeout: float = 5.0) -> bool:
    """事件驱动等待：只靠 processEvents 推进，超时由 deadline 兜底。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    QApplication.processEvents()
    return predicate()


def _pump_for(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.002)


def _schedule_from_thread(action) -> None:
    worker = threading.Thread(target=action)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()


def test_call_later_from_worker_thread_runs_on_gui_thread(app) -> None:
    scheduler = QtScheduler()
    main_thread = QThread.currentThread()
    seen: list[QThread] = []
    fired = threading.Event()

    def callback() -> None:
        seen.append(QThread.currentThread())
        fired.set()

    _schedule_from_thread(lambda: scheduler.call_later(0, callback))
    assert _pump_until(fired.is_set)
    assert seen and seen[0] is main_thread


def test_call_every_repeats_and_cancel_from_worker_thread(app) -> None:
    scheduler = QtScheduler()
    counts: list[int] = []
    reached = threading.Event()
    lock = threading.Lock()

    def callback() -> None:
        with lock:
            counts.append(1)
            if len(counts) >= 3:
                reached.set()

    handles: list[str] = []
    _schedule_from_thread(lambda: handles.append(scheduler.call_every(5, callback)))
    assert _pump_until(reached.is_set)

    _schedule_from_thread(lambda: scheduler.cancel(handles[0]))
    _pump_for(0.05)
    with lock:
        baseline = len(counts)
    _pump_for(0.2)
    with lock:
        assert len(counts) == baseline


def test_callback_exception_does_not_kill_scheduler(app) -> None:
    scheduler = QtScheduler()
    fired = threading.Event()

    def boom() -> None:
        raise RuntimeError("boom")

    scheduler.call_later(0, boom)
    scheduler.call_later(20, fired.set)
    assert _pump_until(fired.is_set)


class _Config:
    def __init__(self, values) -> None:
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class _BrokenConfig:
    def get(self, key, default=None):
        raise RuntimeError(f"broken get({key})")


def test_config_port_reads_value_and_default(app) -> None:
    port = QtConfigPort(_Config({"self_talk_enabled": True}))
    assert port.get("self_talk_enabled") is True
    assert port.get("missing_key", "fallback") == "fallback"
    assert port.get("missing_key") is None


def test_config_port_none_value_falls_back_to_default(app) -> None:
    port = QtConfigPort(_Config({"unset": None}))
    assert port.get("unset", 42) == 42


def test_config_port_swallows_get_errors(app) -> None:
    port = QtConfigPort(_BrokenConfig())
    assert port.get("any_key", "fallback") == "fallback"
