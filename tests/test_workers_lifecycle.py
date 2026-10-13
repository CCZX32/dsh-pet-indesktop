# -*- coding: utf-8 -*-
"""Worker 子进程生命周期（真 QProcess + 真事件循环 + 真子进程）。

蓝本 = DLC 分支的 ``tests/test_workers_lifecycle.py``，按本仓库宿主面重写：
agent-link adapter 的用例不在本片（该 worker 未移植），补上本片真正要证的东西
——**Qt 生命周期隔离**：进程退出/teardown 后不留 QProcess 残骸、不留活动定时器、
不留活着的原生子进程、不留非 daemon 线程。

假 worker 一律是 ``python <临时脚本>``：脚本自带一份**独立实现**的 JSONL 协议
（不 import ``pet.workers.protocol``），这样"两端写出的字节能被对方读懂"才是
真证据，而不是同源实现自证。

时序纪律（AGENTS.md §CI cost discipline）：全部用「有界轮询 + processEvents」
等状态，不用固定 sleep 猜父进程时序（子进程脚本里的等待是另一回事——那是制造
分片/静默的输入，不是对父进程时序的猜测）。预算按 CI 慢 runner 放宽。
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.workers.launch import WorkerLaunch, WorkerLaunchRejected, lease_worker_launch
from pet.workers.supervisor import WorkerSupervisor

app = QApplication.instance() or QApplication([])

_BUDGET_S = 30.0
#: 冷启动 + 握手在被压满的机器上可能远超生产默认 5s，测试显式放宽（测的是协议与
#: 生命周期，不是机器速度；AGENTS.md §CI cost discipline 的宽预算纪律）。
_HANDSHAKE_BUDGET_MS = 30000
_READY_BUDGET_S = 60.0

#: 子进程侧协议自实现（与父进程的 pet.workers.protocol 互不相干）。
_WORKER_PREAMBLE = '''\
import json
import os
import signal
import sys
import time

WORKER_ID = __WORKER_ID__
PID_FILE = __PID_FILE__
CAPABILITIES = __CAPABILITIES__


def write(text):
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def emit(kind, payload=None, request_id=None):
    message = {"protocol": "pet-worker/v1", "worker_id": WORKER_ID, "type": kind,
               "timestamp": "2026-01-01T00:00:00Z", "payload": payload or {}}
    if request_id:
        message["request_id"] = request_id
    write(json.dumps(message, separators=(",", ":")) + "\\n")


def read_command():
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    return json.loads(line)


def record_pid():
    with open(PID_FILE, "w", encoding="ascii") as stream:
        stream.write(str(os.getpid()))


def handshake():
    """hello -> config_push -> ready；返回协商到的 generation。

    子进程认领接班 token 的唯一判据是环境里拿到了它（父进程经
    ``DSH_PET_WORKER_HANDOFF_TOKEN`` 下发）。
    """
    emit("hello", {"pid": os.getpid(), "capabilities": CAPABILITIES,
                   "lease_claimed": bool(os.environ.get("DSH_PET_WORKER_HANDOFF_TOKEN"))})
    command = read_command()
    if command is None or command["type"] != "config_push":
        sys.exit(3)
    generation = command["payload"]["generation"]
    emit("ready", {"generation": generation})
    return generation
'''


def _wait_until(predicate, *, timeout: float = _BUDGET_S, what: str = "") -> bool:
    """轮询状态直到成立（期间照常跑事件循环），超时返回最后判定值。"""
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        result = bool(predicate())
        if result or time.monotonic() >= deadline:
            if what and not result:
                print(f"[workers] 等待超时：{what}", file=sys.stderr)
            return result


def _worker_command(
    tmp_path: Path,
    body: str,
    *,
    worker_id: str = "demo-worker",
    capabilities: tuple[str, ...] = ("demo.read",),
    name: str = "fake_worker",
) -> tuple[str, list[str], Path]:
    pid_file = tmp_path / f"{name}.pid"
    script = tmp_path / f"{name}.py"
    preamble = (
        _WORKER_PREAMBLE.replace("__WORKER_ID__", repr(worker_id))
        .replace("__PID_FILE__", repr(str(pid_file)))
        .replace("__CAPABILITIES__", repr(list(capabilities)))
    )
    script.write_text(preamble + "\n" + textwrap.dedent(body), encoding="utf-8")
    return sys.executable, [str(script)], pid_file


class _Recorder:
    """把 supervisor 的全部出口记下来，断言不依赖内部字段。"""

    def __init__(self, supervisor: WorkerSupervisor) -> None:
        self.states: list[str] = []
        self.messages: list[object] = []
        self.requests: list[object] = []
        self.responses: list[object] = []
        self.failures: list[str] = []
        self.diagnostics: list[tuple[str, dict]] = []
        supervisor.state_changed.connect(self.states.append)
        supervisor.message_received.connect(self.messages.append)
        supervisor.request_received.connect(self.requests.append)
        supervisor.response_received.connect(self.responses.append)
        supervisor.failed.connect(self.failures.append)
        supervisor.diagnostic.connect(lambda stage, payload: self.diagnostics.append((stage, payload)))

    def stages(self) -> list[str]:
        return [stage for stage, _payload in self.diagnostics]

    def stage_payloads(self, stage: str) -> list[dict]:
        return [payload for name, payload in self.diagnostics if name == stage]


def _start_supervisor(
    tmp_path: Path,
    body: str,
    *,
    worker_id: str = "demo-worker",
    capabilities: tuple[str, ...] = ("demo.read",),
    name: str = "fake_worker",
    **supervisor_kwargs,
) -> tuple[WorkerSupervisor, _Recorder, Path]:
    """起一个 supervisor（默认不自动重启）+ 记录器 + 子进程 pid 文件。"""
    program, arguments, pid_file = _worker_command(
        tmp_path, body, worker_id=worker_id, capabilities=capabilities, name=name
    )
    supervisor_kwargs.setdefault("max_restarts", 0)
    # 生产默认 5s 是给冷启动留的余量；测试要在**被压满的机器**上起 Python 子进程
    # （实测 14 个烧核进程下冷启动可越过 5s），显式放宽——这些用例测的是协议与
    # 生命周期，不是"这台机器多快"。要测握手超时本身的用例自行传小值。
    supervisor_kwargs.setdefault("handshake_timeout_ms", _HANDSHAKE_BUDGET_MS)
    supervisor = WorkerSupervisor(worker_id, program=program, arguments=arguments, **supervisor_kwargs)
    recorder = _Recorder(supervisor)
    return supervisor, recorder, pid_file


def _wait_ready(supervisor: WorkerSupervisor, recorder: _Recorder) -> None:
    """等 READY；超时就把状态/失败原因打出来（不许静默超时）。"""
    if _wait_until(lambda: supervisor.state == supervisor.READY, timeout=_READY_BUDGET_S, what="READY"):
        return
    raise AssertionError(
        f"worker 未在 {_READY_BUDGET_S:.0f}s 内 READY：state={supervisor.state} "
        f"failures={recorder.failures} diagnostics={recorder.diagnostics[-6:]}"
    )


def _stop_supervisor(supervisor: WorkerSupervisor, recorder: _Recorder | None = None) -> None:
    supervisor.stop()
    if _wait_until(lambda: supervisor.state == supervisor.STOPPED, what="supervisor STOPPED"):
        return
    detail = "" if recorder is None else f" failures={recorder.failures} diagnostics={recorder.diagnostics[-6:]}"
    raise AssertionError(f"收口后仍未 STOPPED：state={supervisor.state} process={supervisor.process}{detail}")


def _pid_alive(pid: int) -> bool:
    """跨平台存活探针（Windows 用 tasklist，POSIX 用 signal 0）。"""
    if os.name == "nt":
        import subprocess

        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return any(str(pid) in line for line in probe.stdout.splitlines())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _assert_pid_gone(pid: int, what: str) -> None:
    assert _wait_until(lambda: not _pid_alive(pid), timeout=15.0, what=what), f"{what}: 原生子进程 {pid} 仍在运行"


def _active_timers(supervisor: WorkerSupervisor) -> list[str]:
    names = []
    for attribute in ("_io_timer", "_handshake_timer", "_heartbeat_timer", "_restart_timer", "_shutdown_timer", "_terminate_timer"):
        timer = getattr(supervisor, attribute, None)
        if timer is not None and timer.isActive():
            names.append(attribute)
    return names


@pytest.fixture(autouse=True)
def _drain_live_supervisors():
    """每个用例后收口本模块起过的 supervisor。

    生产关闭是异步的；测试需要一个有界收口点，否则某个用例留下的 worker 会
    活到下一个用例里抢 Qt/进程资源（真机全量套件上这类残留会变成随机红）。
    """
    yield
    WorkerSupervisor._shutdown_live_for_tests()


# ---------------------------------------------------------------- 命令与启动门

def test_supervisor_refuses_an_implicit_command():
    """没有隐式命令行：DLC 的 `-m pet --worker <id>` 默认值在本拓扑不存在，
    照搬会让子进程把主程序（托盘/窗口/桌宠）当 worker 拉起来。"""
    with pytest.raises(ValueError, match="worker command required"):
        WorkerSupervisor("demo-worker")

    supervisor = WorkerSupervisor("demo-worker", program=sys.executable, arguments=["-c", "pass"])
    assert supervisor.program == sys.executable
    assert supervisor.arguments == ["-c", "pass"]


def test_launch_boundary_rejections_abort_the_lease(tmp_path: Path):
    """启动租约面的边界校验：越界的 runtime 一律拒绝，且不留下没释放的租约。"""

    class _Lease:
        def __init__(self) -> None:
            self.released = 0
            self.aborted = 0
            self.confirmed: list[int | None] = []

        def release(self) -> None:
            self.released += 1

        def confirm_child(self, child_pid: int | None) -> bool:
            self.confirmed.append(child_pid)
            return True

        def abort(self) -> None:
            self.aborted += 1

    core_root = tmp_path / "core"
    (core_root / "runtime").mkdir(parents=True)

    with pytest.raises(WorkerLaunchRejected) as relative:
        lease_worker_launch(sys.executable, ["-c", "pass"], runtime_directory=Path("relative"))
    assert relative.value.code == "worker_runtime_boundary"

    with pytest.raises(WorkerLaunchRejected) as missing:
        lease_worker_launch(sys.executable, ["-c", "pass"], runtime_directory=tmp_path / "absent")
    assert missing.value.code == "worker_runtime_unavailable"

    with pytest.raises(WorkerLaunchRejected) as inside_core:
        lease_worker_launch(
            sys.executable,
            ["-c", "pass"],
            runtime_directory=core_root / "runtime",
            core_roots=[core_root],
        )
    assert inside_core.value.code == "worker_runtime_boundary"

    # 同一个 Core 根下的宿主自有运行区可以放行（DLC 的 owned area 语义）。
    launch = lease_worker_launch(
        sys.executable,
        ["-c", "pass"],
        runtime_directory=core_root / "runtime",
        core_roots=[core_root],
        owned_root=core_root / "runtime",
    )
    assert Path(launch.working_directory) == (core_root / "runtime").resolve()

    # 校验失败发生在租约包装之前：这里显式验一遍 abort 语义。
    lease = _Lease()
    with pytest.raises(WorkerLaunchRejected):
        lease_worker_launch(
            sys.executable,
            ["-c", "pass"],
            runtime_directory=core_root / "runtime",
            core_roots=[core_root],
            lease=lease,
        )
    assert lease.aborted == 1
    assert lease.released == 0


def test_rejected_launch_factory_faults_with_a_fixed_code(tmp_path: Path):
    """启动被拒 → 固定错误码诊断 + FAULT，且不暴露路径/token。"""

    def acquire():
        raise WorkerLaunchRejected("worker_runtime_boundary")

    supervisor = WorkerSupervisor("demo-worker", launch_factory=acquire, max_restarts=0)
    recorder = _Recorder(supervisor)

    assert supervisor.start() is False
    assert supervisor.state == supervisor.FAULT
    assert recorder.failures == ["worker launch rejected"]
    rejected = recorder.stage_payloads("launch_rejected")
    assert rejected and rejected[0]["code"] == "worker_runtime_boundary"
    assert str(tmp_path) not in str(rejected[0])


# ---------------------------------------------------------------- 正常生命周期

def test_handshake_ready_event_and_graceful_shutdown(tmp_path: Path):
    """hello → config_push → ready → event → shutdown：全链路 + 收口无残留。"""
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        generation = handshake()
        emit("event", {"generation": generation, "note": "started"})
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )

    assert supervisor.start({"greeting": "hi"})
    _wait_ready(supervisor, recorder)
    assert supervisor.generation == 1
    assert recorder.stages().count("failure") == 0

    assert _wait_until(lambda: any(message.type == "event" for message in recorder.messages), what="first event")
    event = next(message for message in recorder.messages if message.type == "event")
    assert event.payload["generation"] == supervisor.generation
    assert event.payload["note"] == "started"

    pid = int(pid_file.read_text(encoding="ascii"))
    process = supervisor.process
    assert process is not None and process.processId() == pid

    _stop_supervisor(supervisor)

    assert supervisor.state == supervisor.STOPPED
    assert supervisor.process is None
    assert _active_timers(supervisor) == []
    _assert_pid_gone(pid, "graceful shutdown 后")


def test_request_and_response_flow_in_both_directions(tmp_path: Path):
    """父发 request / 子答 response，以及子发 request / 父答 response。"""
    supervisor, recorder, _pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        generation = handshake()
        emit("request", {"operation": "budget_check", "generation": generation}, request_id="worker-req-1")
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
            if command["type"] == "request":
                emit("response", {"operation": command["payload"]["operation"], "generation": generation},
                     request_id=command["request_id"])
            elif command["type"] == "response":
                emit("event", {"generation": generation, "note": "reply-seen", "seen": command["payload"]["operation"]})
        """,
    )

    assert supervisor.start()
    _wait_ready(supervisor, recorder)

    request_id = supervisor.send_request("observe_foreground", {"limit": 3})
    assert request_id
    assert _wait_until(
        lambda: any(message.request_id == request_id for message in recorder.responses),
        what="child response",
    )
    response = next(message for message in recorder.responses if message.request_id == request_id)
    assert response.payload["operation"] == "observe_foreground"

    assert _wait_until(lambda: bool(recorder.requests), what="worker-originated request")
    worker_request = recorder.requests[0]
    assert worker_request.payload["operation"] == "budget_check"
    assert supervisor.send_response(worker_request.request_id, "budget_check", {"granted": True}) is True
    assert _wait_until(
        lambda: any(message.payload.get("seen") == "budget_check" for message in recorder.messages),
        what="worker saw the reply",
    )

    _stop_supervisor(supervisor)


