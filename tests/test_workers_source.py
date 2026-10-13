# -*- coding: utf-8 -*-
"""worker 输出流作为消息源：分帧、残行、超长行、坏帧、背压（真 QProcess）。

蓝本 = DLC 分支的 ``tests/test_workers_source.py``（有界读取 / 不丢记录 /
背压诊断）。那版测的是 agent-link 的日志 tailer；本仓库不移植该 worker，
本片把同一组保证对准**子进程字节流这一侧**——supervisor 的 `_consume_lines`
是唯一把字节变成消息的地方，跨进程读到的分片时序（Windows 命名管道尤其）正是
它要扛住的东西。

每条用例都跑真子进程、按字节精确写出（分片 / CRLF / 超长 / 坏帧），父进程用
有界轮询等状态；子进程里的等待是用来**制造**分片与静默输入，不是猜父进程时序。
"""
from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.workers.protocol import MAX_MESSAGE_BYTES
from pet.workers.supervisor import WorkerSupervisor

app = QApplication.instance() or QApplication([])

_BUDGET_S = 30.0
#: 冷启动 + 握手在被压满的机器上可能远超生产默认 5s，测试显式放宽（测的是协议，
#: 不是机器速度；AGENTS.md §CI cost discipline 的宽预算纪律）。
_HANDSHAKE_BUDGET_MS = 30000
_READY_BUDGET_S = 60.0
_WORKER_ID = "demo-worker"

_WORKER_PREAMBLE = '''\
import json
import os
import sys
import time

WORKER_ID = __WORKER_ID__


def raw(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def write(text):
    raw(text.encode("utf-8"))


def frame(kind, payload=None, request_id=None, worker_id=None, newline="\\n"):
    message = {"protocol": "pet-worker/v1", "worker_id": worker_id or WORKER_ID, "type": kind,
               "timestamp": "2026-01-01T00:00:00Z", "payload": payload or {}}
    if request_id:
        message["request_id"] = request_id
    text = json.dumps(message, separators=(",", ":")) + newline
    write(text)
    return message


def read_command():
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    return json.loads(line)


def handshake():
    frame("hello", {"capabilities": ["demo.read"]})
    command = read_command()
    if command is None or command["type"] != "config_push":
        sys.exit(3)
    generation = command["payload"]["generation"]
    frame("ready", {"generation": generation})
    return generation
'''


def _wait_until(predicate, *, timeout: float = _BUDGET_S, what: str = "") -> bool:
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        result = bool(predicate())
        if result or time.monotonic() >= deadline:
            if what and not result:
                print(f"[workers] 等待超时：{what}", file=sys.stderr)
            return result


class _Recorder:
    def __init__(self, supervisor: WorkerSupervisor) -> None:
        self.messages: list[object] = []
        self.failures: list[str] = []
        self.diagnostics: list[tuple[str, dict]] = []
        supervisor.message_received.connect(self.messages.append)
        supervisor.failed.connect(self.failures.append)
        supervisor.diagnostic.connect(lambda stage, payload: self.diagnostics.append((stage, payload)))

    def events(self) -> list[object]:
        return [message for message in self.messages if message.type == "event"]

    def reasons(self, stage: str) -> list[str]:
        return [str(payload.get("reason", "")) for name, payload in self.diagnostics if name == stage]

    def lines(self, stage: str) -> list[str]:
        return [str(payload.get("line", "")) for name, payload in self.diagnostics if name == stage]


