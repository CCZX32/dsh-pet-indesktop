"""Monitor lifetime regressions: real threads, only OS readers are substituted."""

from __future__ import annotations

import threading

import pytest

from petcore.platform.netmon import NetMonitor, NetRateMeter
from petcore.platform.sysmon import SysMonitor

TIMEOUT = 15.0


class GatedReader:
    """Each OS read waits for an explicit release; cleanup releases every call."""

    def __init__(self, kind):
        self.kind = kind
        self.entered = [threading.Event() for _ in range(12)]
        self.release = [threading.Event() for _ in range(12)]
        self.threads = []
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            index = self.calls
            self.calls += 1
            self.threads.append(threading.current_thread())
        self.entered[index].set()
        if not self.release[index].wait(TIMEOUT):
            raise TimeoutError("test did not release the OS reader")
        if self.kind == "sys":
            return 77.0
        return (1000.0 * index, 500.0 * index)

    def unblock(self):
        for event in self.release:
            event.set()


@pytest.fixture(params=["sys", "net"])
def monitor_case(request):
    reader = GatedReader(request.param)
    if request.param == "sys":
        monitor = SysMonitor(cpu_reader=reader, mem_reader=lambda: 61.0)
    else:
        monitor = NetMonitor(interval=0.5, meter=NetRateMeter(reader=reader))
    yield monitor, reader
    # Cleanup also works against the old implementation which loses its handle.
    monitor.stop()
    reader.unblock()
    for thread in set(reader.threads):
        if thread is not threading.current_thread():
            thread.join(TIMEOUT)
            assert not thread.is_alive()


def test_stop_returns_without_waiting_for_a_blocked_reader(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    returned = threading.Event()

    def stop():
        monitor.stop()
        returned.set()

    caller = threading.Thread(target=stop)
    caller.start()
    try:
        # A one-second UI budget distinguishes the old two-second join. All
        # reader/event synchronization otherwise has a generous 15s budget.
        assert returned.wait(1.0), "stop() waited for the blocked OS reader"
        assert not reader.release[0].is_set()
    finally:
        reader.unblock()
        caller.join(TIMEOUT)
        assert not caller.is_alive()


def test_running_remains_true_until_the_cancelled_worker_exits(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    monitor.stop()
    assert monitor.running(), "a blocked cancelled worker is still alive"
    assert monitor.wait_stopped(0.0) is False
    reader.unblock()
    assert monitor.wait_stopped(TIMEOUT) is True
    assert monitor.running() is False
    monitor.stop()
    assert monitor.wait_stopped(0.0) is True


def test_start_during_stop_does_not_create_a_second_worker(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    worker = reader.threads[0]
    monitor.stop()
    monitor.start()
    monitor.start()
    workers = [thread for thread in threading.enumerate() if thread.name == worker.name]
    assert workers == [worker]
    reader.unblock()
    assert monitor.wait_stopped(TIMEOUT)
    # Deferred start is intentionally caller-driven, not a hidden auto-restart.
    assert not monitor.running()
    monitor.start()
    assert monitor.running()
    monitor.stop()
    assert monitor.wait_stopped(TIMEOUT)


def test_cancelled_read_cannot_publish_a_late_snapshot(monitor_case):
    monitor, reader = monitor_case
    reader.release[0].set()
    reader.release[1].set()
    monitor.poll()
    monitor.poll()
    monitor.start()
    assert reader.entered[2].wait(TIMEOUT)
    previous = monitor.snapshot()
    worker = reader.threads[2]
    monitor.stop()
    reader.unblock()
    worker.join(TIMEOUT)
    assert not worker.is_alive()
    assert monitor.snapshot() == previous


def test_restart_discards_old_meter_baseline_and_snapshot(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    reader.release[0].set()
    assert reader.entered[1].wait(TIMEOUT)
    reader.release[1].set()
    assert reader.entered[2].wait(TIMEOUT)
    previous = monitor.snapshot()
    if reader.kind == "sys":
        assert previous.cpu_percent == 77.0
    else:
        assert previous.down_bps > 0.0
    worker = reader.threads[2]
    monitor.stop()
    reader.release[2].set()
    worker.join(TIMEOUT)
    assert not worker.is_alive()
    monitor.start()
    assert reader.entered[3].wait(TIMEOUT)
    initial = monitor.snapshot()
    if reader.kind == "sys":
        assert initial.cpu_percent is None
        assert initial.mem_percent is None
    else:
        assert initial is None
    reader.release[3].set()
    assert reader.entered[4].wait(TIMEOUT)
    primed = monitor.snapshot()
    if reader.kind == "sys":
        assert primed.cpu_percent is None
        assert primed.mem_percent == 61.0
    else:
        assert primed is None
    reader.release[4].set()
    assert reader.entered[5].wait(TIMEOUT)
    fresh = monitor.snapshot()
    if reader.kind == "sys":
        assert fresh.cpu_percent == 77.0
    else:
        assert fresh.down_bps > 0.0


def test_poll_while_worker_is_sampling_only_returns_cached_data(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    expected = monitor.snapshot()
    result = []
    returned = threading.Event()

    def poll():
        result.append(monitor.poll())
        returned.set()

    caller = threading.Thread(target=poll)
    caller.start()
    try:
        assert returned.wait(1.0), "poll raced the background OS reader"
        assert result == [expected]
        assert reader.calls == 1
    finally:
        reader.unblock()
        caller.join(TIMEOUT)
        assert not caller.is_alive()


def test_poll_still_supports_synchronous_sampling_after_stop(monitor_case):
    monitor, reader = monitor_case
    reader.unblock()
    monitor.stop()
    first = monitor.poll()
    second = monitor.poll()
    if reader.kind == "sys":
        assert first.cpu_percent is None
        assert second.cpu_percent == 77.0
        assert second.mem_percent == 61.0
    else:
        assert first is None
        assert second.down_bps > 0.0
    assert monitor.snapshot() == second
    assert not monitor.running()


def test_start_serializes_reset_with_an_inflight_synchronous_poll(monitor_case):
    monitor, reader = monitor_case
    reader.release[0].set()
    reader.release[1].set()
    monitor.poll()
    monitor.poll()
    result = []
    caller = threading.Thread(target=lambda: result.append(monitor.poll()))
    caller.start()
    try:
        assert reader.entered[2].wait(TIMEOUT)
        monitor.start()
        # The old manual read may finish, but cannot publish into the new run
        # or prime its meter after the new worker has reset it.
        reader.release[2].set()
        caller.join(TIMEOUT)
        assert not caller.is_alive()
        assert reader.entered[3].wait(TIMEOUT)
        if reader.kind == "sys":
            assert result[0].cpu_percent is None
        else:
            assert result[0] is None
        reader.release[3].set()
        assert reader.entered[4].wait(TIMEOUT)
        fresh = monitor.snapshot()
        if reader.kind == "sys":
            assert fresh.cpu_percent is None
            assert fresh.mem_percent == 61.0
        else:
            assert fresh is None
    finally:
        reader.unblock()
        caller.join(TIMEOUT)
        assert not caller.is_alive()


def test_wait_stopped_is_only_a_wait_not_an_implicit_stop(monitor_case):
    monitor, reader = monitor_case
    monitor.start()
    assert reader.entered[0].wait(TIMEOUT)
    assert monitor.wait_stopped(0.0) is False
    reader.release[0].set()
    assert reader.entered[1].wait(TIMEOUT)
    assert monitor.running()
