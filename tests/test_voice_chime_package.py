# -*- coding: utf-8 -*-
"""语音报时包：调度纯函数、结构/构建、宿主绑定、音频提交与安装闭环。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import bind_voice_context, register_feature_audio, register_feature_presentation
from pet.feature_management import LocalFeatureRuntime
from pet.plugins.feature_host import FeatureHost
from tests.voice_chime_package_fakes import OWNER, PACKAGE_SOURCE, MemoryVault, build_package, import_pkg, load_host

app = QApplication.instance() or QApplication([])


class _Audio:
    def __init__(self):
        self.spoken = []
        self.stopped = 0

    def speak(self, text):
        self.spoken.append(text)
        return True

    def stop(self):
        self.stopped += 1


class _Presentation:
    def __init__(self):
        self.bubbles = []

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append(text)

    def hold_bubble(self, seconds):
        pass

    def notify(self, title, message, on_click=None):
        pass


def _pump(predicate, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def test_schedule_math_and_quote_rotation():
    # 直接按包源码导入纯函数（不依赖 Qt）。
    import importlib.util
    from pathlib import Path

    path = PACKAGE_SOURCE / "host" / "schedule.py"
    spec = importlib.util.spec_from_file_location("voice_schedule_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    now = datetime(2026, 10, 18, 10, 17, 30)
    assert 0 < module.seconds_until_next(now, "hourly", ()) <= 60 * 43
    assert module.seconds_until_next(now, "every_30", ()) == pytest.approx(12 * 60 + 30)
    assert module.seconds_until_next(now, "custom", ["10:20"]) == pytest.approx(2 * 60 + 30)
    assert module.clean_schedule("nonsense") == "hourly"
    assert module.parse_custom_times(["8:00", "25:00", "bad"]) == ((8, 0),)
    assert "10 点 17 分" in module.clock_sentence(now)
    assert module.pick_quote(now, "a\nb", "c") in {"a", "b", "c"}


def test_structure_and_build_manifest(tmp_path):
    mod = json.loads((PACKAGE_SOURCE / "mod.json").read_text("utf-8-sig"))
    assert mod["id"] == OWNER
    assert mod["execution_kind"] == "host-only"
    assert (PACKAGE_SOURCE / "host" / "factory.py").is_file()
    for path in (PACKAGE_SOURCE / "host").rglob("*.py"):
        text = path.read_text("utf-8")
        for needle in ("pet.voice_chime", "pet.tts", "pet.config", "pet.app"):
            assert needle not in text, f"{path.name} imports {needle}"

    built = build_package(tmp_path / "built")
    manifest = json.loads((built / "manifest.json").read_text("utf-8"))
    assert manifest["execution_kind"] == "host-only"
    assert manifest["worker"] is None
    assert set(manifest["capabilities"]) == {"settings.contribute", "menu.contribute", "audio.speak"}
    assert built.with_suffix(".zip").is_file()


@pytest.fixture
def bound(tmp_path):
    built = build_package(tmp_path / "pkg" / "built")
    _loader, _descriptor, handle = load_host(built)
    host = FeatureHost()
    host.provide(handle.factory())
    context = bind_voice_context(Config(base=tmp_path))
    return host, context, handle


def test_manual_chime_submits_text_to_core_audio_and_bubble(bound):
    host, context, handle = bound
    audio = _Audio()
    presentation = _Presentation()
    register_feature_audio(lambda: audio)
    register_feature_presentation(lambda: presentation)
    try:
        runtime = host.runtime(context)
        runtime.speak_now()
        assert len(audio.spoken) == 1
        assert "现在是" in audio.spoken[0]
        assert presentation.bubbles == audio.spoken
    finally:
        register_feature_audio(None)
        register_feature_presentation(None)


def test_timer_starts_and_stops_with_the_runtime(bound):
    host, context, _handle = bound
    context.preferences.stage({"enabled": True, "schedule": "every_minute"})
    assert context.preferences.flush()
    runtime = host.runtime(context)
    runtime.start()
    assert runtime._timer is not None and runtime._timer.isActive()
    runtime.stop()
    assert runtime._timer is None
    runtime.start()
    runtime.close()
    assert runtime._timer is None
    assert context.scheduler._closed is True


def test_settings_round_trip(bound):
    _host, context, handle = bound
    panel = import_pkg(handle, "host.contribution_settings").VoiceChimeSettings(context)
    try:
        assert panel.dirty() is False
        panel.enabled.setChecked(True)
        panel.schedule.setCurrentIndex(panel.schedule.findData("custom"))
        panel.custom_times.setText("08:00, 12:30")
        panel.quotes_zh.setPlainText("喝口水\n休息一下")
        assert panel.confirm_save() is True
        values = context.preferences.read()
        assert values["enabled"] is True
        assert values["schedule"] == "custom"
        assert values["custom_times"] == ["08:00", "12:30"]
        assert values["quotes_zh"] == "喝口水\n休息一下"
    finally:
        panel.dispose()


def test_install_enable_uninstall_through_the_official_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    data = Config(base=tmp_path).dir / "feature-data" / OWNER
    try:
        assert OWNER in set(runtime.official_packages())
        built = build_package(tmp_path / "pkg" / "install")
        manager, accepted = runtime.install_official(OWNER, built, enabled=True)
        assert accepted is True
        assert _pump(lambda: not manager.busy, timeout=30)
        assert manager.service.inspect().active == "1.0.0"
        assert runtime.host.enabled(OWNER) is True
        assert OWNER in runtime.menu_owners()

        assert runtime.uninstall_official(OWNER) is True
        assert _pump(lambda: not manager.busy, timeout=30)
        assert manager.service.inspect().active is None
        assert data.is_dir()
    finally:
        runtime.close()
