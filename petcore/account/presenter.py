"""余额展示的 Core 门面。

余额请求必须在 UI 线程之外执行，并且按宠物 slot 单飞。Presenter 不依赖
Qt，窗口层只需要提供结果回调和一个可选的 GUI dispatch 函数。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable

from ..performance import runtime_metrics
from .service import AccountError, AccountService, BalanceResult


class BalancePresenter:
    def __init__(
        self,
        account: AccountService,
        *,
        service_id_provider: Callable[[int], str | None] | None = None,
        on_result: Callable[[int, BalanceResult | None, Exception | None], None] | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.account = account
        self.service_id_provider = service_id_provider or (lambda _slot: None)
        self.on_result = on_result
        self.dispatch = dispatch or (lambda callback: callback())
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="petcore-balance")
        self._owns_executor = executor is None
        self._lock = Lock()
        self._inflight: dict[int, Future] = {}
        self._generation: dict[int, int] = {}
        self._cache: dict[int, BalanceResult] = {}
        self._closed = False

    def cached(self, slot: int) -> BalanceResult | None:
        slot = int(slot)
        with self._lock:
            result = self._cache.get(slot)
        if result is not None:
            runtime_metrics.inc("cache_hits")
            return result
        runtime_metrics.inc("cache_misses")
        return None

    def request(self, slot: int, *, force: bool = False) -> None:
        slot = int(slot)
        cached = self.cached(slot)
        if cached is not None and not force:
            self._emit(slot, cached, None)
            return
        if cached is not None:
            self._emit(slot, cached, None)
        missing_service = False
        with self._lock:
            if self._closed or slot in self._inflight:
                return
            generation = self._generation.get(slot, 0)
            try:
                service_id = self.service_id_provider(slot)
            except Exception:
                service_id = None
            if not service_id:
                missing_service = True
            else:
                runtime_metrics.inc("network_requests")
                future = self._executor.submit(self._fetch, str(service_id))
                self._inflight[slot] = future
                runtime_metrics.set_active_threads(len(self._inflight))
        if missing_service:
            self._emit(slot, None, AccountError("protocol", "没有配置余额服务"))
            return
        future.add_done_callback(lambda done: self._done(slot, generation, done))

    def cancel(self, slot: int | None = None) -> None:
        slots = [int(slot)] if slot is not None else None
        dropped: list[Future] = []
        with self._lock:
            targets = slots or list(self._inflight)
            for key in targets:
                self._generation[key] = self._generation.get(key, 0) + 1
                future = self._inflight.pop(key, None)
                if future is not None:
                    dropped.append(future)
            runtime_metrics.set_active_threads(len(self._inflight))
        # ``Future.cancel()`` 对 PENDING 任务会在**调用线程里同步**跑 done_callback
        # （进 ``_done`` 再抢同一把非重入锁）。必须在锁外取消，否则退出路径会挂死。
        for future in dropped:
            future.cancel()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.cancel()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _fetch(self, service_id: str) -> BalanceResult:
        return self.account.fetch_balance(service_id, force=True)

    def _done(self, slot: int, generation: int, future: Future) -> None:
        with self._lock:
            current = self._generation.get(slot, 0)
            # 只摘自己那一条：取消后立刻重发的请求已经占了这个槽位，
            # 无条件 pop 会把新任务的在途记录删掉（从而允许第三个并发）。
            if self._inflight.get(slot) is future:
                self._inflight.pop(slot, None)
            runtime_metrics.set_active_threads(len(self._inflight))
            if self._closed or current != generation:
                return
        try:
            result = future.result()
            with self._lock:
                self._cache[slot] = result
            self._emit(slot, result, None)
        except Exception as exc:  # noqa: BLE001 - stable UI error boundary
            self._emit(slot, None, exc if isinstance(exc, Exception) else RuntimeError("balance failed"))

    def _emit(self, slot: int, result: BalanceResult | None, error: Exception | None) -> None:
        callback = self.on_result
        if callback is None:
            return
        try:
            self.dispatch(lambda: callback(slot, result, error))
        except Exception:
            # A destroyed UI dispatcher must never make the worker noisy.
            return


__all__ = ["BalancePresenter"]