def _start(tmp_path: Path, body: str, **supervisor_kwargs) -> tuple[WorkerSupervisor, _Recorder]:
    script = tmp_path / "stream_worker.py"
    script.write_text(
        _WORKER_PREAMBLE.replace("__WORKER_ID__", repr(_WORKER_ID)) + "\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    supervisor_kwargs.setdefault("max_restarts", 0)
    # 生产默认 5s 是给冷启动留的余量；测试要在**被压满的机器**上起 Python 子进程
    # （实测 14 个烧核进程下冷启动可越过 5s），所以这里显式放宽——测的是协议与
    # 生命周期，不是"这台机器多快"。
    supervisor_kwargs.setdefault("handshake_timeout_ms", _HANDSHAKE_BUDGET_MS)
    supervisor = WorkerSupervisor(_WORKER_ID, program=sys.executable, arguments=[str(script)], **supervisor_kwargs)
    return supervisor, _Recorder(supervisor)


@pytest.fixture(autouse=True)
def _drain_live_supervisors():
    """每个用例后收口本模块起过的 supervisor（同 lifecycle 文件的口径）。

    用例体里的 ``_stop`` 是正常收口；这条是异常路径的兜底——断言失败/异常从
    ``_run_ready`` 抛出时，谁都没停过那个 worker，它会活到下一个用例里去抢
    Qt/进程资源（真机全量套件上这类残留会变成随机红）。
    """
    yield
    WorkerSupervisor._shutdown_live_for_tests()


def _wait_ready(supervisor: WorkerSupervisor, recorder: _Recorder) -> None:
    if _wait_until(lambda: supervisor.state == supervisor.READY, timeout=_READY_BUDGET_S, what="READY"):
        return
    raise AssertionError(
        f"worker 未在 {_READY_BUDGET_S:.0f}s 内 READY：state={supervisor.state} "
        f"failures={recorder.failures} diagnostics={recorder.diagnostics[-6:]}"
    )


def _run_ready(tmp_path: Path, body: str, **supervisor_kwargs) -> tuple[WorkerSupervisor, _Recorder]:
    supervisor, recorder = _start(tmp_path, body, **supervisor_kwargs)
    assert supervisor.start()
    _wait_ready(supervisor, recorder)
    return supervisor, recorder


def _stop(supervisor: WorkerSupervisor, recorder: _Recorder) -> None:
    supervisor.stop()
    if _wait_until(lambda: supervisor.state == supervisor.STOPPED, what="STOPPED"):
        return
    raise AssertionError(
        f"worker 未在收口后 STOPPED：state={supervisor.state} process={supervisor.process} "
        f"failures={recorder.failures} diagnostics={recorder.diagnostics[-6:]}"
    )


def test_a_frame_split_across_two_writes_is_assembled_exactly_once(tmp_path: Path):
    """半行不能当整帧处理，也不能丢：拼回一帧且只交付一次。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        text = json.dumps({"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": "event",
                           "timestamp": "2026-01-01T00:00:00Z",
                           "payload": {"generation": generation, "note": "split"}}, separators=(",", ":"))
        raw(text[:40].encode("utf-8"))
        time.sleep(0.2)
        raw((text[40:] + "\\n").encode("utf-8"))
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: len(recorder.events()) == 1, what="assembled event")
        assert recorder.reasons("protocol") == []
        assert recorder.reasons("lifecycle") == []
        assert recorder.events()[0].payload["note"] == "split"
    finally:
        _stop(supervisor, recorder)


def test_two_frames_in_one_chunk_are_both_handled_in_order(tmp_path: Path):
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        first = json.dumps({"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": "event",
                            "timestamp": "2026-01-01T00:00:00Z",
                            "payload": {"generation": generation, "note": "first"}}, separators=(",", ":"))
        second = json.dumps({"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": "event",
                             "timestamp": "2026-01-01T00:00:00Z",
                             "payload": {"generation": generation, "note": "second"}}, separators=(",", ":"))
        write(first + "\\n" + second + "\\n")
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: len(recorder.events()) == 2, what="both events")
        assert [event.payload["note"] for event in recorder.events()] == ["first", "second"]
        assert recorder.reasons("protocol") == []
    finally:
        _stop(supervisor, recorder)


def test_crlf_terminated_frames_are_accepted(tmp_path: Path):
    """Windows 文本模式写出的 CRLF 必须等价于 LF（子进程用 print 的现实）。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        frame("event", {"generation": generation, "note": "crlf"}, newline="\\r\\n")
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: len(recorder.events()) == 1, what="CRLF event")
        assert recorder.events()[0].payload["note"] == "crlf"
        assert recorder.reasons("protocol") == []
    finally:
        _stop(supervisor, recorder)


def test_a_frame_above_the_wire_limit_is_refused_and_the_stream_recovers(tmp_path: Path):
    """超长行有界丢弃（不把内存撑爆），且后面的正常帧照常送达。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        f"""
        generation = handshake()
        raw(b"x" * {MAX_MESSAGE_BYTES + 4096})
        time.sleep(0.2)
        write("\\n")
        frame("event", {{"generation": generation, "note": "after-overlong"}})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(
            lambda: any("exceeds" in reason or "overlong" in reason for reason in recorder.reasons("protocol")),
            what="overlong line diagnostic",
        )
        assert _wait_until(
            lambda: any(event.payload.get("note") == "after-overlong" for event in recorder.events()),
            what="stream recovered after the overlong line",
        )
    finally:
        _stop(supervisor, recorder)


