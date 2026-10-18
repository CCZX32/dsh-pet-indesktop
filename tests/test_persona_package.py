# -*- coding: utf-8 -*-
"""日常台词包：结构/构建、宿主绑定、朗读开关、设置与安装闭环。"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import bind_persona_context, register_feature_audio, register_feature_presentation
from pet.feature_management import LocalFeatureRuntime
from pet.plugins.feature_host import FeatureHost
from tests.persona_package_fakes import OWNER, PACKAGE_SOURCE, MemoryVault, build_package, import_pkg, load_host

app = QApplication.instance() or QApplication([])


class _Audio:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)
        return True

    def stop(self):
        pass


class _Presentation:
    def __init__(self):
        self.bubbles = []

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append(text)

    def hold_bubble(self, seconds):
        pass

    def notify(self, title, message, on_click=None):
        pass


def _pump(predicate, *, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def test_structure_and_build_manifest(tmp_path):
    mod = json.loads((PACKAGE_SOURCE / "mod.json").read_text("utf-8-sig"))
    assert mod["id"] == OWNER
    assert mod["execution_kind"] == "host-only"
    for path in (PACKAGE_SOURCE / "host").rglob("*.py"):
        text = path.read_text("utf-8")
        for needle in ("pet.persona_phrases", "pet.config", "pet.app"):
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
    context = bind_persona_context(Config(base=tmp_path))
    return host, context, handle


def test_today_shows_a_phrase_and_respects_the_speak_switch(bound):
    host, context, _handle = bound
    audio = _Audio()
    presentation = _Presentation()
    register_feature_audio(lambda: audio)
    register_feature_presentation(lambda: presentation)
    try:
        runtime = host.runtime(context)
        runtime.today()
        assert presentation.bubbles
        assert not audio.spoken

        context.preferences.stage({"speak": True})
        assert context.preferences.flush()
        runtime.today()
        assert audio.spoken == presentation.bubbles[-1:]
    finally:
        register_feature_audio(None)
        register_feature_presentation(None)


def test_custom_phrases_replace_the_builtin_pool(bound):
    host, context, _handle = bound
    context.preferences.stage({"custom_phrases": "只有这一句"})
    assert context.preferences.flush()
    presentation = _Presentation()
    register_feature_presentation(lambda: presentation)
    try:
        host.runtime(context).today()
        assert presentation.bubbles == ["只有这一句"]
    finally:
        register_feature_presentation(None)


def test_settings_round_trip(bound):
    _host, context, handle = bound
    panel = import_pkg(handle, "host.contribution_settings").PersonaSettings(context)
    try:
        assert panel.dirty() is False
        panel.phrases.setPlainText("一\n二")
        panel.speak.setChecked(True)
        assert panel.confirm_save() is True
        values = context.preferences.read()
        assert values == {"custom_phrases": "一\n二", "speak": True}
        assert panel.dirty() is False
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
        assert _pump(lambda: not manager.busy)
        assert manager.service.inspect().active == "1.0.0"
        assert runtime.host.enabled(OWNER) is True
        assert OWNER in runtime.menu_owners()

        assert runtime.uninstall_official(OWNER) is True
        assert _pump(lambda: not manager.busy)
        assert manager.service.inspect().active is None
        assert data.is_dir()
    finally:
        runtime.close()
