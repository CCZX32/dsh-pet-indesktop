"""市场后台任务的应用级持有与有界退出。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    total: int
    cancelled: int
    finished: int
    timed_out: int


class MarketJobRegistry:
    """持有市场 QThread，避免页面销毁时出现无主线程。"""

    def __init__(self) -> None:
        self._jobs: set[QThread] = set()
        self._lock = threading.RLock()

    def submit(self, job: QThread) -> None:
        with self._lock:
            self._jobs.add(job)
        try:
            job.finished.connect(lambda job=job: self._forget(job))
        except RuntimeError:
            self._forget(job)

    def _forget(self, job: QThread) -> None:
        with self._lock:
            self._jobs.discard(job)

    def _snapshot(self) -> tuple[QThread, ...]:
        with self._lock:
            return tuple(self._jobs)

    def cancel_all(self) -> int:
        jobs = self._snapshot()
        cancelled = 0
        for job in jobs:
            cancel = getattr(job, "cancel", None)
            try:
                if callable(cancel):
                    cancel()
                else:
                    job.requestInterruption()
                cancelled += 1
            except RuntimeError:
                self._forget(job)
        return cancelled

    def shutdown_all(self, timeout_ms: int) -> ShutdownReport:
        timeout_ms = max(0, int(timeout_ms))
        jobs = self._snapshot()
        cancelled = self.cancel_all()
        deadline = time.monotonic() + timeout_ms / 1000.0
        finished = 0
        for job in jobs:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            try:
                if job.wait(remaining):
                    finished += 1
                    self._forget(job)
            except RuntimeError:
                self._forget(job)
                finished += 1
        active = len(self._snapshot())
        return ShutdownReport(
            total=len(jobs),
            cancelled=cancelled,
            finished=finished,
            timed_out=active,
        )

    def active_jobs(self) -> tuple[QThread, ...]:
        return self._snapshot()
