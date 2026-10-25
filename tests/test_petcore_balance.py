from __future__ import annotations

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
