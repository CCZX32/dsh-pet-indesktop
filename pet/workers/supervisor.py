# -*- coding: utf-8 -*-
"""Asynchronous QProcess supervisor for built-in JSONL workers.

Ported from the DLC branch `pet/workers/supervisor.py`.  Host adaptations:

* the launch-rejection path no longer reaches into the DLC's feature-package
  trust chain (`StateError` / `PackageVerificationError`); fixed reason codes now
  come from :class:`pet.workers.launch.WorkerLaunchRejected`;
* S2 期间刻意没有隐式命令行（当时 `-m pet --worker <id>` 这条路由还不存在）。
  S3 落下该路由后恢复 DLC 的默认值，见 :meth:`WorkerSupervisor._resolve_command`。
  握手预算默认值也随真 worker 的启动实测抬到 15s。

This is a GUI-thread object owning a :class:`QProcess`; every native child is
released through :meth:`WorkerSupervisor._release_process` so a stopped process
never survives into a later restart or teardown.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
import weakref
from collections import deque
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QEventLoop, QObject, QProcess, QProcessEnvironment, QTimer, Signal

import shiboken6

from .launch import WorkerLaunch, WorkerLaunchRejected
from .protocol import MAX_MESSAGE_BYTES, WorkerMessage, WorkerProtocolError, build_message, decode_message, encode_message

_LOG = logging.getLogger(__name__)
_LIVE_SUPERVISORS: weakref.WeakSet = weakref.WeakSet()


class WorkerSupervisor(QObject):
    """Own one worker process without blocking the GUI thread.

    The supervisor deliberately accepts a program and argument vector so tests
    can launch a small fake worker.  Production callers supply the current Python
    interpreter or the frozen executable plus that worker's own entry route.
    """

    state_changed = Signal(str)
    message_received = Signal(object)
    request_received = Signal(object)
    response_received = Signal(object)
    ready = Signal()
    failed = Signal(str)
    diagnostic = Signal(str, object)

    DISABLED = "disabled"
    STARTING = "starting"
    HANDSHAKING = "handshaking"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"
    FAULT = "fault"

    def __init__(
        self,
        worker_id: str,
        parent: QObject | None = None,
        *,
        program: str | None = None,
        arguments: Sequence[str] | None = None,
        launch_factory: Callable[[], WorkerLaunch] | None = None,
        required_capabilities: Sequence[str] = (),
        handshake_timeout_ms: int = 15000,
        heartbeat_interval_ms: int = 5000,
        heartbeat_timeout_ms: int = 15000,
        shutdown_timeout_ms: int = 2000,
        max_restarts: int = 3,
        restart_window_s: float = 60.0,
        restart_backoff_s: Sequence[float] = (0.5, 1.0, 2.0),
    ) -> None:
        super().__init__(parent)
        self.worker_id = str(worker_id)
        self.required_capabilities = frozenset(required_capabilities)
        self._launch_factory = launch_factory
        self._launches: dict[QProcess, WorkerLaunch] = {}
        self.program, self.arguments = self._resolve_command(self.worker_id, program, arguments)
        # 握手预算（S3 校准）：S2 沿用 DLC 的 5000 ms。但真 worker（还只是 Python
        # 解释器 + 协议层，冻结版可执行只会更慢）在**满载机器**上冷启动可以越过
        # 5s——S2 加压复跑实测到过这条线。两边一起做：worker 入口把 hello 排在
        # 一切导入/初始化之前尽快发出（见 proactive_screen_worker.run），这里把
        # 默认值抬到 15s。取 15s 的依据：S2 空载冷启动→READY 实测 135 ms，加压
        # 拉伸约 2-3 倍（该片 §五/§四），15s ≈ 空载的 100 倍余量；再高只会让
        # 「worker 真的起不来」这种故障晚 10s 才被发现。
        self.handshake_timeout_ms = max(100, int(handshake_timeout_ms))
        self.heartbeat_interval_ms = max(250, int(heartbeat_interval_ms))
        self.heartbeat_timeout_ms = max(self.heartbeat_interval_ms, int(heartbeat_timeout_ms))
        self.shutdown_timeout_ms = max(100, int(shutdown_timeout_ms))
        self.max_restarts = max(0, int(max_restarts))
        self.restart_window_s = max(1.0, float(restart_window_s))
        self.restart_backoff_s = tuple(max(0.0, float(item)) for item in restart_backoff_s) or (0.0,)

        self._state = self.DISABLED
        self._process: QProcess | None = None
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._config: dict[str, Any] = {}
        self._generation = 0
        self._last_heartbeat = 0.0
        self._restart_times: deque[float] = deque()
        self._restart_timer: QTimer | None = None
        self._shutdown_timer: QTimer | None = None
        self._terminate_timer: QTimer | None = None
        self._io_timer = QTimer(self)
        self._io_timer.setInterval(50)
        self._io_timer.timeout.connect(self._poll_process_io)
        self._handshake_timer = QTimer(self)
        self._handshake_timer.setSingleShot(True)
        self._handshake_timer.timeout.connect(self._on_handshake_timeout)
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(1000)
        self._heartbeat_timer.timeout.connect(self._check_heartbeat)
        self._requested_stop = False
        _LIVE_SUPERVISORS.add(self)

    @staticmethod
    def _resolve_command(worker_id: str, program: str | None, arguments: Sequence[str] | None) -> tuple[str, list[str]]:
        """显式命令行优先；否则用本拓扑的子进程专用入口。

        S2 期间这里刻意**没有**隐式命令行：当时 ``-m pet --worker <id>`` 这条
        路由还不存在，照搬 DLC 的默认值会把整个桌宠（托盘/窗口/桌宠本体）当 worker
        拉起来。S3 落下了这条路由（白名单见 ``pet/workers/worker_entry.py``，
        白名单之外的 id 以退出码 2 拒绝，且分流早于 ``pet.app``），禁令随之解除，
        恢复 DLC 的默认值。
        """
        if program:
            return str(program), list(arguments or ())
        if getattr(sys, "frozen", False):
            return sys.executable, ["--worker", str(worker_id)]
        return sys.executable, ["-m", "pet", "--worker", str(worker_id)]

    @property
    def state(self) -> str:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def process(self) -> QProcess | None:
        return self._process

    def _set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.state_changed.emit(state)

    def _emit_diagnostic(self, stage: str, detail: Any = None) -> None:
        payload = detail if isinstance(detail, dict) else {"detail": str(detail) if detail is not None else ""}
        payload = dict(payload)
        payload.setdefault("worker_id", self.worker_id)
        payload.setdefault("generation", self._generation)
        self.diagnostic.emit(stage, payload)

    def start(self, config: Mapping[str, Any] | None = None) -> bool:
        if self._state in {self.STARTING, self.HANDSHAKING, self.READY, self.STOPPING}:
            return False
        previous = self._process
        if previous is not None:
            if previous.state() != QProcess.ProcessState.NotRunning:
                return False
            self._release_process(previous)
        self._cancel_restart_timer()
        self._requested_stop = False
        self._config = dict(config or {})
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        self._generation += 1
        self._last_heartbeat = time.monotonic()
        launch = None
        try:
            if self._launch_factory is not None:
                # A fresh verified lease for every generation, including retries.
                launch = self._launch_factory()
                if not isinstance(launch, WorkerLaunch):
                    raise TypeError("invalid external Worker launch")
            process = QProcess(self)
            process.setProgram(launch.program if launch else self.program)
            process.setArguments(list(launch.arguments) if launch else self.arguments)
            if launch is not None:
                environment = QProcessEnvironment()
                for key, value in launch.environment.items():
                    environment.insert(key, value)
                process.setProcessEnvironment(environment)
                process.setWorkingDirectory(launch.working_directory)
        except Exception as exc:
            if isinstance(launch, WorkerLaunch):
                launch.close()
            # Fixed codes only: never expose paths, tokens or verifier inputs.
            code = exc.code if isinstance(exc, WorkerLaunchRejected) else "worker_launch_failed"
            self._emit_diagnostic("launch_rejected", {"reason": "worker launch rejected", "code": code})
            # Direct Qt subscribers must see the diagnostic before FAULT.
            self._set_state(self.FAULT)
            self.failed.emit("worker launch rejected")
            return False
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        def connect_current(signal, callback):
            # A queued old-generation signal must not dispatch into a new process.
            # Do not capture bound callbacks/self/child strongly: disposing a
            # DeferredDelete child could then release its parent's last Python
            # reference from inside the child's C++ destructor.
            owner_ref = weakref.ref(self)
            process_ref = weakref.ref(process)
            callback_ref = weakref.WeakMethod(callback)

            def dispatch(*args):
                owner = owner_ref()
                child = process_ref()
                target = callback_ref()
                if owner is None or child is None or target is None:
                    return
                if owner._process is not child:
                    # A queued signal from an old generation (or after release) has
                    # no live target left.
                    return
                # Qt 拆除对象树时会先把子 QProcess/QTimer 的 C++ 对象删掉，之后队列里
                # 残留的信号仍会被投进来——此时跑槽会撞上已删对象并抛 RuntimeError，
                # 而 shiboken 只把它打到 stderr 就吞掉（日志里是"玄学 traceback"）。
                # 这是唯一的兜底闸：`destroyed` 信号在销毁路径上**到不了** Python 槽
                # （实测 deleteLater + DeferredDelete 之后 isValid 已 False，但槽没被调），
                # 所以只能用 C++ 有效性判断。
                if not shiboken6.isValid(owner) or not shiboken6.isValid(child):
                    return
                target(*args)

            signal.connect(dispatch)

        connect_current(process.started, self._on_started)
        connect_current(process.readyReadStandardOutput, self._read_stdout)
        connect_current(process.readyReadStandardError, self._read_stderr)
        connect_current(process.errorOccurred, self._on_process_error)
        connect_current(process.finished, self._on_process_finished)
        self._process = process
        if launch is not None:
            self._launches[process] = launch
        self._set_state(self.STARTING)
        process.start()
        return True

    def configure(self, config: Mapping[str, Any]) -> bool:
        self._config = dict(config)
        if self._state == self.READY:
            return self._send_config()
        return False

    def _on_started(self) -> None:
        if self._process is None:
            return
        self._set_state(self.HANDSHAKING)
        self._handshake_timer.start(self.handshake_timeout_ms)
        # Heartbeats begin at READY, not before potentially slow verification
        # or handshake. The separate handshake timer still bounds startup.
        # QProcess normally emits readyReadStandardOutput, but a polling
        # fallback makes the protocol robust when a long-running Qt test
        # leaves a native notification queued or missed.
        self._io_timer.start()

    def _on_handshake_timeout(self) -> None:
        if self._state in {self.STARTING, self.HANDSHAKING}:
            self._fail_current("handshake timeout")

    def _send(
        self,
        message_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> bool:
        process = self._process
        if process is None or process.state() != QProcess.ProcessState.Running:
            return False
        try:
            data = encode_message(
                build_message(
                    self.worker_id,
                    message_type,
                    dict(payload or {}),
                    request_id=request_id,
                )
            )
            written = process.write(data)
            if written < 0:
                self._emit_diagnostic("write", {"reason": "QProcess.write returned -1"})
                return False
            return True
        except (WorkerProtocolError, OSError, RuntimeError) as exc:
            self._emit_diagnostic("write", {"reason": str(exc)})
            return False

    def _send_config(self) -> bool:
        body = dict(self._config)
        body["generation"] = self._generation
        return self._send("config_push", body)

    def send_request(
        self,
        operation: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        generation: int | None = None,
        request_id: str | None = None,
    ) -> str | None:
        """Send a request to a ready worker and return its request id.

        ``generation`` belongs to the caller's logical task, not the
        supervisor process generation.  It is therefore carried in the
        payload and is intentionally not compared by the generic supervisor.
        """
        operation = str(operation).strip()
        if not operation:
            self._emit_diagnostic("request", {"reason": "operation is empty"})
            return None
        rid = str(request_id or uuid.uuid4().hex)
        body: dict[str, Any] = {
            "operation": operation,
            "arguments": dict(arguments or {}),
        }
        if generation is not None:
            body["generation"] = int(generation)
        if not self._send("request", body, request_id=rid):
            return None
        return rid

    def send_response(
        self,
        request_id: str,
        operation: str,
        payload: Mapping[str, Any] | None = None,
        *,
        generation: int | None = None,
    ) -> bool:
        """Reply to a worker-originated request such as ``budget_check``."""
        rid = str(request_id).strip()
        op = str(operation).strip()
        if not rid or not op:
            self._emit_diagnostic("response", {"reason": "request_id and operation are required"})
            return False
        body: dict[str, Any] = dict(payload or {})
        # ``operation`` is part of the response routing contract.  Do not let
        # a payload field accidentally override the operation supplied by the
        # caller.
        body["operation"] = op
        if generation is not None:
            body.setdefault("generation", int(generation))
        return self._send("response", body, request_id=rid)

    def stop(self) -> None:
        self._requested_stop = True
        self._cancel_restart_timer()
        self._handshake_timer.stop()
        self._heartbeat_timer.stop()
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            if process is not None:
                self._release_process(process)
            self._set_state(self.STOPPED)
            return
        self._set_state(self.STOPPING)
        self._send("shutdown", {"generation": self._generation})
        # Closing the parent write channel delivers EOF after the shutdown
        # frame. The worker uses EOF to release its stdin reader on Windows,
        # where a blocking pipe read cannot be interrupted by an Event alone.
        process.closeWriteChannel()
        if self._shutdown_timer is None:
            self._shutdown_timer = QTimer(self)
            self._shutdown_timer.setSingleShot(True)
            self._shutdown_timer.timeout.connect(self._on_shutdown_timeout)
        self._shutdown_timer.start(self.shutdown_timeout_ms)

    def _on_shutdown_timeout(self) -> None:
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        self._emit_diagnostic("shutdown_timeout", {"reason": "worker did not exit after graceful shutdown"})
        process.terminate()
        if self._terminate_timer is None:
            self._terminate_timer = QTimer(self)
            self._terminate_timer.setSingleShot(True)
            self._terminate_timer.timeout.connect(self._on_terminate_timeout)
        self._terminate_timer.start(500)

    def _on_terminate_timeout(self) -> None:
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            self._emit_diagnostic("kill_timeout", {"reason": "worker did not exit after terminate"})
            process.kill()

    def _poll_process_io(self) -> None:
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        if process.bytesAvailable() > 0:
            self._read_stdout()
        if process.bytesAvailable() > 0:
            self._read_stderr()

    def _read_stdout(self) -> None:
        process = self._process
        if process is None:
            return
        self._stdout_buffer.extend(bytes(process.readAllStandardOutput()))
        self._consume_lines(self._stdout_buffer)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None:
            return
        self._stderr_buffer.extend(bytes(process.readAllStandardError()))
        if len(self._stderr_buffer) > MAX_MESSAGE_BYTES:
            self._stderr_buffer = self._stderr_buffer[-MAX_MESSAGE_BYTES:]
        while b"\n" in self._stderr_buffer:
            line, _, rest = self._stderr_buffer.partition(b"\n")
            self._stderr_buffer = bytearray(rest)
            if line.strip():
                self._emit_diagnostic("stderr", {"line": line.decode("utf-8", errors="replace")[:2000]})

    def _consume_lines(self, buffer: bytearray) -> None:
        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n")
            buffer[:] = rest
            if len(line) > MAX_MESSAGE_BYTES:
                self._emit_diagnostic("protocol", {"reason": "worker line exceeds message limit"})
                continue
            if not line.strip():
                continue
            try:
                message = decode_message(bytes(line))
            except WorkerProtocolError as exc:
                self._emit_diagnostic("protocol", {"reason": str(exc)})
                continue
            self._handle_message(message)
        if len(buffer) > MAX_MESSAGE_BYTES:
            self._emit_diagnostic("protocol", {"reason": "worker output has an overlong unterminated line"})
            buffer.clear()

    def _handle_message(self, message: WorkerMessage) -> None:
        if message.worker_id != self.worker_id:
            self._emit_diagnostic("routing", {"reason": f"unexpected worker_id: {message.worker_id}"})
            return
        payload = message.payload
        generation = payload.get("generation")
        if generation is not None:
            try:
                generation = int(generation)
            except (TypeError, ValueError):
                self._emit_diagnostic("generation", {"reason": "generation is not an integer"})
                return
            if message.type in {"event", "heartbeat", "error", "ready"} and generation != self._generation:
                self._emit_diagnostic("stale_message", {"message_type": message.type, "message_generation": generation})
                return
        if message.type == "hello":
            if self._state not in {self.STARTING, self.HANDSHAKING}:
                self._emit_diagnostic("lifecycle", {"reason": "hello received outside handshake"})
                return
            launch = self._launches.get(self._process) if self._process is not None else None
            if launch is not None and launch.requires_handoff:
                if payload.get("lease_claimed") is not True:
                    self._fail_current("worker lease takeover not confirmed")
                    return
                process_pid = int(self._process.processId()) if self._process is not None and self._process.processId() else None
                if not launch.confirm_handoff(process_pid):
                    self._fail_current("worker lease takeover rejected")
                    return
            capabilities = payload.get("capabilities", [])
            if self.required_capabilities and (
                not isinstance(capabilities, list)
                or not all(isinstance(item, str) for item in capabilities)
                or not self.required_capabilities.issubset(capabilities)
            ):
                self._fail_current("worker capability mismatch")
                return
            self._set_state(self.HANDSHAKING)
            if not self._send_config():
                self._fail_current("failed to send config")
            return
        if message.type == "ready":
            if self._state not in {self.HANDSHAKING, self.READY}:
                self._emit_diagnostic("lifecycle", {"reason": "ready received outside handshake/configuration"})
                return
            self._handshake_timer.stop()
            self._last_heartbeat = time.monotonic()
            self._heartbeat_timer.start()
            self._set_state(self.READY)
            self.ready.emit()
            return
        if message.type == "heartbeat":
            self._last_heartbeat = time.monotonic()
            return
        if message.type == "error":
            self._emit_diagnostic("worker_error", payload)
        if message.type in {"request", "response"} and self._state != self.READY:
            self._emit_diagnostic("lifecycle", {"reason": "RPC received outside ready state"})
            return
        if message.type == "request":
            self.request_received.emit(message)
            return
        if message.type == "response":
            self.response_received.emit(message)
            return
        if message.type in {"event", "error", "heartbeat"}:
            self.message_received.emit(message)
            return
        if message.type == "shutdown":
            return
        self._emit_diagnostic("protocol", {"reason": f"unexpected worker message: {message.type}"})

    def _check_heartbeat(self) -> None:
        if self._state != self.READY:
            return
        if time.monotonic() - self._last_heartbeat > self.heartbeat_timeout_ms / 1000.0:
            self._fail_current("heartbeat timeout")

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        self._emit_diagnostic("process_error", {"error": str(error), "error_string": self._process.errorString() if self._process else ""})
        if self._state in {self.STARTING, self.HANDSHAKING, self.READY}:
            self.failed.emit(self._process.errorString() if self._process else "worker process error")
        if error == QProcess.ProcessError.FailedToStart:
            # Qt does not emit finished() when native process creation fails.
            process = self._process
            self._handshake_timer.stop()
            self._heartbeat_timer.stop()
            self._io_timer.stop()
            if process is not None:
                self._release_process(process)
            self._schedule_restart("worker failed to start")

    def _fail_current(self, reason: str) -> None:
        self._handshake_timer.stop()
        self._heartbeat_timer.stop()
        self._emit_diagnostic("failure", {"reason": reason})
        self.failed.emit(reason)
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if self._terminate_timer is None:
                self._terminate_timer = QTimer(self)
                self._terminate_timer.setSingleShot(True)
                self._terminate_timer.timeout.connect(self._on_terminate_timeout)
            self._terminate_timer.start(500)
        else:
            self._schedule_restart(reason)

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        process = self._process
        if self._shutdown_timer is not None:
            self._shutdown_timer.stop()
        if self._terminate_timer is not None:
            self._terminate_timer.stop()
        self._handshake_timer.stop()
        self._heartbeat_timer.stop()
        self._io_timer.stop()
        self._read_stdout()
        self._read_stderr()
        if process is not None:
            self._release_process(process)
        if self._requested_stop:
            self._set_state(self.STOPPED)
            return
        detail = {"exit_code": exit_code, "exit_status": str(exit_status)}
        self._set_state(self.CRASHED)
        self._emit_diagnostic("crashed", detail)
        self._schedule_restart("worker exited")

    def _schedule_restart(self, reason: str) -> None:
        if self._requested_stop:
            self._set_state(self.STOPPED)
            return
        now = time.monotonic()
        while self._restart_times and now - self._restart_times[0] > self.restart_window_s:
            self._restart_times.popleft()
        if len(self._restart_times) >= self.max_restarts:
            self._set_state(self.FAULT)
            self._emit_diagnostic("fault", {"reason": reason, "restart_count": len(self._restart_times)})
            self.failed.emit(reason)
            return
        index = len(self._restart_times)
        self._restart_times.append(now)
        delay = self.restart_backoff_s[min(index, len(self.restart_backoff_s) - 1)]
        self._set_state(self.CRASHED)
        self._emit_diagnostic("restart_scheduled", {"reason": reason, "delay_s": delay, "restart_count": len(self._restart_times)})
        if self._restart_timer is None:
            self._restart_timer = QTimer(self)
            self._restart_timer.setSingleShot(True)
            self._restart_timer.timeout.connect(self._restart_now)
        self._restart_timer.start(max(0, int(delay * 1000)))

    def _restart_now(self) -> None:
        if not self._requested_stop:
            self.start(self._config)

    def _cancel_restart_timer(self) -> None:
        if self._restart_timer is not None:
            self._restart_timer.stop()

    def _release_process(self, process: QProcess) -> None:
        """Release a stopped process exactly once.

        ``QProcess.finished`` can be queued after the native process has
        already reached ``NotRunning``.  Centralising cleanup prevents a
        stopped process from surviving into a later restart or test teardown
        while keeping the production lifecycle asynchronous.
        """
        if process.state() != QProcess.ProcessState.NotRunning:
            return
        if self._process is process:
            self._process = None
        launch = self._launches.pop(process, None)
        if launch is not None:
            launch.close()
        try:
            process.deleteLater()
        except RuntimeError:
            # Qt may already have deleted the QObject through its parent.
            pass

    @classmethod
    def finish_app_shutdown(cls, timeout_ms: int = 4000) -> bool:
        """Drain asynchronous shutdown after the main Qt loop, before destruction.

        aboutToQuit alone cannot keep processing QProcess writes/finished or the
        terminate/kill timers. This exit-only event loop preserves those signals
        without blocking on a native process wait or extending normal UI work.
        All workers share one bounded deadline, not one timeout per worker.
        """
        import shiboken6

        supervisors = [item for item in _LIVE_SUPERVISORS if shiboken6.isValid(item)]
        loop = QEventLoop()
        deadline = QTimer()
        deadline.setSingleShot(True)

        def drained() -> bool:
            return all(item.process is None or item.process.state() == QProcess.ProcessState.NotRunning for item in supervisors)

        def check(_state: str = "") -> None:
            if drained():
                loop.quit()

        deadline.timeout.connect(loop.quit)
        for item in supervisors:
            item.state_changed.connect(check)
            if not item._requested_stop:
                item.stop()
        try:
            if not drained():
                deadline.start(max(1, int(timeout_ms)))
                loop.exec()
            complete = drained()
            if not complete:
                for item in supervisors:
                    if item.process is not None and item.process.state() != QProcess.ProcessState.NotRunning:
                        item._emit_diagnostic("app_shutdown_timeout", {"reason": "exit drain deadline exceeded"})
                        item.process.kill()
            return complete
        finally:
            deadline.stop()
            for item in supervisors:
                item.state_changed.disconnect(check)

    def wait_for_stopped_for_tests(self, timeout_ms: int = 2000) -> None:
        """Wait for this QProcess during test teardown only.

        Production shutdown remains asynchronous.  The test suite needs a small
        bounded drain point so a worker started by one test cannot survive into
        the next test and compete for Qt/process resources.
        """
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        process.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.start(max(1, int(timeout_ms)))
        loop.exec()
        timer.stop()
        try:
            process.finished.disconnect(loop.quit)
        except (RuntimeError, TypeError):
            pass

    @classmethod
    def _shutdown_live_for_tests(cls, timeout_ms: int = 2000) -> None:
        """Stop and drain all live supervisors created by tests.

        This is intentionally a test-only hook.  It does not change the
        non-blocking production lifecycle and is called by pytest teardown.
        """
        supervisors = tuple(_LIVE_SUPERVISORS)
        for supervisor in supervisors:
            try:
                supervisor.stop()
            except (RuntimeError, OSError):
                _LOG.debug("测试收口 Worker supervisor 失败", exc_info=True)
        per_supervisor_ms = max(100, int(timeout_ms))
        for supervisor in supervisors:
            try:
                supervisor.wait_for_stopped_for_tests(per_supervisor_ms)
            except (RuntimeError, OSError):
                _LOG.debug("等待 Worker supervisor 退出失败", exc_info=True)

    def close(self) -> None:
        self.stop()


__all__ = ["WorkerSupervisor"]