def test_malformed_frames_are_diagnosed_and_do_not_stop_the_stream(tmp_path: Path):
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        write("not json\\n")
        write(json.dumps([1, 2, 3]) + "\\n")
        write(json.dumps({"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": "not-a-type",
                          "timestamp": "2026-01-01T00:00:00Z", "payload": {}}) + "\\n")
        write("\\n")
        frame("event", {"generation": generation, "note": "survived"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: len(recorder.reasons("protocol")) >= 3, what="protocol diagnostics")
        reasons = recorder.reasons("protocol")
        assert any("invalid JSON" in reason for reason in reasons)
        assert any("root must be an object" in reason for reason in reasons)
        assert any("unknown message type" in reason for reason in reasons)
        assert _wait_until(
            lambda: any(event.payload.get("note") == "survived" for event in recorder.events()),
            what="valid frame after malformed ones",
        )
    finally:
        _stop(supervisor, recorder)


def test_a_frame_from_another_worker_is_refused_by_routing(tmp_path: Path):
    """worker_id 对不上的帧不许被当成自己的消息交付。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        frame("event", {"generation": generation, "note": "impostor"}, worker_id="other-worker")
        frame("event", {"generation": generation, "note": "legit"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: any(event.payload.get("note") == "legit" for event in recorder.events()), what="legit event")
        assert [event.payload["note"] for event in recorder.events()] == ["legit"]
        assert any("unexpected worker_id" in reason for reason in recorder.reasons("routing"))
    finally:
        _stop(supervisor, recorder)


def test_a_stale_generation_frame_is_dropped(tmp_path: Path):
    """上一代留下的迟到事件必须被丢弃（重启后旧代不能污染新代）。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        frame("event", {"generation": generation + 1, "note": "stale"})
        frame("event", {"generation": generation, "note": "current"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: any(event.payload.get("note") == "current" for event in recorder.events()), what="current event")
        assert [event.payload["note"] for event in recorder.events()] == ["current"]
        payloads = [payload for stage, payload in recorder.diagnostics if stage == "stale_message"]
        assert payloads and payloads[0]["message_generation"] == 2
    finally:
        _stop(supervisor, recorder)


def test_stderr_is_surfaced_as_diagnostics_and_never_parsed_as_messages(tmp_path: Path):
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        sys.stderr.write("worker 抱怨一句\\n")
        sys.stderr.write(json.dumps({"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": "event",
                                     "timestamp": "2026-01-01T00:00:00Z", "payload": {"note": "stderr-frame"}}) + "\\n")
        sys.stderr.flush()
        frame("event", {"generation": generation, "note": "stdout-frame"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: any(event.payload.get("note") == "stdout-frame" for event in recorder.events()), what="stdout event")
        assert _wait_until(lambda: len(recorder.lines("stderr")) >= 2, what="stderr diagnostics")
        assert [event.payload["note"] for event in recorder.events()] == ["stdout-frame"]
        assert any("stderr-frame" in line for line in recorder.lines("stderr"))
    finally:
        _stop(supervisor, recorder)


def test_a_near_limit_payload_survives_the_pipe_intact(tmp_path: Path):
    """接近 64KiB 上限的帧跨管道分片后仍要完整解出（Windows 管道尤其）。"""
    supervisor, recorder = _run_ready(
        tmp_path,
        """
        generation = handshake()
        frame("event", {"generation": generation, "blob": "y" * 60000, "note": "big"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: bool(recorder.events()), what="big event")
        event = recorder.events()[0]
        assert event.payload["note"] == "big"
        assert len(event.payload["blob"]) == 60000
        assert recorder.reasons("protocol") == []
    finally:
        _stop(supervisor, recorder)


def test_a_chatty_worker_is_drained_without_loss_or_duplication(tmp_path: Path):
    """有界读取下的背压口径：记录只许多一轮，不许丢、不许重、顺序不许乱。"""
    total = 400
    supervisor, recorder = _run_ready(
        tmp_path,
        f"""
        generation = handshake()
        for sequence in range({total}):
            frame("event", {{"generation": generation, "sequence": sequence}})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert _wait_until(lambda: len(recorder.events()) >= total, timeout=_BUDGET_S, what=f"{total} events")
        sequences = [event.payload["sequence"] for event in recorder.events()]
        assert sequences == list(range(total))
        assert recorder.reasons("protocol") == []
        assert recorder.reasons("stale_message") == []
        assert recorder.failures == []
    finally:
        _stop(supervisor, recorder)