def test_capability_mismatch_fails_the_worker(tmp_path: Path):
    program, arguments, _pid_file = _worker_command(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            time.sleep(0.05)
        """,
        capabilities=("demo.read",),
    )
    supervisor = WorkerSupervisor(
        "demo-worker",
        program=program,
        arguments=arguments,
        required_capabilities=("screen.capture",),
        handshake_timeout_ms=_HANDSHAKE_BUDGET_MS,
        max_restarts=0,
    )
    recorder = _Recorder(supervisor)
    try:
        assert supervisor.start()
        assert _wait_until(lambda: "worker capability mismatch" in recorder.failures, what="capability failure")
        assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FAULT after capability failure")
    finally:
        _stop_supervisor(supervisor)


def test_start_is_refused_while_a_generation_is_live(tmp_path: Path):
    supervisor, recorder, _pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    try:
        assert supervisor.start() is True
        _wait_ready(supervisor, recorder)
        assert supervisor.start() is False
        assert supervisor.generation == 1
    finally:
        _stop_supervisor(supervisor)


# ---------------------------------------------------------------- 失败与重启

def test_handshake_timeout_when_the_child_never_speaks(tmp_path: Path):
    supervisor, recorder, _pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        while True:
            time.sleep(0.05)
        """,
        handshake_timeout_ms=400,
    )
    try:
        assert supervisor.start()
        assert _wait_until(lambda: "handshake timeout" in recorder.failures, what="handshake timeout")
        assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FAULT after handshake timeout")
        assert "failure" in recorder.stages()
        # 被 terminate 收口的子进程要如实记成 CrashExit（三端同义：POSIX 死信号 /
        # Windows TerminateProcess），不能和"自己正常退出"混为一谈——排障时靠这一个
        # 字段区分"worker 崩了"与"worker 正常结束"。
        crashed = recorder.stage_payloads("crashed")
        assert crashed and crashed[0]["exit_status"] == "ExitStatus.CrashExit", crashed
    finally:
        _stop_supervisor(supervisor, recorder)


