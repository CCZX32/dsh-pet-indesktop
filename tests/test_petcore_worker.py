from __future__ import annotations

import sys
import textwrap
import threading
from pathlib import Path

from petcore.contracts import worker as protocol
from petcore.platform.worker import WorkerHost


def _worker_code() -> str:
    return textwrap.dedent(
        """
        import sys
        from petcore.contracts import worker

        for line in sys.stdin:
            message = worker.decode(line)
            kind = message.get("type")
            if kind == worker.HELLO:
                print(worker.encode({"type": worker.READY}), flush=True)
            elif kind == worker.CONFIG_PUSH:
                print(worker.encode({"type": worker.EVENT, "config": message.get("config")}), flush=True)
            elif kind == worker.CANCEL:
                print(worker.encode({"type": worker.EVENT, "cancelled": message.get(worker.REQUEST_ID)}), flush=True)
            elif kind == worker.SHUTDOWN:
                break
        """
    )


def _argv() -> list[str]:
    return [sys.executable, "-u", "-c", _worker_code()]


def test_worker_host_handshake_config_cancel_and_shutdown() -> None:
    ready = threading.Event()
    config_seen = threading.Event()
    cancel_seen = threading.Event()
    exited = threading.Event()
    messages: list[dict] = []

    def on_message(message: dict) -> None:
        messages.append(message)
        if message.get("type") == protocol.READY:
            ready.set()
        if message.get("config") == {"pet": 1}:
            config_seen.set()
        if message.get("cancelled") == "req-1":
            cancel_seen.set()

    host = WorkerHost()
    session = host.start(
        "test-worker",
        _argv(),
        env={"PYTHONUTF8": "1"},
        on_message=on_message,
        on_exit=lambda _code: exited.set(),
        heartbeat_timeout=0,
    )

    assert ready.wait(3.0)
    session.push_config({"pet": 1})
    session.cancel("req-1")
    assert config_seen.wait(3.0)
    assert cancel_seen.wait(3.0)
    session.shutdown()
    assert exited.wait(3.0)
    host.shutdown_all()
    assert any(item.get("type") == protocol.READY for item in messages)


def test_worker_host_replaces_existing_owner_and_stops_all() -> None:
    host = WorkerHost()
    first = host.start("same-owner", _argv(), heartbeat_timeout=0)
    second = host.start("same-owner", _argv(), heartbeat_timeout=0)
    assert first is not second
    assert not first.alive
    assert second.alive
    host.shutdown_all()
    assert not second.alive


def test_worker_session_reports_malformed_output(tmp_path: Path) -> None:
    del tmp_path
    errors: list[object] = []
    ready = threading.Event()
    code = textwrap.dedent(
        """
        import sys
        from petcore.contracts import worker
        print("not-json", flush=True)
        for line in sys.stdin:
            if worker.decode(line).get("type") == worker.HELLO:
                print(worker.encode({"type": worker.READY}), flush=True)
            elif worker.decode(line).get("type") == worker.SHUTDOWN:
                break
        """
    )
    host = WorkerHost()
    session = host.start(
        "bad-worker",
        [sys.executable, "-u", "-c", code],
        on_error=errors.append,
        on_message=lambda message: ready.set() if message.get("type") == protocol.READY else None,
        heartbeat_timeout=0,
    )
    assert ready.wait(3.0)
    session.shutdown()
    assert errors


def test_worker_failures_are_reported_to_the_user() -> None:
    """P3 验收：worker 出错/异常退出必须有用户可见反馈。"""
    from petcore.ui.ports import WorkerNoticePort

    class Inner:
        def __init__(self) -> None:
            self.kwargs = None

        def start(self, owner, argv, env=None, **kwargs):
            self.kwargs = dict(kwargs, owner=owner, argv=argv, env=env)
            return "session"

    notices: list[str] = []
    inner = Inner()
    port = WorkerNoticePort(inner, notices.append)
    assert port.start("demo", ["python", "-c", "pass"]) == "session"
    inner.kwargs["on_error"](RuntimeError("boom"))
    inner.kwargs["on_exit"](3)
    inner.kwargs["on_exit"](0)
    assert any("出错" in item for item in notices)
    assert any("异常退出" in item for item in notices)
    assert len(notices) == 2
