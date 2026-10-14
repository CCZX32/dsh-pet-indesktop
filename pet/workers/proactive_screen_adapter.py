# -*- coding: utf-8 -*-
"""宿主侧识屏传输适配器：把宿主请求翻成 ``pet-worker/v1`` 上的有界往返。

移植自 DLC 分支 `features/screen_understanding/host/worker_adapter.py`
（该分支的 `pet/workers/proactive_screen_adapter.py` 只是兼容别名）。**适配器只
拥有传输边界**：策略、配额状态、窗口呈现与代数权威仍全部属于
:class:`pet.proactive.ProactiveScreenWatcher`。

宿主面改动（逐条）：

1. 请求模型换成本仓库的 :class:`pet.vision.VisionRequestConfig`（DLC 用
   ``features.screen_understanding.common.models.VisionRequestConfig``）。宿主的
   真值仍是 ``pet.chat.models.ProviderConfig``；``_provider_payload`` 做一次
   「ProviderConfig → 可传输 dict → VisionRequestConfig → dict」的往返，字段名
   两侧完全一致，不存在第二套命名；
2. **独立视觉端点的钥匙串解析留在宿主**：``vision_same_as_chat=False`` 且明文
   钥匙为空时，由宿主（已经加载了聊天包与 keyring）解析 ``vision_api_key_ref``
   并把结果写进明文，然后把 ``vision_api_key_ref`` 从载荷里删掉——子进程因此
   永远不会走到凭据解析（`pet.vision._post_vision_request` 那条惰性 import 在
   worker 侧结构性不可达）；
3. 诊断白名单换成 `pet/workers/worker_diagnostics.py`（DLC 在
   ``features/screen_understanding/host/worker_diagnostics.py``，函数体一致）；
4. 新增 :meth:`ProactiveScreenWorkerAdapter.status_snapshot`：给设置页「主动识屏」
   用的**如实状态快照**（模式/状态/代数/待答请求数/最近诊断），由 watcher 落盘
   成可跨进程读取的小文件（见 `pet/proactive_worker_status.py`）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .launch import WorkerLaunch
from .protocol import WorkerMessage
from .supervisor import WorkerSupervisor
from .worker_diagnostics import failure_hint, safe_diagnostic

log = logging.getLogger("dsh-pet-standalone.worker-proactive-screen")

#: 允许下发给 worker 的配置键（其余键——尤其是任何钥匙——一律丢掉）。
_CONFIG_KEYS = frozenset({"max_edge", "jpeg_quality", "frame_ttl", "platform"})

#: 单飞请求上限：超过就拒绝新请求而不是无限堆积。
MAX_PENDING_REQUESTS = 16


@dataclass(frozen=True)
class _PendingRequest:
    operation: str
    generation: int | None
    kind: str
    deadline: float


class ProactiveScreenWorkerAdapter(QObject):
    """Translate Core requests to the bounded proactive-screen worker."""

    state_changed = Signal(str)
    observation_ready = Signal(object)
    capture_ready = Signal(object)
    analysis_ready = Signal(object)
    manual_ready = Signal(object)
    request_failed = Signal(str, object)
    failed = Signal(str)
    diagnostic = Signal(str, object)

    ACTIVE_STATES = frozenset(
        {
            WorkerSupervisor.STARTING,
            WorkerSupervisor.HANDSHAKING,
            WorkerSupervisor.READY,
        }
    )

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        mode: str = "auto",
        program: str | None = None,
        arguments: Sequence[str] | None = None,
        budget_checker: Callable[[str, int | None], bool] | None = None,
        launch_factory: Callable[[], WorkerLaunch] | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode if mode in {"auto", "in_process", "disabled"} else "auto"
        self._budget_checker = budget_checker
        self._config: dict[str, Any] = {}
        self._pending: dict[str, _PendingRequest] = {}
        #: STOPPING 期间来过的 start：进程停定（stopped）时补拉一次，不静默丢弃。
        self._pending_start = False
        self._deadline_timer = QTimer(self)
        self._deadline_timer.setInterval(500)
        self._deadline_timer.timeout.connect(self._expire_requests)
        self._last_diagnostic: tuple[str, dict[str, Any]] | None = None
        self.supervisor = WorkerSupervisor(
            "proactive-screen",
            self,
            program=program,
            arguments=arguments,
            launch_factory=launch_factory,
            required_capabilities=("foreground.read", "screenshot.capture", "vision.request", "logging.write"),
        )
        self.supervisor.state_changed.connect(self._on_state_changed)
        self.supervisor.stop_requested.connect(self._on_stop_requested)
        self.supervisor.response_received.connect(self._on_response)
        self.supervisor.request_received.connect(self._on_request)
        self.supervisor.diagnostic.connect(self._on_diagnostic)
        self.supervisor.failed.connect(self._on_failed)

    @property
    def state(self) -> str:
        return self.supervisor.state

    @property
    def generation(self) -> int:
        return self.supervisor.generation

    @property
    def ready(self) -> bool:
        return self.state == WorkerSupervisor.READY

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE_STATES

    def start(self, config: Mapping[str, Any] | None = None) -> bool:
        """Start the selected worker unless the adapter is in fallback mode."""
        self._config = self._sanitize_config(config or {})
        if self.mode != "auto":
            return False
        if self.active:
            self._pending_start = False
            if self.ready:
                return self.supervisor.configure(self._config)
            return False
        if self.supervisor.state == WorkerSupervisor.STOPPING:
            # 还在关闭阶梯里：现在拉起会被 supervisor 明确拒绝（进程还没退）。**不能**
            # 就这样丢掉——"隐藏→恢复"正好会落在这个窗口里（pause 停 worker、resume
            # 立刻再拉），丢掉的后果是恢复之后识屏再也不开工，而现场一次报错都没有。
            # 记成待补拉，等进程真的停定（stopped）再起一次。
            self._pending_start = True
            return False
        self._pending_start = False
        self._pending.clear()
        return self.supervisor.start(self._config)

    def configure(self, config: Mapping[str, Any] | None = None) -> bool:
        if config is not None:
            self._config = self._sanitize_config(config)
        if self.mode != "auto" or not self.ready:
            return False
        return self.supervisor.configure(self._config)

    def stop(self) -> None:
        # 显式停优先于待补拉：停就是停（用户关掉主动识屏时不该被一次排队的 start 复活）。
        self._pending_start = False
        self._fail_pending("worker_stopped")
        self.supervisor.stop()

    def diagnostics(self) -> dict[str, Any]:
        stage, detail = self._last_diagnostic or ("", {})
        return {
            "worker_id": self.supervisor.worker_id,
            "mode": self.mode,
            "state": self.state,
            "generation": self.generation,
            "pending": len(self._pending),
            "last_stage": stage,
            "last_detail": dict(detail),
        }

    def status_snapshot(self) -> dict[str, Any]:
        """给设置页用的如实快照（纯数据，可跨进程落盘后展示）。"""
        stage, detail = self._last_diagnostic or ("", {})
        return {
            "mode": self.mode,
            "state": self.state,
            "generation": self.generation,
            "pending": len(self._pending),
            "last_stage": str(stage),
            "last_detail": dict(detail),
            "hint": failure_hint(detail) if stage else "",
        }

    # --------------------------------------------------------------- requests
    def observe_foreground(self, generation: int) -> str | None:
        return self._send("observe_foreground", {"kind": "automatic"}, generation=generation, kind="automatic")

    def capture_foreground(self, window: Mapping[str, Any], generation: int) -> str | None:
        return self._send(
            "capture_foreground",
            {"kind": "automatic", "window": dict(window)},
            generation=generation,
            kind="automatic",
        )

    def analyze_frame(
        self,
        frame_id: str,
        provider: Any,
        system_prompt: str,
        *,
        generation: int,
        memory_context: str = "",
        pet_name: str = "",
    ) -> str | None:
        return self._send(
            "analyze_frame",
            {
                "kind": "automatic",
                "frame_id": str(frame_id),
                "provider": self._provider_payload(provider),
                "system_prompt": str(system_prompt),
                "memory_context": str(memory_context),
                "pet_name": str(pet_name),
            },
            generation=generation,
            kind="automatic",
        )

    def manual_look(
        self,
        provider: Any,
        system_prompt: str,
        *,
        generation: int,
        memory_context: str = "",
        pet_name: str = "",
    ) -> str | None:
        return self._send(
            "manual_look",
            {
                "kind": "manual",
                "provider": self._provider_payload(provider),
                "system_prompt": str(system_prompt),
                "memory_context": str(memory_context),
                "pet_name": str(pet_name),
            },
            generation=generation,
            kind="manual",
        )

    def release_frame(self, frame_id: str, generation: int | None = None) -> str | None:
        return self._send(
            "release_frame",
            {"kind": "automatic", "frame_id": str(frame_id)},
            generation=generation,
            kind="automatic",
        )

    def cancel(self, request_id: str, generation: int | None = None) -> str | None:
        self._pending.pop(request_id, None)
        return self._send(
            "cancel",
            {"kind": "manual", "request_id": str(request_id)},
            generation=generation,
            kind="manual",
        )

    def _send(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        generation: int | None,
        kind: str,
    ) -> str | None:
        if self.mode != "auto" or not self.ready or len(self._pending) >= MAX_PENDING_REQUESTS:
            return None
        request_id = self.supervisor.send_request(operation, arguments, generation=generation)
        if request_id is not None:
            # A missing response must not permanently leave the GUI busy.
            timeout = 240.0 if operation in {"analyze_frame", "manual_look"} else 15.0
            self._pending[request_id] = _PendingRequest(operation, generation, kind, time.monotonic() + timeout)
            self._deadline_timer.start()
        return request_id

    # --------------------------------------------------------------- responses
    def _on_response(self, message: WorkerMessage) -> None:
        request_id = message.request_id or ""
        pending = self._pending.pop(request_id, None)
        payload = dict(message.payload)
        operation = str(payload.get("operation", pending.operation if pending else ""))
        response_generation = self._int_or_none(payload.get("generation"))
        if pending is None:
            self._emit_diag("response", {"reason": "response has no pending request", "operation": operation})
            return
        if operation != pending.operation or response_generation != pending.generation or payload.get("status") not in {"ok", "error"}:
            self._fail_request(request_id, pending, "invalid_response")
            return
        envelope: dict[str, Any] = {
            "request_id": request_id,
            "operation": operation,
            "generation": response_generation,
            "status": str(payload.get("status", "ok")),
        }
        result = payload.get("result")
        if isinstance(result, dict):
            envelope["result"] = dict(result)
        for key in ("error_code", "message", "retryable"):
            if key in payload:
                envelope[key] = payload[key]
        if envelope["status"] == "error":
            self.request_failed.emit(operation, envelope)
            return
        if operation == "observe_foreground":
            self.observation_ready.emit(envelope)
        elif operation == "capture_foreground":
            self.capture_ready.emit(envelope)
        elif operation == "analyze_frame":
            self.analysis_ready.emit(envelope)
        elif operation == "manual_look":
            self.manual_ready.emit(envelope)
        elif operation not in {"release_frame", "cancel"}:
            self._emit_diag("response", {"reason": "unknown response operation", "operation": operation})

    def _on_request(self, message: WorkerMessage) -> None:
        operation = str(message.payload.get("operation", ""))
        if operation != "budget_check" or not message.request_id:
            self._emit_diag("request", {"reason": "unsupported worker request", "operation": operation})
            return
        arguments = message.payload.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        kind = str(arguments.get("kind", "automatic"))
        generation = self._int_or_none(message.payload.get("generation"))
        allowed = False
        try:
            parent = self._pending.get(str(arguments.get("parent_request_id", "")))
            if (
                self._budget_checker is not None
                and parent is not None
                and parent.operation == "analyze_frame"
                and parent.kind == kind == "automatic"
                and parent.generation == generation
            ):
                allowed = bool(self._budget_checker(kind, generation))
        except Exception:
            log.exception("主动识屏 Worker 额度检查失败")
            allowed = False
        self.supervisor.send_response(
            message.request_id,
            "budget_check",
            {"status": "ok", "result": {"allowed": allowed}},
            generation=generation,
        )

    # -------------------------------------------------------------- lifecycle
    def _on_stop_requested(self) -> None:
        """supervisor 被要求停：显式停优先于待补拉（停就是停）。

        适配器自己的 ``stop()`` 也会清这个标记，但退出收口那两条路径
        （``WorkerSupervisor.finish_app_shutdown`` / ``_shutdown_live_for_tests``）
        直接调 ``supervisor.stop()``，不经过适配器——所以作废这件事挂在 supervisor 的
        通知上，而不是挂在某一个调用方上。
        """
        self._pending_start = False

    def _on_state_changed(self, state: str) -> None:
        if state in {"crashed", "fault", "stopping", "stopped"}:
            self._fail_pending("worker_unavailable")
        if state == WorkerSupervisor.STOPPED and self._pending_start:
            # 关闭阶梯走完了：把 STOPPING 期间那次 start 补上（见 :meth:`start`）。
            # 直接调，不再排一次 0ms 定时器——start() 只会换一个 QProcess 并置 STARTING，
            # 不依赖本栈里那个已释放的旧进程（`_release_process` 在 STOPPED 之前就跑过了）。
            self._pending_start = False
            self.start(self._config)
        self.state_changed.emit(state)

    def _on_failed(self, reason: str) -> None:
        self._fail_pending("worker_unavailable")
        self.failed.emit(str(reason))

    def _fail_request(self, request_id: str, pending: _PendingRequest, code: str) -> None:
        self.request_failed.emit(
            pending.operation,
            {
                "request_id": request_id,
                "operation": pending.operation,
                "generation": pending.generation,
                "status": "error",
                "error_code": code,
                "message": "识屏任务已结束，请重试",
                "retryable": True,
            },
        )

    def _fail_pending(self, code: str) -> None:
        pending, self._pending = self._pending, {}
        self._deadline_timer.stop()
        for request_id, item in pending.items():
            self._fail_request(request_id, item, code)

    def _expire_requests(self) -> None:
        now = time.monotonic()
        for request_id, item in list(self._pending.items()):
            if now >= item.deadline:
                self._pending.pop(request_id, None)
                if item.operation not in {"cancel", "release_frame"} and self.ready:
                    # No acknowledgement is retained for this best-effort cancellation.
                    self.supervisor.send_request("cancel", {"request_id": request_id}, generation=item.generation)
                self._fail_request(request_id, item, "request_timeout")
        if not self._pending:
            self._deadline_timer.stop()

    def _on_diagnostic(self, stage: str, detail: object) -> None:
        data = safe_diagnostic(detail)
        self._last_diagnostic = (str(stage), data)
        self.diagnostic.emit(str(stage), data)

    def _emit_diag(self, stage: str, detail: Mapping[str, Any]) -> None:
        self._last_diagnostic = (str(stage), dict(detail))
        self.diagnostic.emit(str(stage), dict(detail))

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sanitize_config(config: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key): value for key, value in config.items() if str(key) in _CONFIG_KEYS}

    @staticmethod
    def _provider_payload(provider: Any) -> dict[str, Any]:
        from ..vision import VisionRequestConfig

        if hasattr(provider, "to_dict"):
            data = provider.to_dict(include_secret=True)
        elif isinstance(provider, Mapping):
            data = dict(provider)
        else:
            raise TypeError("provider must be a mapping or expose to_dict()")
        if not isinstance(data, dict):
            raise TypeError("provider payload must be an object")
        data = _resolve_vision_credential(data)
        # 往返一次：worker 侧读到的字段集与本模块认定的可传输字段集是同一份
        # （多余的键在这里就被丢掉，子进程见不到 api_key_ref / thinking 之类）。
        return VisionRequestConfig.from_dict(data).to_dict(include_secret=True)


def _resolve_vision_credential(data: dict[str, Any]) -> dict[str, Any]:
    """把独立视觉端点的钥匙串解析放在**宿主**做完，再交给子进程。

    与聊天同模型时用的是 ``api_key``（宿主早已解析）；独立端点必须用
    ``vision_api_key``，明文为空而只有 ref 时由这里解析。解析完删掉 ref——
    子进程不该也不需要一个指向钥匙串的指针。
    """
    ref = str(data.get("vision_api_key_ref") or "")
    if not data.get("vision_same_as_chat", True) and not data.get("vision_api_key") and ref:
        try:
            from ..chat.models import SecretStore

            resolved = SecretStore().get(ref)
        except Exception:
            log.exception("读取独立视觉服务密钥失败")
            resolved = ""
        if resolved:
            data["vision_api_key"] = resolved
    data.pop("vision_api_key_ref", None)
    data.pop("api_key_ref", None)
    return data


__all__ = ["ProactiveScreenWorkerAdapter"]