def test_crash_restarts_then_enters_fault(tmp_path: Path):
    supervisor = WorkerSupervisor(
        "demo-worker",
        program=sys.executable,
        arguments=["-c", "import sys; sys.exit(7)"],
        handshake_timeout_ms=_HANDSHAKE_BUDGET_MS,
        max_restarts=1,
        restart_backoff_s=(0.0,),
    )
    recorder = _Recorder(supervisor)
    try:
        assert supervisor.start()
        assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FAULT after restart budget")
        assert "restart_scheduled" in recorder.stages()
        assert "fault" in recorder.stages()
        crashed = recorder.stage_payloads("crashed")
        assert crashed and crashed[0]["exit_code"] == 7
        assert supervisor.generation == 2
    finally:
        _stop_supervisor(supervisor)


@pytest.mark.skipif(os.name == "nt", reason="Windows 上 terminate() 即强杀，无法构造忽略 SIGTERM 的子进程")
def test_terminate_escalates_to_kill_for_a_child_that_ignores_signals(tmp_path: Path):
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        record_pid()
        handshake()
        while True:
            time.sleep(0.05)
        """,
        shutdown_timeout_ms=300,
    )
    try:
        assert supervisor.start()
        _wait_ready(supervisor, recorder)
        pid = int(pid_file.read_text(encoding="ascii"))
        _stop_supervisor(supervisor)
        assert "shutdown_timeout" in recorder.stages()
        assert "kill_timeout" in recorder.stages()
        _assert_pid_gone(pid, "kill 升级后")
    finally:
        _stop_supervisor(supervisor)


def test_stop_escalates_past_graceful_shutdown(tmp_path: Path):
    """子进程拿到 shutdown 也不退 ⇒ 诊断如实 + 最终收口（三端共同的兜底路径）。"""
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            time.sleep(0.05)
        """,
        shutdown_timeout_ms=300,
    )
    try:
        assert supervisor.start()
        _wait_ready(supervisor, recorder)
        pid = int(pid_file.read_text(encoding="ascii"))
        _stop_supervisor(supervisor)
        assert "shutdown_timeout" in recorder.stages()
        assert supervisor.state == supervisor.STOPPED
        assert supervisor.process is None
        _assert_pid_gone(pid, "terminate 兜底后")
    finally:
        _stop_supervisor(supervisor)


