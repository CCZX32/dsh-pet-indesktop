# -*- coding: utf-8 -*-
"""音乐启动器包：结构、构建、宿主绑定、生命周期与安装闭环。"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.feature_host_bindings import bind_music_context, register_feature_presentation
from pet.feature_management import LocalFeatureRuntime
from pet.plugins.feature_host import FeatureHost
from tests.music_package_fakes import OWNER, PACKAGE_SOURCE, MemoryVault, build_package, import_pkg, load_host

app = QApplication.instance() or QApplication([])


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


def test_structure_declares_the_host_only_contract():
    mod = json.loads((PACKAGE_SOURCE / "mod.json").read_text("utf-8-sig"))
    assert mod["id"] == OWNER
    assert mod["execution_kind"] == "host-only"
    assert mod["factory"] == "music/v1"
    assert (PACKAGE_SOURCE / "host" / "factory.py").is_file()
    for path in (PACKAGE_SOURCE / "host").rglob("*.py"):
        text = path.read_text("utf-8")
        for needle in ("pet.music_players", "pet.now_playing", "pet.music_lyric", "pet.config", "pet.app"):
            assert needle not in text, f"{path.name} imports {needle}"


def test_build_manifest_is_host_only_and_inventory_is_complete(tmp_path):
    built = build_package(tmp_path / "built")
    manifest = json.loads((built / "manifest.json").read_text("utf-8"))
    assert manifest["id"] == OWNER
    assert manifest["execution_kind"] == "host-only"
    assert manifest["worker"] is None
    assert set(manifest["capabilities"]) == {"settings.contribute", "menu.contribute", "process.spawn"}
    assert "host/factory.py" in manifest["files"]
    assert built.with_suffix(".zip").is_file()


@pytest.fixture
def bound(tmp_path):
    built = build_package(tmp_path / "pkg" / "built")
    _loader, _descriptor, handle = load_host(built)
    host = FeatureHost()
    host.provide(handle.factory())
    context = bind_music_context(Config(base=tmp_path))
    return host, context, handle


def test_definition_has_four_commands_and_menu_contributions(bound):
    _host, context, handle = bound
    definition = handle.factory()
    assert [c.command for c in definition.menus] == ["netease", "qqmusic", "kugou", "soda"]
    runtime = handle.factory().runtime_factory(context)
    assert set(runtime.commands) == {"netease", "qqmusic", "kugou", "soda"}


def test_launch_reports_success_and_missing_player(bound, monkeypatch):
    host, context, handle = bound
    module = import_pkg(handle, "host.runtime_mount")
    provider = _Presentation()
    register_feature_presentation(lambda: provider)
    try:
        opened = []
        monkeypatch.setattr(module, "find_player", lambda key, manual="": "C:/CloudMusic/cloudmusic.exe")
        monkeypatch.setattr(module, "_open_path", lambda path: opened.append(path))
        runtime = host.runtime(context)
        runtime.launch("netease")
        assert _pump(lambda: provider.bubbles), "成功气泡没有出现"
        assert opened == ["C:/CloudMusic/cloudmusic.exe"]
        assert provider.bubbles[-1] == "已打开网易云音乐"

        monkeypatch.setattr(module, "find_player", lambda key, manual="": None)
        runtime.launch("qqmusic")
        assert _pump(lambda: len(provider.bubbles) >= 2)
        assert "找不到QQ音乐" in provider.bubbles[-1]
    finally:
        register_feature_presentation(None)


def test_settings_persist_manual_paths(bound):
    _host, context, handle = bound
    panel = import_pkg(handle, "host.contribution_settings").MusicSettings(context)
    try:
        assert panel.dirty() is False
        panel._fields["netease"].setText("D:/CloudMusic/cloudmusic.exe")
        assert panel.dirty() is True
        assert panel.confirm_save() is True
        values = context.preferences.read()
        assert values["player_paths"] == {"netease": "D:/CloudMusic/cloudmusic.exe"}
        assert panel.dirty() is False
        panel._fields["netease"].setText("")
        assert panel.discard_changes() is True
        assert panel._fields["netease"].text() == "D:/CloudMusic/cloudmusic.exe"
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
