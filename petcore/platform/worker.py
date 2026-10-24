"""Small process host for feature workers.

Workers communicate with one JSON object per line.  The host owns all pipe
threads and never exposes a Qt object to the worker process; callers can use
events or their own queued bridge at the UI boundary.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..contracts import worker as protocol

logger = logging.getLogger("petcore.platform.worker")


class WorkerSession:
    def __init__(
        self,
        owner: str,
        argv: list[str],
        *,
        generation: int = 0,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[BaseException | str], None] | None = None,
        on_exit: Callable[[int | None], None] | None = None,
        heartbeat_timeout: float = 30.0,
    ) -> None:
        if not argv:
            raise ValueError("worker argv must not be empty")
        self.owner = str(owner)
        self.generation = int(generation)
        self.argv = [str(item) for item in argv]
        self.env = dict(env or {})
        self.cwd = str(cwd) if cwd is not None else None
        self.on_message = on_message
        self.on_error = on_error
        self.on_exit = on_exit
        self.heartbeat_timeout = max(0.0, float(heartbeat_timeout))
        self.process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._ready = threading.Event()
        self._exited = threading.Event()
        self._last_heartbeat = time.monotonic()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    @property
    def pid(self) -> int | None:
        process = self.process
        return process.pid if process is not None else None

    def start(
        self, *, wait_ready: bool = False, ready_timeout: float = 5.0
    ) -> "WorkerSession":
        if self.process is not None:
            raise RuntimeError("worker session already started")
        merged_env = os.environ.copy()
        merged_env.update(self.env)
        try:
            self.process = subprocess.Popen(
                self.argv,
                cwd=self.cwd,
                env=merged_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                close_fds=True,
            )
        except OSError as exc:
            self._report_error(exc)
            raise
        self._reader = threading.Thread(
            target=self._read_stdout, name=f"petcore-worker-{self.owner}-out", daemon=True
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, name=f"petcore-worker-{self.owner}-err", daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()
        if self.heartbeat_timeout > 0:
            self._watchdog = threading.Thread(
                target=self._watch_heartbeat,
                name=f"petcore-worker-{self.owner}-watchdog",
                daemon=True,
            )
            self._watchdog.start()
        self.send({"type": protocol.HELLO, "owner": self.owner})
        self._started.set()
        if wait_ready and not self.wait_ready(ready_timeout):
            self.shutdown(timeout=min(max(float(ready_timeout), 0.05), 1.0))
            raise TimeoutError(f"worker {self.owner} did not complete handshake")
        return self

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """Wait for the worker's ``ready`` handshake without polling or sleeps."""
        if self._ready.is_set():
            return True
        if self._exited.is_set():
            return False
        return self._ready.wait(max(0.0, float(timeout)))

    def send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise RuntimeError(f"worker {self.owner} is not running")
        line = protocol.encode(message)
        with self._write_lock:
            try:
                process.stdin.write(line + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._report_error(exc)
                raise RuntimeError(f"worker {self.owner} pipe is closed") from exc

    def push_config(self, config: dict[str, Any]) -> None:
        self.send({"type": protocol.CONFIG_PUSH, "config": dict(config)})

    def cancel(self, request_id: str) -> None:
        self.send({"type": protocol.CANCEL, protocol.REQUEST_ID: str(request_id)})

    def request(self, request_id: str, payload: dict[str, Any]) -> None:
        self.send(
            {
                "type": protocol.REQUEST,
                protocol.REQUEST_ID: str(request_id),
                "payload": dict(payload),
            }
        )

    def shutdown(self, timeout: float = 2.0) -> None:
        process = self.process
        if process is None:
            return
        self._stop.set()
        if process.poll() is None:
            try:
                self.send({"type": protocol.SHUTDOWN})
            except RuntimeError:
                pass
            try:
                process.wait(timeout=max(0.05, float(timeout)))
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=max(0.05, float(timeout)))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if self._stop.is_set() and not line.strip():
                    break
                try:
                    message = protocol.decode(line)
                except (TypeError, ValueError) as exc:
                    self._report_error(exc)
                    continue
                message_type = message.get("type")
                if message_type == protocol.READY:
                    self._ready.set()
                elif message_type == protocol.HEARTBEAT:
                    self._last_heartbeat = time.monotonic()
                callback = self.on_message
                if callback is not None:
                    try:
                        callback(message)
                    except Exception as exc:
                        self._report_error(exc)
        finally:
            self._exited.set()
            code = process.poll()
            if code is None:
                code = process.wait()
            callback = self.on_exit
            if callback is not None:
                try:
                    callback(code)
                except Exception:
                    logger.exception("worker exit callback failed: %s", self.owner)

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            text = line.rstrip()
            if text:
                logger.warning("worker %s stderr: %s", self.owner, text[:1000])

    def _watch_heartbeat(self) -> None:
        interval = min(max(self.heartbeat_timeout / 4.0, 0.05), 1.0)
        while not self._stop.wait(interval):
            if not self.alive:
                return
            if time.monotonic() - self._last_heartbeat > self.heartbeat_timeout:
                self._report_error(f"worker {self.owner} heartbeat timeout")
                self.shutdown(timeout=0.2)
                return

    def _report_error(self, error: BaseException | str) -> None:
        callback = self.on_error
        if callback is not None:
            try:
                callback(error)
            except Exception:
                logger.exception("worker error callback failed: %s", self.owner)
        else:
            logger.warning("worker %s error: %s", self.owner, error)


