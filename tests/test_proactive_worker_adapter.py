# -*- coding: utf-8 -*-
"""宿主侧识屏传输适配器 + watcher 的 worker 路由 + 状态可见性。

蓝本 = DLC 分支的 ``tests/test_proactive_worker_lifecycle.py``（适配器/真进程部分）
与 ``provider`` 载荷边界用例，按本仓库宿主面重写。

三组：

1. **适配器**：配置白名单、待答请求、故障时把在飞请求如实失败、状态快照；
2. **watcher 路由**：worker 模式下派发走适配器、故障时**不**回退进程内、
   显式切换执行位置时收口；
3. **状态如实可见**：快照落盘 / 损坏容错 / 设置页那一行显示的文案。

时序纪律：真进程部分用事件循环有界轮询；其余是纯逻辑，不涉时序。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

# QApplication 必须先于任何 QObject/QTimer 存在（见 tests/test_proactive_worker.py 的说明）。
_APP = QApplication.instance() or QApplication([])

ROOT = Path(__file__).resolve().parents[1]
WORKER_ID = "proactive-screen"
CAPABILITIES = ("foreground.read", "screenshot.capture", "vision.request", "logging.write")


# ------------------------------------------------------------------ 载荷边界

def _adapter(**kwargs):
    from pet.workers.proactive_screen_adapter import ProactiveScreenWorkerAdapter

    kwargs.setdefault("mode", "in_process")  # 默认不拉真进程；要真进程的用例显式覆盖
    return ProactiveScreenWorkerAdapter(**kwargs)


def test_provider_payload_keeps_only_the_transferable_fields():
    from pet.chat.models import ProviderConfig

    provider = ProviderConfig("openai-main")
    provider.base_url = "https://vision.invalid"
    provider.model = "chat-model"
    provider.api_key = "chat-key"
    provider.vision_same_as_chat = True
    provider.web_search = object()  # 运行时注入的联网设置，不该上管道
    payload = _adapter()._provider_payload(provider)
    assert payload["base_url"] == "https://vision.invalid"
    assert payload["api_key"] == "chat-key"
    assert payload["vision_same_as_chat"] is True
    # 聊天域自己的字段与钥匙串指针一个都不下发。
    for forbidden in ("provider_id", "web_search", "api_key_ref", "vision_api_key_ref", "thinking"):
        assert forbidden not in payload


def test_provider_payload_resolves_the_independent_vision_key_in_the_host(monkeypatch):
    """独立视觉端点的钥匙串解析留在**宿主**：子进程只收明文，不收 ref。"""
    from pet import vision
    from pet.chat.models import ProviderConfig

    provider = ProviderConfig("openai-main")
    provider.vision_same_as_chat = False
    provider.api_key = "chat-key"
    provider.vision_api_key_ref = "provider/openai-main/vision"
    provider.vision_api_key = ""

    class _Store:
        def get(self, ref):
            assert ref == "provider/openai-main/vision"
            return "vision-key-from-keyring"

    monkeypatch.setattr("pet.chat.models.SecretStore", _Store)
    payload = _adapter()._provider_payload(provider)
    assert payload["vision_api_key"] == "vision-key-from-keyring"
    assert "vision_api_key_ref" not in payload
    # 独立端点绝不允许回退到聊天 Key。
    assert payload["api_key"] == "chat-key"  # 字段在，但 worker 侧按 vision_same_as_chat 选钥匙
    restored = vision.VisionRequestConfig.from_dict(payload)
    assert (restored.api_key if restored.vision_same_as_chat else restored.vision_api_key) == "vision-key-from-keyring"


def test_provider_payload_rejects_a_non_mapping_provider():
    with pytest.raises(TypeError):
        _adapter()._provider_payload(object())


def test_config_sanitizer_drops_credentials_and_unknown_keys():
    sanitized = _adapter()._sanitize_config(
        {
            "max_edge": 768,
            "jpeg_quality": 80,
            "frame_ttl": 10,
            "platform": "windows",
            "api_key": "must-not-be-config",
            "provider": {"api_key": "must-not-be-config"},
        }
    )
    assert sanitized == {"max_edge": 768, "jpeg_quality": 80, "frame_ttl": 10, "platform": "windows"}


# -------------------------------------------------------------------- 适配器

def test_an_in_process_adapter_never_spawns_or_sends():
    adapter = _adapter()
    assert adapter.start({"max_edge": 640}) is False
    assert adapter.observe_foreground(1) is None
    assert adapter.capture_foreground({"hwnd": 1, "pid": 2}, 1) is None
    assert adapter.manual_look({"api_key": "k"}, "sys", generation=1) is None
    assert adapter.ready is False
    assert adapter.active is False
    adapter.stop()


def test_pending_requests_fail_visibly_when_the_worker_goes_away():
    adapter = _adapter(mode="auto")
    failures: list = []
    adapter.request_failed.connect(lambda operation, payload: failures.append((operation, payload)))
    # 直接把内部状态摆成"有一个在飞请求"，再触发故障收口。
    from pet.workers.proactive_screen_adapter import _PendingRequest

    adapter._pending["req-1"] = _PendingRequest("analyze_frame", 4, "automatic", time.monotonic() + 60)
    adapter._on_failed("worker crashed")
    assert failures == [
        (
            "analyze_frame",
            {
                "request_id": "req-1",
                "operation": "analyze_frame",
                "generation": 4,
                "status": "error",
                "error_code": "worker_unavailable",
                "message": "识屏任务已结束，请重试",
                "retryable": True,
            },
        )
    ]
    assert adapter._pending == {}


def test_status_snapshot_reports_mode_state_and_a_hint():
    adapter = _adapter()
    snapshot = adapter.status_snapshot()
    assert snapshot["mode"] == "in_process"
    assert snapshot["state"] == adapter.state
    assert snapshot["pending"] == 0
    from pet.proactive_worker_status import describe

    value, hint = describe(snapshot)
    assert value == "进程内执行"
    assert hint


def test_diagnostics_are_whitelisted_before_they_reach_the_ui():
    adapter = _adapter()
    seen: list = []
    adapter.diagnostic.connect(lambda stage, detail: seen.append((stage, detail)))
    adapter._on_diagnostic(
        "launch_rejected",
        {
            "code": "worker_launch_failed",
            "reason": "worker launch rejected",
            "exit_code": 2,
            "generation": 1,
            "line": "Traceback ... File 'C:\\Users\\secret\\pet\\x.py', line 3, in <module>",
            "token": "must-not-surface",
            "path": "C:\\Users\\secret",
        },
    )
    assert seen and seen[0][0] == "launch_rejected"
    detail = seen[0][1]
    assert detail["code"] == "worker_launch_failed"
    assert detail["exit_code"] == 2
    assert "token" not in detail and "path" not in detail
    assert "secret" not in json.dumps(detail, ensure_ascii=False)


# ----------------------------------------------------- 真进程（默认命令行）

def _wait_until(predicate, *, timeout: float = 90.0) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

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


def test_adapter_drives_the_real_worker_over_the_default_command():
    adapter = _adapter(mode="auto", budget_checker=lambda _kind, _generation: True)
    observations: list = []
    adapter.observation_ready.connect(observations.append)
    try:
        assert adapter.supervisor.arguments == ["-m", "pet", "--worker", WORKER_ID]
        assert adapter.start({"max_edge": 768, "jpeg_quality": 80, "frame_ttl": 10, "platform": "windows"})
        assert _wait_until(lambda: adapter.ready), adapter.state
        assert adapter.supervisor._config == {"max_edge": 768, "jpeg_quality": 80, "frame_ttl": 10, "platform": "windows"}
        request_id = adapter.observe_foreground(11)
        assert request_id
        assert _wait_until(lambda: bool(observations))
        envelope = observations[0]
        assert envelope["request_id"] == request_id
        assert envelope["generation"] == 11
        assert envelope["status"] == "ok"
        assert "api_key" not in json.dumps(envelope, ensure_ascii=False)
        snapshot = adapter.status_snapshot()
        assert snapshot["state"] == "ready"
        assert snapshot["mode"] == "auto"
    finally:
        adapter.stop()
        assert _wait_until(lambda: adapter.state == "stopped", timeout=30.0)
    assert adapter.supervisor.process is None


# --------------------------------------------------------- watcher 路由（假适配器）

class _FakeAdapter:
    """记录调用序列的适配器替身：本组只验**路由**，真 worker 由上面那组负责。"""

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.active = True
        self.state = "ready" if ready else "starting"
        self.calls: list[tuple] = []
        self.released: list[str] = []
        self.started: list[dict] = []
        self.stopped = 0

    def start(self, config=None):
        self.started.append(dict(config or {}))
        return True

    def configure(self, config=None):
        return True

    def stop(self):
        self.stopped += 1

    def capture_foreground(self, window, generation):
        self.calls.append(("capture_foreground", dict(window), generation))
        return f"cap-{len(self.calls)}"

    def analyze_frame(self, frame_id, provider, system_prompt, **kwargs):
        self.calls.append(("analyze_frame", frame_id, system_prompt, kwargs))
        return f"ana-{len(self.calls)}"

    def release_frame(self, frame_id, generation=None):
        self.released.append(frame_id)
        return "rel"

    def status_snapshot(self):
        return {"mode": "auto", "state": self.state, "generation": 0, "pending": 0, "last_stage": "", "last_detail": {}, "hint": ""}


class _DummyWindow:
    on_open_chat = True

    def __init__(self) -> None:
        self.mouse_through = False
        self._dragging = False
        self._physics_mode = None
        self._click_effect_phase = 0
        self.bubbles: list[str] = []

    def isVisible(self) -> bool:
        return True

    def show_bubble(self, text, duration_ms=3000):
        self.bubbles.append(text)

    def hold_bubble(self, seconds):
        return None


def _watcher(tmp_path, monkeypatch, *, execution: str = "worker"):
    from pet.config import Config
    from pet.proactive import ProactiveScreenWatcher

    monkeypatch.setattr(sys, "platform", "win32")
    cfg = Config(base=tmp_path)
    cfg.set(
        "proactive_screen",
        {
            "enabled": True,
            "whitelist": ["code.exe"],
            "execution": execution,
            "pre_cue": True,
        },
    )
    win = _DummyWindow()
    watcher = ProactiveScreenWatcher(win, cfg)
    return cfg, win, watcher


def _patch_foreground(monkeypatch, hwnd: int = 42, pid: int = 7):
    from pet import vision

    info = {"hwnd": hwnd, "pid": pid, "process": "code.exe", "title": "fixture", "rect": [0, 0, 100, 80]}
    monkeypatch.setattr(vision, "foreground_window_info", lambda: dict(info))
    return info


def _arm_tick(watcher, info):
    """把 G3/G4 前提摆好：同一窗口、停留时长达标、频控放行。"""
    watcher._current_hwnd = info["hwnd"]
    watcher._entered_ts = time.time() - 600
    watcher._worker_busy = False
    watcher._request_in_flight = False


def test_watcher_dispatch_goes_through_the_worker_in_worker_mode(tmp_path, monkeypatch):
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    info = _patch_foreground(monkeypatch)
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    _arm_tick(watcher, info)
    watcher._on_tick()
    assert fake.calls == [("capture_foreground", {"hwnd": 42, "pid": 7}, watcher._generation)]
    assert watcher._worker_busy is True


def test_watcher_does_not_fall_back_to_the_in_process_pipeline_on_fault(tmp_path, monkeypatch):
    """worker 坏了就停派发——不许悄悄改走进程内（两套行为同时活着才是坑）。"""
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    info = _patch_foreground(monkeypatch)
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    in_process: list = []
    monkeypatch.setattr(watcher, "_worker_capture", lambda *a, **k: in_process.append(1))
    watcher._on_worker_failed("worker crashed")
    assert watcher._worker_fault == "worker crashed"
    assert watcher._execution_mode == "worker", "故障不许改执行位置"
    _arm_tick(watcher, info)
    watcher._on_tick()
    assert fake.calls == []
    assert in_process == []


def test_watcher_resumes_after_the_worker_restarts(tmp_path, monkeypatch):
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    info = _patch_foreground(monkeypatch)
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher._on_worker_failed("worker crashed")
    assert watcher._worker_fault
    watcher._on_worker_state_changed("ready")  # 重启阶梯把 worker 拉回来了
    assert watcher._worker_fault == ""
    _arm_tick(watcher, info)
    watcher._on_tick()
    assert len(fake.calls) == 1


def test_switching_execution_mode_is_the_only_thing_that_clears_a_fault(tmp_path, monkeypatch):
    cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher._on_worker_failed("worker crashed")
    cfg.set("proactive_screen", {"enabled": True, "whitelist": ["code.exe"], "execution": "in_process"})
    watcher.apply_config()
    assert watcher._execution_mode == "in_process"
    assert watcher._worker_fault == ""
    assert fake.stopped == 1


def test_watcher_configures_the_worker_with_the_in_process_encoding_parameters(tmp_path, monkeypatch):
    """执行位置换到 worker 不许悄悄改变发给模型的图（max_edge/quality 逐字对齐）。"""
    from pet import vision

    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    config = watcher._worker_config()
    assert config["max_edge"] == int(vision.MAX_EDGE)
    assert config["jpeg_quality"] == 70


def test_capture_ready_routes_to_analysis_and_releases_the_frame(tmp_path, monkeypatch):
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher._on_worker_capture_ready(
        {"generation": watcher._generation, "result": {"frame_id": "f2", "dhash": 9, "window": {"hwnd": 42, "process": "code.exe", "title": "t"}}}
    )
    assert len(fake.calls) == 1
    operation, frame_id, prompt, kwargs = fake.calls[0]
    assert (operation, frame_id) == ("analyze_frame", "f2")
    assert kwargs["generation"] == watcher._generation
    assert watcher._worker_busy is False
    assert watcher._request_in_flight is True


def test_capture_ready_in_dry_run_stamps_but_releases_without_asking_the_model(tmp_path, monkeypatch):
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher.limiter.dry_run = True
    watcher._on_worker_capture_ready(
        {"generation": watcher._generation, "result": {"frame_id": "f1", "dhash": 7, "window": {"hwnd": 42, "process": "code.exe", "title": "t"}}}
    )
    assert fake.calls == []
    assert fake.released == ["f1"]
    assert watcher._last_dhash == 7


def test_analysis_ready_bubbles_counts_and_syncs_without_the_window_title(tmp_path, monkeypatch):
    cfg, win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    synced: list = []
    watcher._on_reply_synced = lambda user_text, reply: synced.append((user_text, reply))
    watcher._request_in_flight = True
    watcher._on_worker_analysis_ready(
        {
            "generation": watcher._generation,
            "result": {
                "reply": "看到你在写代码呢",
                "window": {"hwnd": 42, "process": "code.exe", "title": "机密文档.docx"},
            },
        }
    )
    assert win.bubbles == ["看到你在写代码呢"]
    assert watcher._request_in_flight is False
    assert synced and "机密文档.docx" not in synced[0][0]
    assert synced[0][1] == "看到你在写代码呢"
    assert watcher.memory.latest().get("process") == "code.exe"
    title_line = json.dumps(watcher.memory.latest(), ensure_ascii=False)
    assert "机密文档.docx" not in title_line
    assert cfg.dir.exists()


def test_a_stale_worker_response_is_dropped_by_generation(tmp_path, monkeypatch):
    _cfg, win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    stale = watcher._generation - 1
    watcher._on_worker_capture_ready(
        {"generation": stale, "result": {"frame_id": "f1", "dhash": 1, "window": {}}}
    )
    assert fake.calls == []
    watcher._on_worker_analysis_ready({"generation": stale, "result": {"reply": "迟到"}})
    assert win.bubbles == []


def test_a_worker_vision_failure_counts_toward_the_circuit_breaker(tmp_path, monkeypatch):
    """模型侧失败照旧计入熔断（连续 3 次）。"""
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    for _ in range(3):
        watcher._on_worker_request_failed(
            "analyze_frame", {"error_code": "vision_rate_limited", "generation": watcher._generation}
        )
    assert watcher.limiter.allow() == (False, "paused_by_circuit_breaker")


def test_a_worker_outage_is_not_counted_as_a_model_failure(tmp_path, monkeypatch):
    """worker 自己没了不算模型的错：不占熔断额度，也不冒泡成"模型失败"。"""
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    ok, reason = watcher.limiter.allow()
    assert ok is True, reason
    for _ in range(4):
        watcher._on_worker_request_failed(
            "analyze_frame", {"error_code": "worker_unavailable", "generation": watcher._generation}
        )
    assert watcher.limiter.allow()[1] != "paused_by_circuit_breaker"


def test_shutdown_stops_the_worker_and_is_idempotent(tmp_path, monkeypatch):
    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher.shutdown()
    watcher.shutdown()
    assert fake.stopped == 2
    assert watcher.is_running() is False


# --------------------------------------------------------- 状态可见性（设置页）

def test_status_file_round_trip_and_bounded_write(tmp_path):
    from pet.proactive_worker_status import read_status, status_path, write_status

    assert read_status(tmp_path) == {}
    assert write_status(tmp_path, {"mode": "auto", "state": "ready"}) is True
    snapshot = read_status(tmp_path)
    assert snapshot["mode"] == "auto"
    assert "updated_at" in snapshot
    # 超限写入被拒（诊断信息不值得撑爆配置目录）
    assert write_status(tmp_path, {"mode": "auto", "blob": "x" * 9000}) is False
    assert read_status(tmp_path)["state"] == "ready"
    status_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert read_status(tmp_path) == {}


def test_status_description_covers_every_state_truthfully():
    from pet.proactive_worker_status import describe

    assert describe({})[0].startswith("未知")
    assert describe({"mode": "in_process"})[0] == "进程内执行"
    assert describe({"mode": "disabled"})[0] == "已关闭"
    assert describe({"mode": "auto", "state": "ready"})[0] == "worker 子进程（就绪）"
    assert describe({"mode": "auto", "state": "handshaking"})[0] == "worker 子进程（启动中）"
    assert describe({"mode": "auto", "state": "crashed"})[0] == "worker 崩溃，等待重启"
    value, hint = describe({"mode": "auto", "state": "fault", "last_reason": "worker crashed"})
    assert value == "worker 故障，识屏已停止"
    assert "进程内" in hint
    value, hint = describe({"mode": "auto", "state": "fault", "hint": "识屏 Worker 未能启动；…"})
    assert "识屏 Worker 未能启动" in hint


def test_worker_mode_resolution_defaults_to_the_subprocess():
    from pet.proactive_worker_status import worker_mode

    assert worker_mode({}) == "worker"
    assert worker_mode({"execution": "in_process"}) == "in_process"
    assert worker_mode({"execution": "WORKER"}) == "worker"
    assert worker_mode({"execution": "nonsense"}) == "worker"
    assert worker_mode(None) == "worker"


def test_watcher_publishes_the_status_snapshot_to_disk(tmp_path, monkeypatch):
    from pet.proactive_worker_status import read_status

    _cfg, _win, watcher = _watcher(tmp_path, monkeypatch, execution="worker")
    fake = _FakeAdapter()
    watcher._worker_adapter = fake
    watcher.publish_worker_status()
    assert read_status(watcher.cfg.dir)["state"] == "ready"
    watcher._on_worker_failed("worker crashed")
    snapshot = read_status(watcher.cfg.dir)
    assert snapshot["state"] == "fault"
    assert snapshot["last_reason"] == "worker crashed"
    assert snapshot["execution"] == "worker"


def test_settings_row_shows_the_worker_state_and_the_fallback_mode(tmp_path, monkeypatch):
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow
    from pet.proactive_worker_status import write_status

    monkeypatch.setattr(sys, "platform", "win32")
    config = Config(base=tmp_path)
    write_status(config.dir, {"mode": "auto", "state": "ready"})
    dialog = ModernSettingsDialog(config, include_ai=True)
    try:
        row = dialog.findChild(SettingRow, "settingRow_proactive_worker_status")
        assert row is not None
        assert "worker 子进程" in dialog.pro_worker_status_label.text()
        # 用户在页面上切到进程内：状态行立刻反映"打算改成什么"，不留假象。
        dialog.pro_execution_select.setCurrentIndex(1)
        assert dialog.pro_execution_select.currentData() == "in_process"
        assert "进程内执行" in dialog.pro_worker_status_label.text()
        # 切回 worker：读回落盘的真实状态（此时仍是 ready）
        dialog.pro_execution_select.setCurrentIndex(0)
        assert "worker 子进程" in dialog.pro_worker_status_label.text()
    finally:
        dialog.close()


def test_settings_row_shows_a_fault_without_pretending_it_recovered(tmp_path, monkeypatch):
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.proactive_worker_status import write_status

    monkeypatch.setattr(sys, "platform", "win32")
    config = Config(base=tmp_path)
    write_status(config.dir, {"mode": "auto", "state": "fault", "last_reason": "worker crashed"})
    dialog = ModernSettingsDialog(config, include_ai=True)
    try:
        text = dialog.pro_worker_status_label.text()
        assert "worker 故障，识屏已停止" in text
        assert "不会静默改用进程内执行" in text
    finally:
        dialog.close()


def test_settings_page_saves_the_execution_choice(tmp_path, monkeypatch):
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    monkeypatch.setattr(sys, "platform", "win32")
    config = Config(base=tmp_path)
    dialog = ModernSettingsDialog(config, include_ai=True)
    try:
        dialog.pro_execution_select.setCurrentIndex(1)
        assert dialog._write_config() is True
    finally:
        dialog.close()
    reloaded = Config(base=tmp_path)
    assert reloaded.get("proactive_screen", {}).get("execution") == "in_process"


# ------------------------------------------------ 全链路（真 worker + 本地视觉端点）

_CHAIN_CHILD = r'''
import sys
from PIL import Image
from pet import vision

# 只替换 OS 边界（截图/前台窗口），其余全走生产路径：白名单分流、协议、
# dHash、额度反向请求、视觉 HTTP。
vision.foreground_window_info = lambda: {
    "hwnd": 42, "pid": 7, "process": "code.exe", "title": "fixture", "rect": [0, 0, 100, 80]
}
vision.capture_window_rect = lambda rect: Image.new("RGB", (100, 80), "navy")

from pet.workers.worker_entry import main
raise SystemExit(main("proactive-screen"))
'''


def test_full_chain_watcher_through_the_real_worker_to_a_local_vision_endpoint(tmp_path, monkeypatch):
    """生产链路端到端：watcher（策略/限流/冒泡）→ 适配器 → 真 worker 子进程 →
    本地视觉端点。**只**替换 OS 边界（前台窗口/截图）与模型端点。

    这是"识屏真的在子进程里跑"的唯一直接证据：宿主进程里没有任何截图代码被调用，
    模型请求由子进程发出（HTTP 服务端在宿主进程，能看见 Authorization 与图片载荷）。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from pet.config import Config
    from pet.proactive import ProactiveScreenWatcher
    from pet.workers.proactive_screen_adapter import ProactiveScreenWorkerAdapter

    requests: list = []
    served = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):  # noqa: N802 - http.server 的接口名
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.headers.get("Authorization"), body))
            served.set()
            payload = json.dumps({"choices": [{"message": {"content": "看见你在改代码"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

    monkeypatch.setattr(sys, "platform", "win32")
    config = Config(base=tmp_path)
    config.set(
        "proactive_screen",
        {"enabled": True, "whitelist": ["code.exe"], "execution": "worker", "pre_cue": True},
    )
    provider = config.data["chat"]["providers"]["openai-main"]
    provider["base_url"] = endpoint
    provider["model"] = "fixture-vision"
    provider["vision_same_as_chat"] = True
    provider["api_key_ref"] = ""  # 不查钥匙串：本用例验的是"宿主把钥匙喂给子进程"这条链
    provider["api_key"] = "chain-key"
    config.data["chat"]["active_provider"] = "openai-main"

    info = _patch_foreground(monkeypatch)
    win = _DummyWindow()
    watcher = ProactiveScreenWatcher(win, config)
    adapter = ProactiveScreenWorkerAdapter(
        program=sys.executable,
        arguments=["-c", _CHAIN_CHILD],
        budget_checker=lambda kind, generation: watcher.limiter.consume_budget(),
    )
    # 注入的是「另一条命令行的适配器」，接线逐字走生产代码（不绕过 _attach_*）。
    watcher._attach_worker_adapter(adapter)
    try:
        watcher.apply_config()
        assert _wait_until(lambda: adapter.ready), adapter.state
        _arm_tick(watcher, info)
        watcher._on_tick()
        assert _wait_until(lambda: served.is_set() and bool(win.bubbles)), (
            f"链路未跑通：state={adapter.state} mode={watcher._execution_mode} "
            f"busy={watcher._worker_busy} inflight={watcher._request_in_flight} "
            f"fault={watcher._worker_fault!r} dhash={watcher._last_dhash} "
            f"snap={adapter.status_snapshot()} bubbles={win.bubbles} requests={len(requests)}"
        )
    finally:
        watcher.shutdown()
        _wait_until(lambda: adapter.state == "stopped", timeout=30.0)
        server.shutdown()
        server.server_close()
        thread.join(5)

    assert requests, "子进程没有发出视觉请求"
    authorization, body = requests[0]
    assert authorization == "Bearer chain-key"
    url = body["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert body["model"] == "fixture-vision"
    assert win.bubbles == ["让我看看……", "看见你在改代码"], "先兆提示 + 模型答复各一条"
    assert adapter.supervisor.process is None


def test_app_exit_path_drains_workers_after_the_main_loop():
    """生产退出路径必须接上收口泵：`app.exec()` 之后、对象析构之前。

    源码级守卫（与 tests/test_architecture.py 同族）：真跑一次整只桌宠的退出
    不适合放进单测，而"接线在不在、在不在正确的位置"是纯结构问题。行为侧由
    tests/test_workers_lifecycle.py 的 `finish_app_shutdown` 用例负责。
    """
    source = (ROOT / "pet" / "app.py").read_text(encoding="utf-8")
    call = "WorkerSupervisor.finish_app_shutdown()"
    assert call in source, "退出路径没有接 WorkerSupervisor.finish_app_shutdown()"
    assert source.index(call) > source.index("return app.exec()"), "收口泵必须在主事件循环之后"
    assert source.index(call) < source.index("overlay_gate.release()", source.index("return app.exec()")), (
        "收口泵必须早于进程门释放（还在收尾时第二实例不得起来）"
    )
