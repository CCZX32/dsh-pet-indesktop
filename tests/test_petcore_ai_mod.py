"""AI 对话扩展：manifest、prompt 组装、流式回传、截图提问、无服务提示。"""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.config import Config
from petcore.contracts.screen import ScreenCapture
from petcore.mods.manifest import load_manifest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "ai.chat"


def _load_factory():
    path = MOD_DIR / "host" / "factory.py"
    spec = importlib.util.spec_from_file_location("ai_chat_factory", path)
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

    def open(self, owner, *, pet_slot=None, title=""):
        self.calls.append(("open", pet_slot, title))
        return True

    def append(self, owner, role, text, *, pet_slot=None):
        self.calls.append(("append", role, text))

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

    def capture(self, *, pet_slot=None):
        self.calls += 1
        return ScreenCapture(png=b"png-bytes", width=10, height=10, screen_name="fake")


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
        pets=FakePets(),
        presentation=FakePresentation(),
    )
    return SimpleNamespace(host=host, ports=ports)


@pytest.fixture()
def runtime(tmp_path: Path):
    module = _load_factory()
    context = _context(tmp_path)
    definition = module.create_host(context)
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
    module = _load_factory()
    definition = module.create_host(_context(tmp_path))
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


def test_screen_capture_sends_an_inline_png(runtime) -> None:
    runtime.screen_capture()
    chat = runtime.context.ports.chat
    assert chat.done_event.wait(5)
    assert runtime.context.ports.screen.calls == 1
    assert ("append", "user", "（截图提问）") in chat.calls
    request = runtime.context.ports.api.requests[0]
    content = request["messages"][-1]["content"]
    assert isinstance(content, list)
    image = next(item for item in content if item["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_missing_service_reports_instead_of_silently_failing(tmp_path: Path) -> None:
    module = _load_factory()
    context = _context(tmp_path, service=False)
    instance = module.create_host(context).runtime_factory(context)
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