def test_worker_without_heartbeat_is_faulted(tmp_path: Path):
    """READY 之后不再发心跳 ⇒ heartbeat timeout（与握手超时分开计）。"""
    supervisor, recorder, _pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            time.sleep(0.05)
        """,
    )
    supervisor.heartbeat_interval_ms = 250
    supervisor.heartbeat_timeout_ms = 300
    try:
        assert supervisor.start()
        _wait_ready(supervisor, recorder)
        assert _wait_until(lambda: "heartbeat timeout" in recorder.failures, what="heartbeat timeout")
        assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FAULT after heartbeat timeout")
        assert any(payload.get("reason") == "heartbeat timeout" for payload in recorder.stage_payloads("failure"))
    finally:
        _stop_supervisor(supervisor)


def test_failed_to_start_is_reported_without_a_native_process(tmp_path: Path):
    supervisor = WorkerSupervisor(
        "demo-worker",
        program=str(tmp_path / "definitely-absent-interpreter"),
        arguments=["-c", "pass"],
        max_restarts=0,
    )
    recorder = _Recorder(supervisor)

    assert supervisor.start()
    assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FailedToStart → FAULT")
    assert "process_error" in recorder.stages()
    assert supervisor.process is None
    assert _active_timers(supervisor) == []


# ---------------------------------------------------------------- 启动租约

def test_launch_factory_lease_is_held_to_native_exit(tmp_path: Path):
    """租约只在原生子进程退出后释放；握手里的 handoff 由父进程确认。"""
    program, arguments, _pid_file = _worker_command(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    events: list[str] = []

    class _Lease:
        def release(self) -> None:
            events.append("release")

        def confirm_child(self, child_pid: int | None) -> bool:
            events.append(f"confirm:{child_pid is not None}")
            return True

        def abort(self) -> None:
            events.append("abort")

    lease = _Lease()
    generations: list[int] = []

    def acquire() -> WorkerLaunch:
        generations.append(len(generations) + 1)
        return lease_worker_launch(program, arguments, runtime_directory=runtime, environment=dict(os.environ), lease=lease, handoff_token="tok-1")

    supervisor = WorkerSupervisor(
        "demo-worker",
        launch_factory=acquire,
        handshake_timeout_ms=_HANDSHAKE_BUDGET_MS,
        max_restarts=0,
    )
    recorder = _Recorder(supervisor)
    try:
        assert supervisor.start()
        assert _wait_until(lambda: supervisor.state == supervisor.READY, what="READY with handoff")
        assert events == ["confirm:True"], events
        assert recorder.stages().count("failure") == 0
        assert generations == [1]

        _stop_supervisor(supervisor)
        assert events == ["confirm:True", "release"], events
    finally:
        _stop_supervisor(supervisor)


def test_unclaimed_handoff_is_refused_and_the_lease_is_aborted(tmp_path: Path):
    """子进程没在 hello 里认领 token ⇒ 拒绝接班，租约不得被确认接班。"""
    program, arguments, _pid_file = _worker_command(
        tmp_path,
        """
        record_pid()
        emit("hello", {"pid": os.getpid(), "capabilities": CAPABILITIES})
        while True:
            time.sleep(0.05)
        """,
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    events: list[str] = []

    class _Lease:
        def release(self) -> None:
            events.append("release")

        def confirm_child(self, child_pid: int | None) -> bool:
            events.append("confirm")
            return True

        def abort(self) -> None:
            events.append("abort")

    lease = _Lease()
    supervisor = WorkerSupervisor(
        "demo-worker",
        launch_factory=lambda: lease_worker_launch(program, arguments, runtime_directory=runtime, lease=lease, handoff_token="tok-1"),
        handshake_timeout_ms=_HANDSHAKE_BUDGET_MS,
        max_restarts=0,
    )
    recorder = _Recorder(supervisor)
    try:
        assert supervisor.start()
        assert _wait_until(lambda: "worker lease takeover not confirmed" in recorder.failures, what="handoff refusal")
        assert "confirm" not in events
        _stop_supervisor(supervisor)
        # 拒绝接班后租约必须被丢掉：abort（接班未成）与 release（资源交还）
        # 是两件事，DLC 的 close() 同样两者都调。
        assert "abort" in events, events
    finally:
        _stop_supervisor(supervisor)


# ---------------------------------------------------------------- Qt 生命周期隔离

def test_teardown_leaves_no_process_timer_or_thread_residue(tmp_path: Path):
    """三个 worker 同时活着 → 一次收口：无 QProcess、无活动定时器、无活子进程。

    线程口径：本框架在**父进程**里不建线程（读线程在子进程内），所以断言的是
    「收口后没有新增非 daemon 线程」——那是真正会卡住解释器退出的残留。
    """
    baseline = {thread.ident for thread in threading.enumerate() if not thread.daemon}
    supervisors = []
    pids = []
    for index in range(3):
        supervisor, recorder, pid_file = _start_supervisor(
            tmp_path,
            """
            record_pid()
            handshake()
            while True:
                command = read_command()
                if command is None or command["type"] == "shutdown":
                    break
            """,
            name=f"fake_worker_{index}",
        )
        supervisors.append(supervisor)
        assert supervisor.start()
        _wait_ready(supervisor, recorder)
        pids.append(int(pid_file.read_text(encoding="ascii")))

    for pid in pids:
        assert _pid_alive(pid)

    WorkerSupervisor._shutdown_live_for_tests()

    for supervisor in supervisors:
        assert supervisor.state == supervisor.STOPPED
        assert supervisor.process is None
        assert _active_timers(supervisor) == []
    for pid in pids:
        _assert_pid_gone(pid, "teardown 后")

    assert _wait_until(
        lambda: not ({thread.ident for thread in threading.enumerate() if not thread.daemon} - baseline),
        timeout=10.0,
        what="no new non-daemon thread",
    )


def test_bounded_drain_persists_the_stop_to_a_slow_worker(tmp_path: Path):
    """收口钩子对慢性子 worker 也必须**等地到停**，不能只发信号就走。

    ``WorkerSupervisor._shutdown_live_for_tests`` 是测试收口点；生产路径用
    ``finish_app_shutdown``（同一个 drained 判据）。这里断言钩子返回时进程真的
    已经不在，避免"信号发了就算收口"的假收口。
    """
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        time.sleep(0.5)
        """,
    )
    assert supervisor.start()
    _wait_ready(supervisor, recorder)
    pid = int(pid_file.read_text(encoding="ascii"))

    WorkerSupervisor._shutdown_live_for_tests(timeout_ms=8000)

    assert supervisor.state == supervisor.STOPPED
    assert not _pid_alive(pid), "收口钩子返回后子进程仍活着"


