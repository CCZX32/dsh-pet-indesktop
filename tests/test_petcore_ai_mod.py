"""AI 对话扩展：manifest、prompt 组装、流式回传、截图提问、无服务提示。"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.screen import ScreenCapture
from petcore.mods.feature import import_entrypoint
from petcore.mods.manifest import load_manifest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "ai.chat"


def _create_host(context):
    factory = import_entrypoint(MOD_DIR, "host/__init__.py:create_host", "ai.chat")
    return factory(context)


def _load_module(name: str):
    path = MOD_DIR / "host" / name
    spec = importlib.util.spec_from_file_location(f"ai_chat_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeChat:
    OWNER = "ai.chat"

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.done_event = threading.Event()
        self.history_messages: list[dict] = []
        self.submit_callback = None
        self.stop_callback = None
        self.records: list[tuple[str, str, int]] = []
        self.attachments: list[dict] = []

    def open(self, owner, *, pet_slot=None, title=""):
        self.calls.append(("open", pet_slot, title))
        return True

    def append(self, owner, role, text, *, pet_slot=None):
        self.calls.append(("append", role, text))

    def record(self, owner, role, text, *, pet_slot=None):
        self.records.append((role, text, pet_slot))

    def take_attachments(self, owner, *, pet_slot=None):
        pending, self.attachments = list(self.attachments), []
        return pending

    def token(self, owner, delta, *, pet_slot=None):
        self.calls.append(("token", delta))

    def done(self, owner, text="", *, pet_slot=None):
        self.calls.append(("done", text))
        self.done_event.set()

    def error(self, owner, reason, message="", *, pet_slot=None):
        self.calls.append(("error", reason, message))
        self.done_event.set()

    def history(self, owner, *, pet_slot=None):
        return list(self.history_messages)

    def on_submit(self, owner, callback):
        self.submit_callback = callback
        return lambda: None

    def on_stop(self, owner, callback):
        self.stop_callback = callback
        return lambda: None


class FakeApi:
    def __init__(self, service: bool = True) -> None:
        self.service = service
        self.requests: list[dict] = []

    def services(self):
        if not self.service:
            return []
        return [
            SimpleNamespace(
                service_id="svc", name="服务", model="chat-model", vision_model="vision-model"
            )
        ]

    def stream_chat(
        self,
        service_id,
        messages,
        *,
        model="",
        temperature=None,
        timeout=60.0,
        on_delta=None,
        cancel=None,
    ):
        self.requests.append(
            {
                "service_id": service_id,
                "messages": messages,
                "model": model,
                "temperature": temperature,
            }
        )
        if on_delta is not None:
            on_delta("答")
            on_delta("案")
        return SimpleNamespace(text="答案", chunks=2, cancelled=False)

    def open_settings(self):
        self.requests.append({"open_settings": True})


class FakeScreen:
    def __init__(self) -> None:
        self.calls = 0
        self.region_calls = 0

    def capture(self, *, pet_slot=None):
        self.calls += 1
        return ScreenCapture(
            png=b"png-bytes",
            width=10,
            height=10,
            screen_name="fake",
            app_info="code.exe | main.py",
        )

    def capture_region(self, *, pet_slot=None):
        self.region_calls += 1
        return ScreenCapture(png=b"region-png", width=8, height=6, screen_name="fake")

    def foreground_app(self):
        return "code.exe | main.py"


class FakeScreenAsk:
    def __init__(self) -> None:
        self.opened: list[tuple] = []
        self.callback = None

    def open(self, owner, capture, *, pet_slot=None, title=""):
        self.opened.append((owner, capture, pet_slot, title))
        return True

    def on_ask(self, owner, callback):
        self.callback = callback
        return lambda: None

    def history(self, owner, *, pet_slot=None):
        return []

    def is_open(self, owner, *, pet_slot=None):
        return bool(self.opened)

    def close(self, owner, *, pet_slot=None):
        return None


class FakePets:
    def active(self):
        return SimpleNamespace(slot=2)

    def primary(self):
        return SimpleNamespace(slot=0)


class FakePresentation:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text, **_kwargs):
        self.said.append(str(text))


class FakeConfig:
    """HostPorts.config 的测试实现（只读）。"""

    def __init__(self, config: Config) -> None:
        self._config = config

    def get(self, key, default=None):
        value = self._config.get(key, default)
        return default if value is None else value


class FakeScheduler:
    """立即执行版 scheduler；生产实现会排队到 GUI 线程。"""

    def __init__(self) -> None:
        self.calls = 0

    def call_later(self, delay_ms, callback):
        self.calls += 1
        callback()
        return f"timer-{self.calls}"


def _context(tmp_path: Path, *, service: bool = True):
    host = SimpleNamespace(
        config=Config(tmp_path),
        character_for=lambda character_id: SimpleNamespace(name="鲸鱼娘"),
    )
    host.config.set("character", "shen")
    ports = SimpleNamespace(
        api=FakeApi(service=service),
        chat=FakeChat(),
        screen=FakeScreen(),
        screen_ask=FakeScreenAsk(),
        pets=FakePets(),
        presentation=FakePresentation(),
        config=FakeConfig(host.config),
        scheduler=FakeScheduler(),
    )
    return SimpleNamespace(host=host, ports=ports)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_until(app, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture()
def runtime(tmp_path: Path):
    context = _context(tmp_path)
    definition = _create_host(context)
    instance = definition.runtime_factory(context)
    instance.start()
    yield instance
    instance.stop()


def test_manifest_is_a_host_only_feature_with_capabilities() -> None:
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest is not None
    assert manifest.id == "ai.chat"
    assert manifest.kind == "feature"
    assert manifest.execution == "host-only"
    assert "screenshot.capture" in manifest.capabilities
    assert "network.request" in manifest.capabilities


def test_definition_exposes_three_commands_and_a_settings_page(tmp_path: Path) -> None:
    definition = _create_host(_context(tmp_path))
    assert definition.owner == "ai.chat"
    assert [item.kind for item in definition.contributions] == ["settings_page"]
    instance = definition.runtime_factory(_context(tmp_path))
    assert set(instance.commands) == {"open", "look_screen", "screen_capture"}


def test_submit_sends_system_prompt_and_history(runtime) -> None:
    chat = runtime.context.ports.chat
    chat.history_messages = [
        {"role": "user", "content": "上一句"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "现在这句"},
    ]
    runtime._on_submit("现在这句", 2)
    assert chat.done_event.wait(5), "流式回调没有结束"
    request = runtime.context.ports.api.requests[0]
    assert request["service_id"] == "svc"
    messages = request["messages"]
    assert messages[0]["role"] == "system"
    assert "鲸鱼娘" in messages[0]["content"]
    assert [item["content"] for item in messages[1:]] == ["上一句", "上一答", "现在这句"]
    assert ("token", "答") in chat.calls and ("token", "案") in chat.calls
    assert ("done", "答案") in chat.calls


def test_open_creates_a_chat_window_for_the_active_pet(runtime) -> None:
    runtime.open_chat()
    chat = runtime.context.ports.chat
    assert chat.calls[0][0] == "open"
    assert chat.calls[0][1] == 2


def test_screen_capture_opens_the_region_ask_window(runtime) -> None:
    runtime.screen_capture(2)
    ask = runtime.context.ports.screen_ask
    screen = runtime.context.ports.screen
    assert screen.region_calls == 1
    assert ask.opened and ask.opened[0][1].png == b"region-png"
    assert ask.opened[0][2] == 2
    # 旧流程会自动把整屏图塞进主对话；新流程必须等用户在 ask 窗口里发问。
    assert runtime.context.ports.chat.calls == []


def test_ask_callback_sends_image_and_history(runtime) -> None:
    reply = runtime._on_ask(
        "这是什么？",
        b"region-png",
        [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "第一答"}],
        2,
    )
    assert reply == "答案"
    request = runtime.context.ports.api.requests[-1]
    messages = request["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["content"][0]["text"] == "第一问"
    assert messages[1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert messages[2] == {"role": "assistant", "content": "第一答"}
    assert messages[3]["content"] == "这是什么？"


def test_look_screen_replies_in_bubble_and_records_without_opening(
    qt_app, runtime
) -> None:
    runtime.look_screen(2)
    chat = runtime.context.ports.chat
    assert _wait_until(qt_app, lambda: len(chat.records) == 2)
    said = runtime.context.ports.presentation.said
    assert said[0] == "让我看看…"
    assert said[-1] == "答案"
    assert chat.records[0][0] == "user"
    assert "看看屏幕" in chat.records[0][1]
    assert "code.exe" in chat.records[0][1]
    assert chat.records[1] == ("assistant", "答案", 2)
    assert not [call for call in chat.calls if call[0] == "open"]


def test_look_screen_auto_open_toggle_opens_the_chat(qt_app, tmp_path: Path) -> None:
    context = _context(tmp_path)
    context.host.config.set("ai_look_screen_auto_open", True)
    instance = _create_host(context).runtime_factory(context)
    instance.start()
    instance.look_screen(2)
    chat = context.ports.chat
    assert _wait_until(qt_app, lambda: bool([c for c in chat.calls if c[0] == "open"]))
    assert [c for c in chat.calls if c[0] == "open"][0][1] == 2
    instance.stop()


def test_submit_includes_attachment_images(runtime) -> None:
    chat = runtime.context.ports.chat
    chat.attachments = [
        {
            "path": "a.png",
            "name": "a.png",
            "mime": "image/png",
            "text": None,
            "image_data_url": "data:image/png;base64,AAAA",
        }
    ]
    runtime._on_submit("看看这张图", 2)
    assert chat.done_event.wait(5)
    request = runtime.context.ports.api.requests[0]
    content = request["messages"][-1]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "看看这张图"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_submit_does_not_duplicate_the_current_user_turn(runtime) -> None:
    chat = runtime.context.ports.chat
    # controller 在回调前已把本轮问题追加进会话；mod 不能再发一遍同样的 user 消息。
    chat.history_messages = [
        {"role": "user", "content": "上一句"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "现在这句"},
    ]
    runtime._on_submit("现在这句", 2)
    assert chat.done_event.wait(5)
    messages = runtime.context.ports.api.requests[0]["messages"]
    user_turns = [item["content"] for item in messages if item["role"] == "user"]
    assert user_turns == ["上一句", "现在这句"]


def test_missing_service_reports_instead_of_silently_failing(tmp_path: Path) -> None:
    context = _context(tmp_path, service=False)
    instance = _create_host(context).runtime_factory(context)
    instance._on_submit("你好", 0)
    chat = context.ports.chat
    assert chat.done_event.wait(5), "无服务时必须给出明确错误"
    assert any(call[0] == "error" and call[1] == "no_service" for call in chat.calls)
    assert context.ports.presentation.said


def test_stop_sets_the_cancel_event(runtime) -> None:
    cancel = threading.Event()
    runtime._cancels[2] = cancel
    runtime._on_stop(2)
    assert cancel.is_set()


def test_ai_keys_survive_config_reload(tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("ai_vision_enabled", False)
    config.set("ai_temperature", 1.3)
    config.set("ai_look_screen_auto_open", True)
    config.save()
    reloaded = Config.load(tmp_path)
    assert reloaded.get("ai_vision_enabled") is False
    assert reloaded.get("ai_temperature") == 1.3
    assert reloaded.get("ai_look_screen_auto_open") is True


def test_manifest_uses_a_package_entrypoint() -> None:
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest is not None
    assert manifest.entrypoint == "host/__init__.py:create_host"


def test_runtime_module_is_qt_and_network_free() -> None:
    runtime_text = (MOD_DIR / "host" / "runtime.py").read_text(encoding="utf-8")
    for needle in ("PySide6", "petcore.net", "petcore.api", "host.config"):
        assert needle not in runtime_text, f"runtime.py 不应出现 {needle}"
    settings_text = (MOD_DIR / "host" / "settings_page.py").read_text(encoding="utf-8")
    assert "PySide6" in settings_text, "设置页是受信 UI，允许使用 Qt"


def test_prompt_builders_keep_history_shapes() -> None:
    prompts = _load_module("prompts.py")
    chat = prompts.chat_messages(
        "sys",
        [
            {"role": "user", "content": "上一句"},
            {"role": "assistant", "content": "上一答"},
            {"role": "user", "content": "现在这句"},
        ],
        "现在这句",
        ["data:image/png;base64,AAAA"],
    )
    assert chat[0] == {"role": "system", "content": "sys"}
    assert chat[1] == {"role": "user", "content": "上一句"}
    assert chat[2] == {"role": "assistant", "content": "上一答"}
    assert chat[3]["content"][0] == {"type": "text", "text": "现在这句"}
    assert chat[3]["content"][1]["image_url"]["url"].endswith("AAAA")

    ask = prompts.ask_messages(
        "sys", [{"role": "user", "content": "第一问"}], "第二问", "data:image/png;base64,BBBB"
    )
    assert ask[1]["content"][0]["text"] == "第一问"
    assert ask[1]["content"][1]["image_url"]["url"].endswith("BBBB")
    assert ask[2] == {"role": "user", "content": "第二问"}


def test_settings_page_exposes_chat_appearance_and_previews(qt_app, tmp_path: Path) -> None:
    context = _context(tmp_path)
    definition = _create_host(context)

    class AppearanceChat:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def apply_appearance(self, **kwargs):
            self.calls.append(dict(kwargs))

    host = SimpleNamespace(
        config=Config(tmp_path),
        features=SimpleNamespace(ports=SimpleNamespace(api=FakeApi())),
        chat=AppearanceChat(),
    )
    page = definition.settings_factory(host)
    try:
        values = [
            page.background_combo.itemData(index)
            for index in range(page.background_combo.count())
        ]
        assert "builtin:whale" in values
        assert "__custom__" in values

        index = page.background_combo.findData("builtin:whale")
        page.background_combo.setCurrentIndex(index)
        assert host.config.get("chat_background") == "builtin:whale"

        page.accent_edit.setText("#FF8800")
        page._on_accent_finished()
        assert host.config.get("chat_accent") == "#ff8800"

        page.follow_check.setChecked(True)
        page.on_top_check.setChecked(True)
        assert host.config.get("chat_follow_pet") is True
        assert host.config.get("chat_always_on_top") is True
        assert host.chat.calls, "设置改动必须实时预览到对话窗"
        assert host.chat.calls[-1]["background"] == "builtin:whale"
        assert host.chat.calls[-1]["accent"] == "#ff8800"
        assert host.chat.calls[-1]["follow"] is True
        assert host.chat.calls[-1]["always_on_top"] is True

        page.accent_edit.setText("不是颜色")
        page._on_accent_finished()
        assert host.config.get("chat_accent") == "#ff8800"
    finally:
        page.close()
