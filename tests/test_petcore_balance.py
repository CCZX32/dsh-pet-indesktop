from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from threading import Event, Lock

from petcore.account.presenter import BalancePresenter
from petcore.account.service import AccountError, BalanceResult


class _Account:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[str] = []
        self._lock = Lock()

    def fetch_balance(self, service_id: str, *, force: bool = False) -> BalanceResult:
        with self._lock:
            self.calls.append(service_id)
        self.started.set()
        self.release.wait(2)
        return BalanceResult(service_id, "12.34", "2", "10")


def test_balance_presenter_is_single_flight_and_emits_cached_result() -> None:
    account = _Account()
    received: list[tuple[int, object, object]] = []
    done = Event()
    presenter = BalancePresenter(
        account,
        service_id_provider=lambda slot: f"service-{slot}",
        on_result=lambda slot, result, error: (received.append((slot, result, error)), done.set()),
        dispatch=lambda callback: callback(),
    )
    try:
        presenter.request(2, force=True)
        assert account.started.wait(1)
        presenter.request(2, force=True)
        assert account.calls == ["service-2"]
        account.release.set()
        assert done.wait(2)
        assert received[0][0] == 2
        assert received[0][1].format_text() == "余额 ¥12.34（充值 ¥10 / 赠送 ¥2）"
        assert presenter.cached(2) is received[0][1]
        presenter.request(2)
        assert len(received) == 2
    finally:
        presenter.shutdown()


def test_balance_presenter_cancel_rejects_late_result() -> None:
    account = _Account()
    received: list[tuple[int, object, object]] = []
    presenter = BalancePresenter(
        account,
        service_id_provider=lambda _slot: "service",
        on_result=lambda *args: received.append(args),
        dispatch=lambda callback: callback(),
    )
    try:
        presenter.request(0, force=True)
        assert account.started.wait(1)
        presenter.cancel(0)
        account.release.set()
        assert presenter._executor is not None
        presenter._executor.shutdown(wait=True)
        assert received == []
    finally:
        presenter.shutdown()


def test_balance_presenter_reports_missing_service() -> None:
    received: list[tuple[int, object, object]] = []
    presenter = BalancePresenter(
        object(),
        service_id_provider=lambda _slot: None,
        on_result=lambda *args: received.append(args),
        dispatch=lambda callback: callback(),
    )
    try:
        presenter.request(3)
        assert received[0][0] == 3
        assert isinstance(received[0][2], AccountError)
        assert received[0][2].reason == "protocol"
    finally:
        presenter.shutdown()


class _DaemonExecutor:
    """只用 daemon 线程的顺序执行器。

    死锁回归测试不能在失败时把 pytest 退出拖住：``ThreadPoolExecutor`` 的线程
    是非 daemon 的，atexit join 会把整个进程挂死。这里自己排一个 daemon 线程，
    失败只表现为断言失败。
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._queue: list = []
        self._busy = False

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        with self._lock:
            self._queue.append((future, fn, args, kwargs))
            if not self._busy:
                self._busy = True
                threading.Thread(target=self._pump, daemon=True).start()
        return future

    def _pump(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._busy = False
                    return
                future, fn, args, kwargs = self._queue.pop(0)
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # noqa: BLE001 - 原样转交给 Future
                future.set_exception(exc)

    def shutdown(self, wait: bool = False, cancel_futures: bool = False) -> None:
        del wait, cancel_futures


def test_cancel_does_not_deadlock_on_queued_future() -> None:
    """取消排队中的余额请求必须立即返回（Future.cancel 会同步跑 done_callback）。"""
    account = _Account()
    presenter = BalancePresenter(
        account,
        service_id_provider=lambda _slot: "service",
        dispatch=lambda callback: callback(),
        executor=_DaemonExecutor(),
    )
    presenter.request(0, force=True)
    assert account.started.wait(1)
    presenter.request(1, force=True)

    finished = Event()
    worker = threading.Thread(
        target=lambda: (presenter.cancel(), finished.set()), daemon=True
    )
    worker.start()
    try:
        assert finished.wait(3), "cancel() 在 PENDING future 上死锁"
    finally:
        account.release.set()


def test_balance_dispatch_from_worker_thread_reaches_gui_thread() -> None:
    """余额结果由工作线程投递，必须真的落到 GUI 事件循环上（不能是空转）。"""
    from PySide6.QtCore import QCoreApplication

    from petcore.ui.app import gui_dispatch
    from petcore.ui.ports import QtScheduler

    app = QCoreApplication.instance() or QCoreApplication([])
    dispatch = gui_dispatch(QtScheduler())
    received: list[str] = []

    dispatch(lambda: received.append("main"))
    worker = threading.Thread(target=lambda: dispatch(lambda: received.append("worker")))
    worker.start()
    worker.join(2)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(received) < 2:
        app.processEvents()
        time.sleep(0.01)

    assert sorted(received) == ["main", "worker"]

def test_done_only_pops_the_future_it_belongs_to() -> None:
    """取消后立刻重发：旧 future 的 done 回调不许删掉新请求的在途记录（AUD-19）。"""
    presenter = BalancePresenter(
        object(),
        service_id_provider=lambda _slot: None,
        dispatch=lambda callback: callback(),
    )
    old: Future = Future()
    new: Future = Future()
    old.set_result(BalanceResult("service", "1", "1", "0"))
    try:
        presenter._inflight[0] = new  # noqa: SLF001 - 直接摆放"重发后"的状态
        presenter._done(0, presenter._generation.get(0, 0), old)  # noqa: SLF001
        assert presenter._inflight.get(0) is new, "旧任务的完成回调误删了新任务的在途记录"
    finally:
        # 线程池不关掉会留下工作线程，后续 Qt 用例退出时会与本进程抢收尾。
        presenter.shutdown()
