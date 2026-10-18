# -*- coding: utf-8 -*-
"""快捷启动包：结构/构建、宿主绑定、启动与设置、安装闭环。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import bind_quick_launch_context, register_feature_presentation
from pet.feature_management import LocalFeatureRuntime
from pet.feature_policy import official_package_verifier
from pet.official_features import QUICK_LAUNCH_FEATURE_ID
from pet.plugins.feature_host import FeatureHost
from pet.plugins.feature_packages import FeaturePackageLoader

app = QApplication.instance() or QApplication([])
OWNER = QUICK_LAUNCH_FEATURE_ID
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "features" / "quick-launch"


class MemoryVault:
    priority = 1

    def __init__(self):
        self.items = {}

    def set_password(self, service, ref, value):
        self.items[service, ref] = value

    def get_password(self, service, ref):
        return self.items.get((service, ref))

    def delete_password(self, service, ref):
        self.items.pop((service, ref), None)


class _Presentation:
    def __init__(self):
        self.bubbles = []

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append(text)

    def hold_bubble(self, seconds):
        pass

    def notify(self, title, message, on_click=None):
        pass


def _build(target: Path) -> Path:
    from scripts.build_quick_launch_package import build_package

    return build_package(PACKAGE_SOURCE, target)


def _load(built: Path):
    verifier = official_package_verifier(OWNER)
    descriptor = verifier.verify(built)
    return FeaturePackageLoader(verifier).load_host(descriptor)


def _import(handle, dotted: str):
    import importlib

    return importlib.import_module(handle.namespace + "." + dotted)


def _pump(predicate, *, timeout=5.0):
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
    built = _build(tmp_path / "built")
    manifest = json.loads((built / "manifest.json").read_text("utf-8"))
    assert manifest["execution_kind"] == "host-only"
    assert manifest["worker"] is None
    assert set(manifest["capabilities"]) == {"settings.contribute", "menu.contribute", "process.spawn"}
    assert built.with_suffix(".zip").is_file()


@pytest.fixture
def bound(tmp_path):
    built = _build(tmp_path / "pkg" / "built")
    handle = _load(built)
    host = FeatureHost()
    host.provide(handle.factory())
    return host, bind_quick_launch_context(Config(base=tmp_path)), handle


def test_launch_opens_the_configured_program(bound, tmp_path, monkeypatch):
    host, context, handle = bound
    target = tmp_path / "notepad.exe"
    target.write_bytes(b"stub")
    context.preferences.stage({"entries": [{"label": "记事本", "path": str(target)}]})
    assert context.preferences.flush()
    module = _import(handle, "host.runtime_mount")
    opened = []
    monkeypatch.setattr(module, "_open_path", lambda path: opened.append(path))
    provider = _Presentation()
    register_feature_presentation(lambda: provider)
    try:
        runtime = host.runtime(context)
        runtime.launch(0)
        assert _pump(lambda: provider.bubbles)
        assert opened == [str(target)]
        assert provider.bubbles[-1] == "已打开记事本"
    finally:
        register_feature_presentation(None)


def test_unconfigured_slot_and_missing_file_are_reported(bound, tmp_path):
    host, context, _handle = bound
    provider = _Presentation()
    register_feature_presentation(lambda: provider)
    try:
        runtime = host.runtime(context)
        runtime.launch(2)
        assert "还没有配置" in provider.bubbles[-1]
        context.preferences.stage({"entries": [{"label": "缺失", "path": str(tmp_path / "nope.exe")}]})
        assert context.preferences.flush()
        runtime.launch(0)
        assert _pump(lambda: len(provider.bubbles) >= 2)
        assert "找不到缺失" in provider.bubbles[-1]
    finally:
        register_feature_presentation(None)


def test_settings_round_trip(bound):
    _host, context, handle = bound
    panel = _import(handle, "host.contribution_settings").QuickLaunchSettings(context)
    try:
        assert panel.dirty() is False
        panel.entries.setPlainText("记事本|C:/Windows/notepad.exe\n计算器|C:/Windows/System32/calc.exe")
        assert panel.confirm_save() is True
        assert context.preferences.read()["entries"] == [
            {"label": "记事本", "path": "C:/Windows/notepad.exe"},
            {"label": "计算器", "path": "C:/Windows/System32/calc.exe"},
        ]
        assert panel.dirty() is False
    finally:
        panel.dispose()


def test_install_enable_uninstall_through_the_official_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: MemoryVault())
    runtime = LocalFeatureRuntime(Config(base=tmp_path), role="core")
    data = Config(base=tmp_path).dir / "feature-data" / OWNER
    try:
        assert OWNER in set(runtime.official_packages())
        built = _build(tmp_path / "pkg" / "install")
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
