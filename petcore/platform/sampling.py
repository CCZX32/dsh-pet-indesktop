"""Small stdlib-only lifecycle shared by the island sampling monitors.

A stopped reader may still be blocked in an OS call. Keep its thread and its
cancellation token until it exits; never wait for that call on the GUI thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Generic, TypeVar

Sample = TypeVar("Sample")


class SamplingLoop(Generic[Sample]):
    """Single reader, cancellation-safe publication, and caller-driven restart.

    ``start`` records the desired state but cannot replace a live, cancelled
    worker. Call it again on the owner's next reconciliation tick. ``stop``
    cancels that intent too. There is deliberately no hidden restart thread.
    """

    def __init__(
        self,
        *,
        name: str,
        interval: float,
        read: Callable[[], Sample | None],
        reset: Callable[[], None] | None,
        empty: Sample,
        logger: logging.Logger,
    ) -> None:
        self._name = name
        self.interval = interval
        self._read = read
        self._reset = reset
        self._empty = empty
        self._logger = logger
        self._latest = empty
        self._lock = threading.Lock()
        self._reading = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._generation = 0
        self._wanted = False

    def start(self) -> None:
        with self._lock:
            self._wanted = True
            if self._thread is not None and self._thread.is_alive():
                return
            self._generation += 1
            self._cancel = threading.Event()
            self._latest = self._empty
            self._thread = threading.Thread(
                target=self._loop,
                args=(self._generation, self._cancel),
                name=self._name,
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Cancel without joining; running() stays true until the worker exits."""
        with self._lock:
            self._wanted = False
            self._generation += 1
            self._cancel.set()

    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def wait_stopped(self, timeout: float = 2.0) -> bool:
        """Bounded non-GUI wait, without requesting stop or consuming start intent."""
        with self._lock:
            thread = self._thread
        if thread is threading.current_thread():
            return False
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
        return not self.running()

    def snapshot(self) -> Sample:
        with self._lock:
            return self._latest

    def poll(self) -> Sample:
        """Sample synchronously only while idle; a busy reader returns its cache."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._latest
            generation = self._generation
        # A synchronous caller must not race another caller or a worker reset.
        if not self._reading.acquire(blocking=False):
            return self.snapshot()
        try:
            self._sample(generation)
        finally:
            self._reading.release()
        return self.snapshot()

    def _current(self, generation: int, cancel: threading.Event | None) -> bool:
        # Caller holds _lock. OS reads and reset never run under this lock.
        return generation == self._generation and (
            cancel is None or (self._wanted and not cancel.is_set())
        )

    def _sample(self, generation: int, cancel: threading.Event | None = None) -> None:
        # Caller holds _reading across the entire meter operation.
        with self._lock:
            if not self._current(generation, cancel):
                return
        sample = self._read()
        with self._lock:
            if sample is not None and self._current(generation, cancel):
                self._latest = sample

    def _loop(self, generation: int, cancel: threading.Event) -> None:
        # Reset on the owning worker, serialized with even an in-flight manual
        # poll. A start/stop call must never reset a meter in the GUI thread.
        with self._reading:
            with self._lock:
                if not self._current(generation, cancel):
                    return
            if self._reset is not None:
                self._reset()
        while not cancel.wait(self.interval):
            try:
                with self._reading:
                    self._sample(generation, cancel)
            except Exception:  # noqa: BLE001 - a failed OS read must not kill sampling
                self._logger.debug("sample poll failed", exc_info=True)