class WorkerHost:
    def __init__(self) -> None:
        self._sessions: dict[str, WorkerSession] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.RLock()

    def start(
        self,
        owner: str,
        argv: list[str],
        env: dict[str, str] | None = None,
        *,
        cwd: str | Path | None = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[BaseException | str], None] | None = None,
        on_exit: Callable[[int | None], None] | None = None,
        heartbeat_timeout: float = 30.0,
        ready_timeout: float = 0.0,
    ) -> WorkerSession:
        owner = str(owner)
        with self._lock:
            old = self._sessions.pop(owner, None)
            generation = self._generations.get(owner, 0) + 1
            self._generations[owner] = generation
        if old is not None:
            old.shutdown()

        session = WorkerSession(
            owner,
            argv,
            generation=generation,
            env=env,
            cwd=cwd,
            on_message=lambda message, owner=owner, generation=generation, callback=on_message:
                self._on_message(owner, generation, callback, message),
            on_error=lambda error, owner=owner, generation=generation, callback=on_error:
                self._on_error(owner, generation, callback, error),
            on_exit=lambda code, owner=owner, generation=generation, callback=on_exit:
                self._on_exit(owner, generation, code, callback),
            heartbeat_timeout=heartbeat_timeout,
        )
        with self._lock:
            self._sessions[owner] = session
        try:
            session.start(wait_ready=ready_timeout > 0, ready_timeout=ready_timeout)
        except Exception:
            with self._lock:
                if self._sessions.get(owner) is session:
                    self._sessions.pop(owner, None)
            raise
        return session

    def get(self, owner: str) -> WorkerSession | None:
        with self._lock:
            return self._sessions.get(str(owner))

    def stop(self, owner: str, timeout: float = 2.0) -> None:
        with self._lock:
            session = self._sessions.pop(str(owner), None)
        if session is not None:
            session.shutdown(timeout)

    def shutdown_all(self, timeout: float = 2.0) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.shutdown(timeout)

    def _is_current(self, owner: str, generation: int) -> bool:
        with self._lock:
            session = self._sessions.get(owner)
            return session is not None and session.generation == generation

    def _on_message(self, owner: str, generation: int, callback, message) -> None:
        if callback is not None and self._is_current(owner, generation):
            callback(message)

    def _on_error(self, owner: str, generation: int, callback, error) -> None:
        if callback is not None and self._is_current(owner, generation):
            callback(error)

    def _on_exit(self, owner: str, generation: int, code: int | None, callback) -> None:
        with self._lock:
            session = self._sessions.get(owner)
            current = session is not None and session.generation == generation
            if current and not session.alive:
                self._sessions.pop(owner, None)
        # An old process can finish after a replacement has started.  Its exit
        # and error/message callbacks must not affect the new generation.
        if current and callback is not None:
            callback(code)
