"""tool.ocr：本地优先的 OCR 扩展（引擎路径、阅读顺序、回退口径）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD_DIR = ROOT / "examples" / "petcore-mods" / "tool.ocr"


def _load_package():
    import sys
    import types

    name = "tool_ocr_under_test"
    package = types.ModuleType(name)
    package.__path__ = [str(MOD_DIR / "host")]
    sys.modules[name] = package
    return importlib.import_module(f"{name}.runtime"), importlib.import_module(
        f"{name}.engine"
    )


runtime_module, engine = _load_package()


class Resources:
    def __init__(self, base: Path) -> None:
        self.base = base

    def bundle_path(self, *parts):
        return self.base.joinpath(*parts)


def _ports(base: Path | None = None, screen_ask=None):
    return SimpleNamespace(
        resources=Resources(base or ROOT),
        screen_ask=screen_ask,
    )


# ---------------------------------------------------------------- 引擎判据


def test_model_problem_reports_missing_files(tmp_path: Path) -> None:
    assert "不存在" in engine.model_problem(tmp_path / "nope")
    assert "缺失" in engine.model_problem(tmp_path)
    for name in engine.MODEL_FILES.values():
        (tmp_path / name).write_bytes(b"onnx")
    assert engine.model_problem(tmp_path) == ""


def test_available_needs_the_engine_and_the_models(tmp_path: Path) -> None:
    ports = _ports()
    assert engine.available(ports) is (importlib.util.find_spec("rapidocr") is not None)

    for name in engine.MODEL_FILES.values():
        (tmp_path / name).write_bytes(b"onnx")
    ports = SimpleNamespace(resources=SimpleNamespace(bundle_path=lambda *p: tmp_path))
    assert engine.available(ports) is (importlib.util.find_spec("rapidocr") is not None)


def test_model_dir_comes_from_the_resources_port() -> None:
    assert engine.model_dir(_ports()).name == "rapidocr_models"
    assert engine.model_dir(SimpleNamespace()) is None


# ---------------------------------------------------------------- 阅读顺序


def test_reading_text_orders_lines_top_down_and_words_left_to_right() -> None:
    blocks = [
        ("world", 120.0, 10.0, 40.0, 12.0),
        ("hello", 20.0, 10.0, 40.0, 12.0),
        ("second", 20.0, 40.0, 60.0, 12.0),
        ("third", 20.0, 70.0, 50.0, 12.0),
    ]
    assert engine.reading_text(blocks) == "hello world\nsecond\nthird"


def test_reading_text_of_empty_blocks_is_empty() -> None:
    assert engine.reading_text([]) == ""


# ---------------------------------------------------------------- 运行时


class FakeScreenAsk:
    def __init__(self) -> None:
        self.registered: list[tuple] = []

    def on_action(self, owner, callback, *, priority=100, actions=()):
        self.registered.append((owner, callback, priority, actions))
        return lambda: None


def test_runtime_registers_as_the_local_ocr_handler() -> None:
    ask = FakeScreenAsk()
    runtime = runtime_module.OcrRuntime(
        SimpleNamespace(ports=_ports(screen_ask=ask))
    )
    runtime.start()
    assert len(ask.registered) == 1
    owner, _callback, priority, actions = ask.registered[0]
    assert owner == "tool.ocr"
    assert priority == 10
    assert actions == ("ocr",)


def test_runtime_declines_other_actions_and_missing_engine(monkeypatch) -> None:
    runtime = runtime_module.OcrRuntime(SimpleNamespace(ports=_ports()))
    assert runtime._on_action("translate", "", b"png", 0) == ""

    monkeypatch.setattr(engine, "available", lambda _ports: False)
    assert runtime._on_action("ocr", "", b"png", 0) == ""


def test_runtime_returns_local_text_and_swallows_engine_errors(monkeypatch) -> None:
    ports = _ports()
    runtime = runtime_module.OcrRuntime(SimpleNamespace(ports=ports))
    monkeypatch.setattr(engine, "available", lambda _ports: True)
    monkeypatch.setattr(engine, "recognize", lambda _png, _ports: "本地文字\n第二行")
    assert runtime._on_action("ocr", "", b"png", 0) == "本地文字\n第二行"

    def boom(_png, _ports):
        raise engine.OcrUnavailable("模型坏了")

    monkeypatch.setattr(engine, "recognize", boom)
    assert runtime._on_action("ocr", "", b"png", 0) == ""


# ---------------------------------------------------------------- 真实引擎


@pytest.mark.skipif(
    importlib.util.find_spec("rapidocr") is None, reason="rapidocr not installed"
)
def test_real_engine_recognizes_generated_text(tmp_path: Path) -> None:
    import cv2
    import numpy as np

    image = np.full((200, 900, 3), 255, np.uint8)
    cv2.putText(
        image,
        "HELLO 123",
        (40, 140),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.5,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", image)
    assert ok

    engine.release_engine()
    text = engine.recognize(encoded.tobytes(), _ports())
    assert "HELLO" in text.upper()
    assert "123" in text
