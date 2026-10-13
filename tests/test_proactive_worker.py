# -*- coding: utf-8 -*-
"""主动识屏 worker（子进程执行侧）：协议往返、限额、隐私与导入边界。

蓝本 = DLC 分支的 ``tests/test_screen_worker_boundary.py`` +
``tests/test_proactive_worker_integration.py``，按本仓库落点重写。

三组证据：

1. **协议级**（本进程，真 ``ProactiveScreenWorker`` + 线程安全的管道替身）：
   握手、请求路由、忙态、取消、帧过期、额度反向请求、错误码与密钥遮蔽；
2. **真进程**：``python -m pet --worker proactive-screen`` 经 ``WorkerSupervisor``
   握手 → 观察前台 → 优雅收口（不靠假 worker）；
3. **导入边界**：真子进程 + setuptools 元路径拦截器，跑完整一次
   「截图 → 发视觉请求」往返（真的打到本地 HTTP 服务器），证明这条链在
   **完全不加载 Qt / pet.chat / pet.config** 的前提下能工作。

时序纪律：一律事件/条件变量同步 + 宽预算，不用固定 sleep 猜时序。
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 与 tests/test_workers_lifecycle.py 同规：QApplication 必须**先于**任何
#: QObject/QTimer 存在。晚建会得到一个没有事件分发器的现场——supervisor 的
#: io/handshake/heartbeat 三个 QTimer 在构造期就绑定了失效的定时器，收口阶梯
#: 随之时灵时不灵（实测：stop() 后卡在 stopping）。生产路径天然满足这个顺序
#: （pet/app.py 先建 QApplication，watcher 才建适配器），测试必须自己立规矩。
from PySide6.QtWidgets import QApplication as _QApplication

_APP = _QApplication.instance() or _QApplication([])

_BUDGET_S = 30.0
_READY_BUDGET_S = 90.0

WORKER_ID = "proactive-screen"
CAPABILITIES = [
    "foreground.read",
    "screenshot.capture",
    "vision.request",
    "logging.write",
]


# ---------------------------------------------------------------- 测试夹具

class WorkerHarness:
    """把真 worker 挂在一条真管道上，供测试逐帧驱动。

    ``os.pipe`` + 非缓冲 FileIO：worker 的 stdin 读线程真的会阻塞等待，测试可以
    在任意时刻喂下一帧——这不是"把命令一次性塞进去然后赌它处理完"，每条断言都在
    自己的响应帧到达后才判定。
    """

    def __init__(self) -> None:
        read_fd, self._write_fd = os.pipe()
        self._stdin = os.fdopen(read_fd, "rb", 0)
        self._out = io.BytesIO()
        self.frames: list[dict] = []
        self._cond = threading.Condition()
        self._error: BaseException | None = None

        from pet.workers.proactive_screen_worker import ProactiveScreenWorker

        self.worker = ProactiveScreenWorker(stdin=self._stdin, stdout=self._out)
        self._thread = threading.Thread(target=self._run, name="test-proactive-worker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.worker.run()
        except BaseException as exc:  # pragma: no cover - 只用于把子线程异常带回主线程
            self._error = exc
        finally:
            with self._cond:
                self._cond.notify_all()

    def send(self, message_type: str, payload: dict | None = None, *, request_id: str | None = None) -> str:
        from pet.workers.protocol import build_message, encode_message

        message = build_message(WORKER_ID, message_type, payload or {}, request_id=request_id)
        os.write(self._write_fd, encode_message(message))
        return message.request_id or ""

    def request(self, operation: str, arguments: dict | None = None, *, generation: int = 1) -> str:
        return self.send(
            "request",
            {"operation": operation, "generation": generation, "arguments": arguments or {}},
            request_id=f"req-{operation}-{generation}-{time.monotonic_ns()}",
        )

    def _parse(self) -> None:
        raw = self._out.getvalue()
        text = raw.decode("utf-8", "replace")
        lines = text.split("\n")
        # 最后一段可能只写了一半：只解析完整的行。
        complete = lines[:-1]
        parsed = []
        for line in complete:
            if line.strip():
                parsed.append(json.loads(line))
        with self._cond:
            self.frames = parsed
            self._cond.notify_all()

    def wait_for(self, predicate, *, timeout: float = _BUDGET_S, what: str = ""):
        """等到 predicate(frames) 成立；返回命中的帧或 None（超时）。"""
        deadline = time.monotonic() + timeout
        while True:
            self._parse()
            with self._cond:
                hit = predicate(list(self.frames))
            if hit:
                return hit
            if self._error is not None:
                raise AssertionError(f"worker 线程异常：{self._error!r}")
            if time.monotonic() >= deadline:
                pytest.fail(f"等待超时：{what or predicate}；已收到的帧：{self.frames}")
            time.sleep(0.01)

    def wait_for_state(self, state: str) -> None:
        self.send("config_push", {"generation": 1, "max_edge": 640, "jpeg_quality": 75, "frame_ttl": 5.0})
        ready = self.wait_for(lambda frames: next((f for f in frames if f["type"] == "ready"), None), what="ready")
        assert ready["payload"]["configured"] is True
        assert ready["payload"]["capabilities"] == CAPABILITIES
        assert state == "ready"

    def response_for(self, request_id: str) -> dict:
        frame = self.wait_for(
            lambda frames: next(
                (f for f in frames if f.get("request_id") == request_id and f["type"] == "response"),
                None,
            ),
            what=f"{request_id} 的响应",
        )
        return frame

    def close(self) -> None:
        try:
            os.close(self._write_fd)
        except OSError:
            pass
        self._thread.join(timeout=10.0)
        try:
            self._stdin.close()
        except OSError:
            pass

    def __enter__(self) -> "WorkerHarness":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


@pytest.fixture()
def harness():
    created = WorkerHarness()
    try:
        yield created
    finally:
        created.close()


class _FakeImage:
    """够 `_encode_image` 用的小图（PIL 真对象，别的一概不要）。"""

    @staticmethod
    def make(color: str = "navy", size: tuple[int, int] = (64, 48)):
        from PIL import Image

        return Image.new("RGB", size, color)


def _fake_foreground(hwnd: int = 42, pid: int = 7, process: str = "code.exe", title: str = "fixture"):
    return {
        "hwnd": hwnd,
        "pid": pid,
        "process": process,
        "title": title,
        "rect": [0, 0, 100, 80],
    }


def _patch_vision(monkeypatch, *, foreground=None, image=None, calls: list | None = None):
    """把 worker 会用到的 `pet.vision` 原语换成确定性替身（只换 OS 边界）。"""
    from pet import vision

    captured: list = calls if calls is not None else []
    current = {"info": foreground if foreground is not None else _fake_foreground()}

    def _foreground():
        return current["info"]

    def _capture(rect):
        captured.append(("capture", tuple(rect)))
        return image if image is not None else _FakeImage.make()

    monkeypatch.setattr(vision, "foreground_window_info", _foreground)
    monkeypatch.setattr(vision, "capture_window_rect", _capture)
    return current, captured


# ------------------------------------------------------------------ 协议往返

def test_hello_is_the_first_frame_and_reports_the_lease(monkeypatch):
    # 交接契约在**子进程启动的那一刻**就定下（环境变量），所以这里自己建 harness。
    monkeypatch.setenv("DSH_PET_WORKER_HANDOFF_TOKEN", "unit-test-token")
    harness = WorkerHarness()
    try:
        harness.send("heartbeat")
        harness.wait_for(lambda frames: any(f["type"] == "hello" for f in frames), what="hello")
        hello = harness.frames[0]
        assert hello["type"] == "hello"
        assert hello["worker_id"] == WORKER_ID
        assert hello["payload"]["capabilities"] == CAPABILITIES
        assert hello["payload"]["lease_claimed"] is True
        assert isinstance(hello["payload"]["pid"], int)
    finally:
        harness.close()


def test_config_push_answers_ready_and_clamps_out_of_range_values(harness):
    harness.send("config_push", {"generation": 3, "max_edge": 99999, "jpeg_quality": 1, "frame_ttl": 9999})
    ready = harness.wait_for(lambda frames: next((f for f in frames if f["type"] == "ready"), None), what="ready")
    assert ready["payload"]["generation"] == 3
    assert harness.worker._config == {"max_edge": 4096, "jpeg_quality": 40, "frame_ttl": 120.0}


def test_a_request_before_config_is_refused_as_not_ready(harness):
    request_id = harness.request("observe_foreground")
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "error"
    assert response["payload"]["error_code"] == "not_ready"


def test_unknown_operation_is_refused_without_echoing_its_arguments(harness):
    harness.wait_for_state("ready")
    secret = "unit-test-secret-not-for-wire-log"
    request_id = harness.request("not_an_operation", {"api_key": secret, "provider": {"api_key": secret}})
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "error"
    assert response["payload"]["error_code"] == "unknown_operation"
    assert secret not in json.dumps(response, ensure_ascii=False)


def test_observe_foreground_returns_a_bounded_window(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    request_id = harness.request("observe_foreground")
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "ok"
    result = response["payload"]["result"]
    assert result["window"]["hwnd"] == 42
    assert result["window"]["process"] == "code.exe"
    assert result["app_info"] == "code.exe | fixture"


def test_capture_foreground_rejects_a_foreground_that_changed(harness, monkeypatch):
    harness.wait_for_state("ready")
    current, captured = _patch_vision(monkeypatch)
    request_id = harness.request("capture_foreground", {"window": {"hwnd": 999, "pid": 7}})
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "error"
    assert response["payload"]["error_code"] == "foreground_changed"
    assert captured == [], "前台不匹配时绝不许截图"


def test_capture_foreground_hashes_before_downsampling_and_hides_the_frame(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    request_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    response = harness.response_for(request_id)
    result = response["payload"]["result"]
    assert response["payload"]["status"] == "ok"
    assert result["window"]["hwnd"] == 42
    assert isinstance(result["dhash"], int)
    # 截图本体留在子进程：协议帧里只有元数据，绝不含图像字节。
    assert "jpeg" not in result and result["size"] > 0
    assert harness.worker._frame is not None
    release_id = harness.request("release_frame", {"frame_id": result["frame_id"]})
    assert harness.response_for(release_id)["payload"]["result"] == {"released": True}
    assert harness.worker._frame is None


def test_analyze_frame_uses_the_vision_transport_and_reports_the_kind(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    from pet import vision

    seen: list[tuple] = []

    def _post(jpeg, app_info, system_prompt, provider, **kwargs):
        seen.append((jpeg, app_info, system_prompt, provider, kwargs))
        return "她看了一眼"

    monkeypatch.setattr(vision, "_post_vision_request", _post)
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]

    request_id = harness.request(
        "analyze_frame",
        {
            "frame_id": frame_id,
            "provider": {"base_url": "https://vision.invalid", "model": "m", "api_key": "k"},
            "system_prompt": "sys",
            "memory_context": "上次看到你在写代码。",
            "pet_name": "小鱼",
        },
    )
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "ok"
    assert response["payload"]["result"]["reply"] == "她看了一眼"
    assert response["payload"]["result"]["request_metadata"] == {"kind": "automatic"}
    assert seen and seen[0][2] == "sys"
    assert seen[0][4]["memory_context"] == "上次看到你在写代码。"
    assert seen[0][4]["pet_name"] == "小鱼"
    # 帧只消费一次：再分析同一个 frame_id 必须失败。
    assert harness.worker._frame is None
    again = harness.request("analyze_frame", {"frame_id": frame_id, "provider": {"api_key": "k"}})
    assert harness.response_for(again)["payload"]["error_code"] == "frame_unavailable"


def test_analyze_frame_requires_the_key_the_transport_will_use(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    # 独立视觉端点（vision_same_as_chat=False）看的是 vision_api_key，不是 api_key。
    request_id = harness.request(
        "analyze_frame",
        {"frame_id": frame_id, "provider": {"vision_same_as_chat": False, "api_key": "chat-key"}},
    )
    response = harness.response_for(request_id)
    assert response["payload"]["error_code"] == "provider_key_missing"
    assert "chat-key" not in json.dumps(response, ensure_ascii=False)


def test_a_denied_budget_stops_the_request_before_the_http_call(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    from pet import vision

    posted: list = []

    def _post(jpeg, app_info, system_prompt, provider, **kwargs):
        consume = kwargs.get("consume_budget")
        if consume is not None and not consume():
            raise vision.VisionError("每日请求上限已到，今天先陪你到这儿了", code="vision_budget_exhausted")
        posted.append(1)
        return "不该到这里"

    monkeypatch.setattr(vision, "_post_vision_request", _post)
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    request_id = harness.request(
        "analyze_frame",
        {"frame_id": frame_id, "provider": {"api_key": "k"}},
    )
    # 宿主收到反向额度请求并明确拒绝。
    budget = harness.wait_for(
        lambda frames: next(
            (f for f in frames if f["type"] == "request" and f["payload"].get("operation") == "budget_check"),
            None,
        ),
        what="budget_check",
    )
    assert budget["payload"]["arguments"]["kind"] == "automatic"
    assert budget["payload"]["arguments"]["parent_request_id"] == request_id
    harness.send(
        "response",
        {"operation": "budget_check", "generation": 1, "status": "ok", "result": {"allowed": False}},
        request_id=budget["request_id"],
    )
    response = harness.response_for(request_id)
    assert response["payload"]["error_code"] == "vision_budget_exhausted"
    assert posted == []


def test_manual_look_never_charges_the_automatic_budget(harness, monkeypatch):
    harness.wait_for_state("ready")
    from pet import vision

    monkeypatch.setattr(vision, "foreground_window_info", lambda: _fake_foreground())
    monkeypatch.setattr(vision, "capture_screen_bytes", lambda: b"jpeg-bytes")
    monkeypatch.setattr(vision, "_post_vision_request", lambda *a, **k: "手动看一眼")
    request_id = harness.request(
        "manual_look",
        {"provider": {"api_key": "k"}, "system_prompt": "sys"},
    )
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "ok"
    assert response["payload"]["result"]["request_metadata"] == {"kind": "manual"}
    budget_requests = [
        f for f in harness.frames if f["type"] == "request" and f["payload"].get("operation") == "budget_check"
    ]
    assert budget_requests == [], "手动识屏不该向宿主申请自动额度"


def test_a_second_request_of_the_same_kind_is_busy(harness, monkeypatch):
    harness.wait_for_state("ready")
    from pet import vision

    entered = threading.Event()
    release = threading.Event()

    def _blocked(*_a, **_k):
        entered.set()
        release.wait(20)
        return "ok"

    monkeypatch.setattr(vision, "foreground_window_info", lambda: _fake_foreground())
    monkeypatch.setattr(vision, "capture_screen_bytes", lambda: b"jpeg")
    monkeypatch.setattr(vision, "_post_vision_request", _blocked)
    first = harness.request("manual_look", {"provider": {"api_key": "k"}})
    assert entered.wait(20), "第一个请求没有进入视觉调用"
    second = harness.request("manual_look", {"provider": {"api_key": "k"}})
    response = harness.response_for(second)
    assert response["payload"]["error_code"] == "busy"
    release.set()
    assert harness.response_for(first)["payload"]["status"] == "ok"


def test_cancel_marks_a_running_task(harness, monkeypatch):
    harness.wait_for_state("ready")
    from pet import vision

    entered = threading.Event()
    release = threading.Event()

    def _blocked(*_a, **_k):
        entered.set()
        release.wait(20)
        return "ok"

    monkeypatch.setattr(vision, "foreground_window_info", lambda: _fake_foreground())
    monkeypatch.setattr(vision, "capture_screen_bytes", lambda: b"jpeg")
    monkeypatch.setattr(vision, "_post_vision_request", _blocked)
    target = harness.request("manual_look", {"provider": {"api_key": "k"}})
    assert entered.wait(20)
    cancel_id = harness.request("cancel", {"request_id": target})
    assert harness.response_for(cancel_id)["payload"]["result"] == {"cancelled": True}
    release.set()
    response = harness.response_for(target)
    assert response["payload"]["error_code"] == "cancelled"


def test_a_stale_frame_is_dropped_after_the_generation_changes(harness, monkeypatch):
    harness.wait_for_state("ready")
    from pet import vision

    posted: list = []
    monkeypatch.setattr(vision, "foreground_window_info", lambda: _fake_foreground())
    monkeypatch.setattr(vision, "capture_window_rect", lambda rect: _FakeImage.make())
    monkeypatch.setattr(vision, "_post_vision_request", lambda *a, **k: posted.append(1) or "ok")
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}}, generation=1)
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    # 代次翻转（宿主重配）后旧帧必须作废。
    harness.send("config_push", {"generation": 2, "max_edge": 640})
    harness.wait_for(lambda frames: sum(1 for f in frames if f["type"] == "ready") >= 2, what="第二次 ready")
    assert harness.worker._frame is None
    request_id = harness.request(
        "analyze_frame", {"frame_id": frame_id, "provider": {"api_key": "k"}}, generation=1
    )
    assert harness.response_for(request_id)["payload"]["error_code"] == "frame_unavailable"
    assert posted == []


def test_vision_failure_is_reported_with_its_code_and_retryability(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    from pet import vision

    def _fail(*_a, **_k):
        raise vision.VisionError("模型当前访问量大（免费档高峰限流），稍后再点一次试试", code="vision_rate_limited")

    monkeypatch.setattr(vision, "_post_vision_request", _fail)
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    request_id = harness.request("analyze_frame", {"frame_id": frame_id, "provider": {"api_key": "k"}})
    response = harness.response_for(request_id)
    assert response["payload"]["status"] == "error"
    assert response["payload"]["error_code"] == "vision_rate_limited"
    assert response["payload"]["retryable"] is True
    assert "http" not in response["payload"]["message"].lower()


def test_a_secret_echoed_by_the_model_is_redacted(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    from pet import vision

    secret = "unit-test-provider-secret"
    monkeypatch.setattr(vision, "_post_vision_request", lambda *a, **k: f"我看到 {secret} 出现在屏幕上")
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    request_id = harness.request(
        "analyze_frame", {"frame_id": frame_id, "provider": {"api_key": secret}}
    )
    response = harness.response_for(request_id)
    assert secret not in json.dumps(response, ensure_ascii=False)
    assert "[redacted]" in response["payload"]["result"]["reply"]


def test_frame_ttl_expiry_is_enforced(harness, monkeypatch):
    harness.wait_for_state("ready")
    _patch_vision(monkeypatch)
    with harness.worker._frame_lock:
        pass
    harness.worker._config["frame_ttl"] = 1.0
    capture_id = harness.request("capture_foreground", {"window": {"hwnd": 42, "pid": 7}})
    frame_id = harness.response_for(capture_id)["payload"]["result"]["frame_id"]
    deadline = time.monotonic() + 20.0
    while harness.worker._frame is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert harness.worker._frame is None, "帧必须按 frame_ttl 自行过期"
    request_id = harness.request("analyze_frame", {"frame_id": frame_id, "provider": {"api_key": "k"}})
    assert harness.response_for(request_id)["payload"]["error_code"] == "frame_unavailable"


def test_stdin_eof_stops_the_worker_without_output(harness):
    harness.wait_for_state("ready")
    harness.close()
    assert not harness._thread.is_alive()
    assert harness._error is None


# ------------------------------------------------------------------- 真进程

def _wait_until(predicate, *, timeout: float = _READY_BUDGET_S):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(int(timeout * 1000))
    loop.exec()
    poll.stop()
    deadline.stop()
    return bool(predicate())


def test_real_worker_handshakes_observes_and_shuts_down_gracefully():
    """真 CLI 路由 + 真 QProcess：握手 → 观察前台 → 优雅收口，不留残骸。"""
    from pet.workers.supervisor import WorkerSupervisor

    supervisor = WorkerSupervisor(
        WORKER_ID,
        required_capabilities=tuple(CAPABILITIES),
    )
    assert supervisor.arguments == ["-m", "pet", "--worker", WORKER_ID]
    responses: list = []
    supervisor.response_received.connect(responses.append)
    failures: list = []
    supervisor.failed.connect(failures.append)
    try:
        assert supervisor.start({"max_edge": 640, "jpeg_quality": 75, "frame_ttl": 5.0}) is True
        assert _wait_until(lambda: supervisor.state == WorkerSupervisor.READY), supervisor.state
        request_id = supervisor.send_request("observe_foreground", {"kind": "automatic"}, generation=7)
        assert request_id
        assert _wait_until(lambda: any(m.request_id == request_id for m in responses))
        payload = next(m for m in responses if m.request_id == request_id).payload
        assert payload["operation"] == "observe_foreground"
        assert payload["generation"] == 7
        assert payload["status"] == "ok"
        assert isinstance(payload["result"], dict)
        assert failures == []
    finally:
        supervisor.stop()
        assert _wait_until(lambda: supervisor.state == WorkerSupervisor.STOPPED, timeout=30.0)
    assert supervisor.process is None


def test_real_worker_refuses_an_unknown_operation_over_the_wire():
    from pet.workers.supervisor import WorkerSupervisor

    supervisor = WorkerSupervisor(WORKER_ID, required_capabilities=tuple(CAPABILITIES))
    responses: list = []
    supervisor.response_received.connect(responses.append)
    secret = "integration-secret-never-on-wire"
    try:
        assert supervisor.start({"max_edge": 640})
        assert _wait_until(lambda: supervisor.state == WorkerSupervisor.READY), supervisor.state
        request_id = supervisor.send_request("nope", {"provider": {"api_key": secret}}, generation=2)
        assert _wait_until(lambda: any(m.request_id == request_id for m in responses))
        payload = next(m for m in responses if m.request_id == request_id).payload
        assert payload["error_code"] == "unknown_operation"
        assert secret not in json.dumps(payload, ensure_ascii=False)
    finally:
        supervisor.stop()
        assert _wait_until(lambda: supervisor.state == WorkerSupervisor.STOPPED, timeout=30.0)


# ------------------------------------------------------------ 真进程导入边界

_BOUNDARY_PROBE = r'''
import io, json, os, sys, threading, time
from importlib.abc import MetaPathFinder

BLOCKED = (
    "PySide6", "PyQt5", "PyQt6",
    "pet.app", "pet.window", "pet.chat", "pet.config", "pet.proactive",
    "pet.overlay_shell", "pet.workers.proactive_screen_adapter",
    "pet.workers.supervisor",
)
attempted = []


class NoHost(MetaPathFinder):
    def find_spec(self, fullname, *args):
        if any(fullname == b or fullname.startswith(b + ".") for b in BLOCKED):
            attempted.append(fullname)
            raise AssertionError("worker crossed import boundary: " + fullname)
        return None


sys.meta_path.insert(0, NoHost())
endpoint = sys.argv[1]
report = sys.argv[2]

from PIL import Image
from pet import vision
from pet.workers.proactive_screen_worker import ProactiveScreenWorker
from pet.workers.protocol import build_message, decode_message, encode_message

vision.foreground_window_info = lambda: {
    "hwnd": 42, "pid": 7, "process": "code.exe", "title": "fixture", "rect": [0, 0, 100, 80]
}
vision.capture_window_rect = lambda rect: Image.new("RGB", (100, 80), "navy")

read_fd, write_fd = os.pipe()
out = io.BytesIO()
worker = ProactiveScreenWorker(stdin=os.fdopen(read_fd, "rb", 0), stdout=out)
runner = threading.Thread(target=worker.run, daemon=True)
runner.start()


def send(kind, payload=None, request_id=None):
    os.write(write_fd, encode_message(build_message("proactive-screen", kind, payload or {}, request_id=request_id)))


def frames():
    parsed = []
    for line in out.getvalue().decode("utf-8", "replace").split("\n")[:-1]:
        if line.strip():
            parsed.append(json.loads(line))
    return parsed


def wait(predicate, timeout=40.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hit = predicate(frames())
        if hit:
            return hit
        time.sleep(0.01)
    raise SystemExit("timeout waiting for " + repr(predicate))


send("config_push", {"generation": 1, "max_edge": 640, "jpeg_quality": 70, "frame_ttl": 5.0})
wait(lambda f: any(x["type"] == "ready" for x in f))
send("request", {"operation": "capture_foreground", "generation": 1,
                 "arguments": {"kind": "automatic", "window": {"hwnd": 42, "pid": 7}}}, request_id="cap-1")
capture = wait(lambda f: next((x for x in f if x.get("request_id") == "cap-1"), None))
frame_id = capture["payload"]["result"]["frame_id"]
send("request", {"operation": "analyze_frame", "generation": 1, "arguments": {
    "kind": "automatic", "frame_id": frame_id,
    "provider": {"base_url": endpoint, "model": "fixture-vision", "api_key": "probe-key",
                 "vision_same_as_chat": True, "timeout": 30.0},
    "system_prompt": "probe"}}, request_id="ana-1")

budget = wait(lambda f: next((x for x in f if x["type"] == "request" and x["payload"].get("operation") == "budget_check"), None))
send("response", {"operation": "budget_check", "generation": 1, "status": "ok", "result": {"allowed": True}},
     request_id=budget["request_id"])
answer = wait(lambda f: next((x for x in f if x.get("request_id") == "ana-1"), None), timeout=90.0)

os.close(write_fd)
runner.join(10)
loaded = sorted(
    name for name in sys.modules
    if any(name == b or name.startswith(b + ".") for b in BLOCKED)
)
with open(report, "w", encoding="utf-8") as stream:
    json.dump({"reply": answer["payload"].get("result", {}).get("reply"),
               "status": answer["payload"].get("status"),
               "attempted": attempted, "loaded": loaded}, stream)
'''


def test_analysis_over_a_real_endpoint_stays_qt_free(tmp_path: Path):
    """worker 里跑完一次**真的**视觉 HTTP 往返，全程不加载 Qt/聊天/配置域。

    这条用例是 `pet/http_compat.py` 搬家的存在理由：视觉传输原语若还留在
    `pet.chat.providers`，导入它就会连带 `pet.chat.__init__`（Qt），这里会立刻红。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests: list = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):  # noqa: N802 - http.server 的接口名
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.headers.get("Authorization"), body))
            payload = json.dumps({"choices": [{"message": {"content": "probe-reply"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    report = tmp_path / "boundary.json"
    try:
        result = subprocess_run(["-c", _BOUNDARY_PROBE, endpoint, str(report)])
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["attempted"] == []
        assert data["loaded"] == []
        assert data["status"] == "ok"
        assert data["reply"] == "probe-reply"
        assert requests and requests[0][0] == "Bearer probe-key"
        assert requests[0][1]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def subprocess_run(args):
    import subprocess

    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        timeout=180,
    )
