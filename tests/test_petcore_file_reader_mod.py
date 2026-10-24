"""tool.file-reader：扫描预算、有界读取、拖放运行时与设置页（P4-a）。"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.contracts.host import HostPorts
from petcore.mods import feature as feature_mod
from petcore.mods.manifest import load_manifest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "tool.file-reader"
HOST_PKG = "petcore_file_reader_test_host"


def _host_package():
    if HOST_PKG in sys.modules:
        return sys.modules[HOST_PKG]
    spec = importlib.util.spec_from_file_location(
        HOST_PKG,
        MOD_DIR / "host" / "__init__.py",
        submodule_search_locations=[str(MOD_DIR / "host")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[HOST_PKG] = module
    spec.loader.exec_module(module)
    return module


_host_package()
reader = importlib.import_module(f"{HOST_PKG}.reader")
runtime_mod = importlib.import_module(f"{HOST_PKG}.runtime")


class _Presentation:
    def __init__(self):
        self.said = []

    def say(self, text, *, duration_ms=4000, force=False):
        self.said.append(text)

    def show_image(self, *args, **kwargs):
        return False

    def play_animation(self, name):
        return False

    def play_event(self, group, variant=None):
        return False

    def notify(self, *args, **kwargs):
        return None


class _Config(dict):
    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return dict.get(self, key, default)


class _Chat:
    def __init__(self):
        self.records = []

    def record(self, owner, role, text, *, pet_slot=None):
        self.records.append((owner, role, text))


class _Api:
    def __init__(self, text="这是摘要。"):
        self.text = text
        self.calls = []

    def services(self):
        return [SimpleNamespace(service_id="deepseek")]

    def stream_chat(self, service_id, messages, **kwargs):
        self.calls.append((service_id, messages))
        return SimpleNamespace(text=self.text)


class _Interaction:
    def __init__(self):
        self.callbacks = {}

    def on_drop(self, owner, callback):
        self.callbacks[owner] = callback
        return lambda: self.callbacks.pop(owner, None)


def _context(config=None, *, api=None, chat=None, interaction=None):
    presentation = _Presentation()
    ports = HostPorts(
        presentation=presentation,
        config=_Config(config or {}),
        api=api,
        chat=chat,
        interaction=interaction or _Interaction(),
    )
    return SimpleNamespace(ports=ports), presentation


# ---------------------------------------------------------------- 纯逻辑


def test_collect_skips_dirs_and_binaries(tmp_path):
    text = tmp_path / "a.md"
    text.write_text("hello", encoding="utf-8")
    binary = tmp_path / "b.bin"
    binary.write_bytes(b"\x00\x01")
    folder = tmp_path / "sub"
    folder.mkdir()

    files = reader.collect_interpretable([text, binary, folder, text])

    assert files == [text]


def test_collect_honours_budget(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"f{index}.txt"
        path.write_text("x", encoding="utf-8")
        paths.append(path)

    budget = reader.ScanBudget(limit=2, seconds=60.0)
    files = reader.collect_interpretable(paths, budget)

    assert files == paths[:2]
    assert budget.truncated is True


def test_extract_text_is_bounded_and_reports_skips(tmp_path):
    short = tmp_path / "short.txt"
    short.write_text("abcdef", encoding="utf-8")
    long = tmp_path / "long.txt"
    long.write_text("x" * 100, encoding="utf-8")

    content, skipped = reader.extract_text([short, long], max_chars=10)

    assert "abcdef" in content
    assert "已截断" in content
    assert skipped == []


def test_extract_text_skips_unreadable(tmp_path):
    missing = tmp_path / "gone.txt"
    content, skipped = reader.extract_text([missing])

    assert content == ""
    assert skipped == ["gone.txt"]


def test_build_user_text_mentions_names_and_instruction():
    text = reader.build_user_text("BODY", ["a.txt"], ["b.txt"], budget_truncated=True)

    assert "a.txt" in text and "b.txt" in text
    assert reader.INSTRUCTION in text
    assert "只扫描了前一部分" in text


def test_summarize_is_single_line_and_short():
    assert reader.summarize("a\nb   c") == "a b c"
    assert reader.summarize("x" * 500).endswith("…")
    assert len(reader.summarize("x" * 500)) == 180


# ---------------------------------------------------------------- 运行时


def test_start_subscribes_to_drop_and_stop_unsubscribes():
    interaction = _Interaction()
    context, _ = _context(interaction=interaction)
    runtime = runtime_mod.FileReaderRuntime(context)

    runtime.start()
    assert runtime_mod.OWNER in interaction.callbacks
    runtime.stop()
    assert interaction.callbacks == {}


def test_disabled_runtime_ignores_drops(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hi", encoding="utf-8")
    context, presentation = _context({"file_reader_enabled": False})
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.on_drop([path])

    assert presentation.said == []


def test_non_text_drop_explains_why(tmp_path):
    binary = tmp_path / "a.bin"
    binary.write_bytes(b"\x00")
    context, presentation = _context()
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.on_drop([binary])

    assert presentation.said[-1] == reader.NO_TEXT_HINT


def test_drop_without_api_service_asks_for_configuration(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hi", encoding="utf-8")
    context, presentation = _context()
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.on_drop([path])

    assert presentation.said[-1] == reader.NO_SERVICE_HINT
    assert runtime._busy is False


def test_drop_interpretation_reports_bubble_and_records(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("project notes", encoding="utf-8")
    api = _Api("这是一个说明文件。")
    chat = _Chat()
    context, presentation = _context({"ai_service": "deepseek"}, api=api, chat=chat)
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.on_drop([path])
    runtime._threads[0].join(5)

    assert api.calls[0][0] == "deepseek"
    assert "【文件：a.txt】" in api.calls[0][1][0]["content"]
    assert presentation.said[-1] == "这是一个说明文件。"
    assert [role for _, role, _ in chat.records] == ["user", "assistant"]
    assert runtime._busy is False


def test_failure_is_visible_in_bubble(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hi", encoding="utf-8")

    class _Failing:
        def services(self):
            return [SimpleNamespace(service_id="deepseek")]

        def stream_chat(self, *args, **kwargs):
            raise RuntimeError("网络不可达")

    context, presentation = _context(api=_Failing())
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.on_drop([path])
    runtime._threads[0].join(5)

    assert presentation.said[-1] == "网络不可达"


def test_read_last_without_history_explains(tmp_path):
    context, presentation = _context()
    runtime = runtime_mod.FileReaderRuntime(context)
    runtime.read_last()

    assert "还没有拖过文件" in presentation.said[-1]


# ---------------------------------------------------------------- 设置页 / 清单


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Host:
    def __init__(self, config):
        self.config = _Config(config)


def test_settings_page_round_trips(app):
    manager = feature_mod.FeatureManager(HostPorts())
    manifest, _ = load_manifest(MOD_DIR)
    manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    page_class = manager.settings_pages()[0].factory
    host = _Host({"file_reader_enabled": True, "file_reader_progress_seconds": 15})
    page = page_class(host)

    page.progress.setValue(30)
    assert host.config["file_reader_progress_seconds"] == 30
    assert page.dirty() is True

    page.confirm_save()
    assert page.dirty() is False

    page.record.setChecked(False)
    page.discard_changes()
    assert page.record.isChecked() is True


def test_mod_manifest_and_contributions_load():
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest.id == "tool.file-reader"
    assert "files.read" in manifest.capabilities
    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    assert diagnostics == []
    assert manager.settings_pages()


@pytest.mark.parametrize("failure", [False, True])
def test_stop_discards_queued_result(app, tmp_path, failure):
    from dataclasses import replace
    from PySide6.QtCore import QEventLoop, QTimer
    from petcore.ui.ports import QtScheduler

    scheduler = QtScheduler()
    class Api(_Api):
        def stream_chat(self, *args, **kwargs):
            if failure:
                raise RuntimeError("offline")
            return super().stream_chat(*args, **kwargs)

    chat = _Chat()
    context, presentation = _context(api=Api(), chat=chat)
    context.ports = replace(context.ports, scheduler=scheduler)
    runtime = runtime_mod.FileReaderRuntime(context)
    path = tmp_path / "input.txt"
    path.write_text("notes", encoding="utf-8")
    runtime.on_drop([path])
    runtime._threads[-1].join(10)
    assert not runtime._threads[-1].is_alive()
    before = list(presentation.said)
    runtime.stop()
    loop = QEventLoop()
    delivered = []
    scheduler.call_later(0, lambda: (delivered.append(True), loop.quit()))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(10000)
    loop.exec()
    timeout.stop()
    assert delivered
    assert presentation.said == before
    assert chat.records == []


def test_stop_cancels_request_and_refuses_overlap(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    cancellations = []

    class Api(_Api):
        def stream_chat(self, *args, **kwargs):
            cancellations.append(kwargs.get("cancel"))
            entered.set()
            assert release.wait(10)
            return SimpleNamespace(text="late")

    context, presentation = _context(api=Api())
    runtime = runtime_mod.FileReaderRuntime(context)
    path = tmp_path / "input.txt"
    path.write_text("notes", encoding="utf-8")
    try:
        runtime.on_drop([path])
        assert entered.wait(10)
        runtime.stop()
        assert cancellations[0] is not None and cancellations[0].is_set()
        runtime.start()
        runtime.on_drop([path])
        assert len(runtime._threads) == 1
    finally:
        runtime.stop()
        release.set()
        for thread in runtime._threads:
            thread.join(10)
    assert "late" not in presentation.said


def test_repeated_requests_prune_finished_workers(tmp_path):
    context, _ = _context(api=_Api())
    runtime = runtime_mod.FileReaderRuntime(context)
    path = tmp_path / "input.txt"
    path.write_text("notes", encoding="utf-8")
    for _ in range(30):
        runtime.on_drop([path])
        assert len(runtime._threads) == 1
        runtime._threads[0].join(10)
        assert not runtime._threads[0].is_alive()
    runtime.stop()
