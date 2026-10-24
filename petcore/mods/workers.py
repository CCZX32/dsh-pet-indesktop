"""Process-wide admission for non-overlapping mod background workers.

Ownership outlives a runtime instance: unloading a mod does not make a blocked
worker disappear. Cancellation remains cooperative and belongs to the caller.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

_lock = threading.Lock()
_workers: dict[str, threading.Thread] = {}


def try_start_worker(owner: str, target: Callable[[], None], *, name: str) -> threading.Thread | None:
    """Start at most one live worker for owner; never wait on the calling thread."""
    with _lock:
        for key, worker in tuple(_workers.items()):
            if not worker.is_alive():
                del _workers[key]
        if owner in _workers:
            return None
        worker = threading.Thread(target=target, name=name, daemon=True)
        _workers[owner] = worker
        try:
            worker.start()
        except BaseException:
            del _workers[owner]
            raise
        # Keep the reference until a later admission sees actual thread exit.
        return worker