def test_finish_app_shutdown_drains_inside_the_deadline(tmp_path: Path):
    """``finish_app_shutdown`` = 主事件循环之后的收口泵：有界、跑到停。"""
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            command = read_command()
            if command is None or command["type"] == "shutdown":
                break
        """,
    )
    assert supervisor.start()
    _wait_ready(supervisor, recorder)
    pid = int(pid_file.read_text(encoding="ascii"))

    started = time.monotonic()
    assert WorkerSupervisor.finish_app_shutdown(timeout_ms=8000) is True
    elapsed = time.monotonic() - started

    assert elapsed < 8.0
    assert supervisor.state == supervisor.STOPPED
    assert supervisor.process is None
    _assert_pid_gone(pid, "finish_app_shutdown 后")


def test_finish_app_shutdown_kills_a_worker_that_never_exits(tmp_path: Path):
    """超过共享 deadline 的 worker 必须被强杀，且返回 False（如实报告未排空）。"""
    supervisor, recorder, pid_file = _start_supervisor(
        tmp_path,
        """
        record_pid()
        handshake()
        while True:
            time.sleep(0.05)
        """,
        shutdown_timeout_ms=60000,
    )
    assert supervisor.start()
    _wait_ready(supervisor, recorder)
    pid = int(pid_file.read_text(encoding="ascii"))

    assert WorkerSupervisor.finish_app_shutdown(timeout_ms=500) is False

    _assert_pid_gone(pid, "deadline 后强杀")
    _stop_supervisor(supervisor)
    assert supervisor.process is None


def test_stop_is_idempotent_and_releases_a_stopped_process(tmp_path: Path):
    """重复 stop 不复活进程、不留引用（进程自己先退出后的收口路径）。"""
    supervisor = WorkerSupervisor(
        "demo-worker",
        program=sys.executable,
        arguments=["-c", "import sys; sys.exit(0)"],
        max_restarts=0,
    )
    assert supervisor.start()
    assert _wait_until(lambda: supervisor.state == supervisor.FAULT, what="FAULT after clean exit")
    assert supervisor.process is None

    supervisor.stop()
    supervisor.stop()
    assert supervisor.state == supervisor.STOPPED
    assert supervisor.process is None
    assert _active_timers(supervisor) == []


#: 真子进程驱动：不 stop 就销毁 supervisor（应用退出/父对象先死的路径），
#: 把"子进程有没有被带走"和"stderr 有没有被吞掉的 traceback"一起报回来。
_DESTROY_DRIVER = '''\
import os
import subprocess
import sys
import time
from pathlib import Path

root = sys.argv[1]
work = Path(sys.argv[2])
sys.path.insert(0, root)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from pet.workers.supervisor import WorkerSupervisor

app = QApplication.instance() or QApplication([])
pid_file = work / "driver_child.pid"
worker = work / "driver_worker.py"
worker.write_text(
    "import json, os, sys, time\\n"
    "from pathlib import Path\\n"
    f"Path(r'{pid_file}').write_text(str(os.getpid()))\\n"
    "def frame(kind, payload):\\n"
    "    m = {'protocol': 'pet-worker/v1', 'worker_id': 'demo-worker', 'type': kind,\\n"
    "         'timestamp': '2026-01-01T00:00:00Z', 'payload': payload}\\n"
    "    sys.stdout.buffer.write((json.dumps(m, separators=(',', ':')) + chr(10)).encode())\\n"
    "    sys.stdout.buffer.flush()\\n"
    "frame('hello', {'capabilities': ['demo.read']})\\n"
    "sys.stdin.readline()\\n"
    "frame('ready', {'generation': 1})\\n"
    "while True:\\n"
    "    time.sleep(0.05)\\n",
    encoding="utf-8",
)


def alive(pid):
    probe = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
    return any(str(pid) in line for line in probe.stdout.splitlines())


supervisor = WorkerSupervisor("demo-worker", program=sys.executable, arguments=[str(worker)], max_restarts=0)
assert supervisor.start()
deadline = time.monotonic() + 60.0
while supervisor.state != supervisor.READY and time.monotonic() < deadline:
    app.processEvents()
assert supervisor.state == supervisor.READY, supervisor.state
pid = int(pid_file.read_text(encoding="ascii"))
print(f"child={pid}", flush=True)
print(f"started_alive={alive(pid)}", flush=True)

# 不 stop，直接走 Qt 的销毁路径（DeferredDelete 必须显式投递才会被处理）。
import shiboken6  # noqa: E402

supervisor.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
for _ in range(40):
    app.processEvents()
    time.sleep(0.05)
print(f"supervisor_valid={shiboken6.isValid(supervisor)}", flush=True)
del supervisor

for _ in range(200):
    app.processEvents()
    if not alive(pid):
        break
    time.sleep(0.05)
print(f"child_alive_after_destroy={alive(pid)}", flush=True)
'''


def test_destroying_a_running_supervisor_kills_the_child_without_stderr_tracebacks(tmp_path: Path):
    """不 stop 就销毁（父对象先死/应用退出）时：C++ 析构带走子进程，且不留 traceback。

    这条守的是两类真实事故：
    ① 孤儿 worker——supervisor 被删而原生子进程继续跑；
    ② shiboken 吞掉的 RuntimeError（`Internal C++ object (QProcess) already deleted`）
       ——它只进 stderr、不冒泡，日志里看着像玄学（本仓库
       ``tests/test_animation_icon_worker_lifecycle.py`` 记录过同一类事故）。
    在**真子进程**里验：本进程早已导入过 Qt，stderr 断言等于没验。
    """
    driver = tmp_path / "destroy_driver.py"
    driver.write_text(_DESTROY_DRIVER, encoding="utf-8")
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, str(driver), str(project_root), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=200,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    values = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if line.split("=", 1)[0] in {"child", "started_alive", "supervisor_valid", "child_alive_after_destroy"}
    )
    assert int(values["child"]) > 0
    assert values["started_alive"] == "True"
    # supervisor 的 C++ 对象确实被销毁了（否则这条用例什么都没测）
    assert values["supervisor_valid"] == "False"
    assert values["child_alive_after_destroy"] == "False", "supervisor 被销毁后子进程仍在跑（孤儿 worker）"
    assert "Traceback (most recent call last)" not in result.stderr, result.stderr
    assert "RuntimeError" not in result.stderr, result.stderr
