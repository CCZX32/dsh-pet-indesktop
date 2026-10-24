from __future__ import annotations

import json
import sys
import textwrap
import threading

from petcore.platform.worker import WorkerHost


_WORKER = textwrap.dedent(
    """
    import json, sys
    PROTOCOL = "petcore-worker/v1"
    def emit(kind, **extra):
        print(json.dumps({"protocol": PROTOCOL, "type": kind, **extra}), flush=True)
    for raw in sys.stdin:
        message = json.loads(raw)
        kind = message.get("type")
        if kind == "hello":
            emit("ready")
            emit("heartbeat")
        elif kind == "request":
            emit("event", request_id=message.get("request_id"))
        elif kind == "cancel":
            emit("event", cancelled=message.get("request_id"))
        elif kind == "shutdown":
            break
    """
).strip()


_IDLE_WORKER = textwrap.dedent(
    """
    import json, sys, time
    for raw in sys.stdin:
        message = json.loads(raw)
        if message.get("type") == "hello":
            time.sleep(30)
            break
    """
).strip()


def _argv(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_worker_handshake_request_cancel_and_shutdown():
    messages: list[dict] = []
    ready = threading.Event()
    request_seen = threading.Event()
    cancel_seen = threading.Event()

    def on_message(message):
        messages.append(message)
        if message.get("type") == "ready":
            ready.set()
        if message.get("request_id") == "r1":
            request_seen.set()
        if message.get("cancelled") == "r1":
            cancel_seen.set()

    host = WorkerHost()
    session = host.start(
        "test-worker",
        _argv(_WORKER),
        on_message=on_message,
        heartbeat_timeout=2.0,
        ready_timeout=2.0,
    )
    assert session.ready
    assert ready.wait(2.0)
    session.request("r1", {"value": 1})
    assert request_seen.wait(2.0)
    session.cancel("r1")
    assert cancel_seen.wait(2.0)
    host.shutdown_all(timeout=1.0)
    assert host.get("test-worker") is None
    assert any(message.get("type") == "heartbeat" for message in messages)


def test_worker_replacement_rejects_stale_exit_callback():
    stale_exit = threading.Event()
    host = WorkerHost()
    host.start(
        "same-owner",
        _argv(_IDLE_WORKER),
        on_exit=lambda _code: stale_exit.set(),
        heartbeat_timeout=0,
    )
    replacement = host.start(
        "same-owner",
        _argv(_WORKER),
        heartbeat_timeout=0,
        ready_timeout=2.0,
    )
    assert replacement.ready
    assert not stale_exit.wait(0.5)
    host.shutdown_all(timeout=1.0)


def test_worker_heartbeat_timeout_reports_and_stops_process():
    error = threading.Event()
    exited = threading.Event()
    host = WorkerHost()
    host.start(
        "silent-worker",
        _argv(_IDLE_WORKER),
        on_error=lambda _error: error.set(),
        on_exit=lambda _code: exited.set(),
        heartbeat_timeout=0.2,
    )
    assert error.wait(3.0)
    assert exited.wait(3.0)
    assert host.get("silent-worker") is None
