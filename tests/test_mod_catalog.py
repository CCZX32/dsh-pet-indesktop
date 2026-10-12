"""MOD catalog invalidation: a revision token plus change detection.

Ported from the DLC branch `pet/mod_catalog.py` blueprint. The DLC monitor
watched ``content/characters``; on this topology character packages live under
the roots owned by :mod:`pet.catalog` (built-in ``assets/characters`` plus the
external roots), so the watch set is derived from there instead.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pet import catalog
from pet.mod_catalog import ModCatalogMonitor, catalog_watch_paths, publish_catalog_change


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _package(root, character_id: str = "demo") -> None:
    videos = root / character_id / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    (videos / "idle.webm").write_bytes(b"video")


# ----------------------------------------------------------- revision token

def test_publish_catalog_change_writes_only_a_token(tmp_path):
    publish_catalog_change(tmp_path)
    token = tmp_path / "mod-catalog.revision"
    assert token.is_file()
    assert token.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mod-catalog.revision"]


def test_publish_catalog_change_advances_the_token(tmp_path):
    publish_catalog_change(tmp_path)
    first = (tmp_path / "mod-catalog.revision").read_bytes()
    publish_catalog_change(tmp_path)
    second = (tmp_path / "mod-catalog.revision").read_bytes()
    assert first != second


# ------------------------------------------------------------- watch paths

def test_catalog_watch_paths_cover_data_root_and_character_roots(tmp_path):
    roots = [tmp_path / "builtin", tmp_path / "external"]
    paths = catalog_watch_paths(tmp_path / "data", character_roots=roots)
    assert tmp_path / "data" in paths
    assert tmp_path / "data" / "characters" in paths
    assert tmp_path / "data" / "mod-catalog.revision" in paths
    for root in roots:
        assert root in paths


def test_catalog_watch_paths_are_deduplicated(tmp_path):
    data_root = tmp_path / "data"
    paths = catalog_watch_paths(data_root, character_roots=[data_root / "characters"])
    keys = [os.path.normcase(str(path)) for path in paths]
    assert len(keys) == len(set(keys))
    assert keys.count(os.path.normcase(str(data_root / "characters"))) == 1


def test_default_watch_paths_use_the_catalog_character_roots(tmp_path):
    paths = catalog_watch_paths(tmp_path / "data")
    assert catalog.characters_dir() in paths
    for root in catalog.external_character_dirs():
        assert root in paths


# ---------------------------------------------------------------- monitor

def test_monitor_emits_only_when_a_watched_root_changes(app, tmp_path):
    roots = [tmp_path / "characters"]
    monitor = ModCatalogMonitor(tmp_path / "data", character_roots=roots)
    seen = []
    monitor.changed.connect(lambda: seen.append(True))
    try:
        monitor.check()
        baseline = len(seen)
        monitor.check()
        assert len(seen) == baseline, "an unchanged tree must not re-emit"
        _package(roots[0])
        monitor.check()
        assert len(seen) > baseline
    finally:
        monitor.close()


def test_monitor_watches_a_root_that_appears_after_construction(app, tmp_path):
    roots = [tmp_path / "characters"]
    monitor = ModCatalogMonitor(tmp_path / "data", character_roots=roots)
    seen = []
    monitor.changed.connect(lambda: seen.append(True))
    try:
        monitor.check()
        before = len(seen)
        _package(roots[0], "late")
        monitor.check()
        assert len(seen) > before
        registered = set(monitor.watcher.directories()) | set(monitor.watcher.files())
        assert str(roots[0]) in registered
    finally:
        monitor.close()


def test_monitor_stops_emitting_and_releases_watches_after_close(app, tmp_path):
    roots = [tmp_path / "characters"]
    monitor = ModCatalogMonitor(tmp_path / "data", character_roots=roots)
    seen = []
    monitor.changed.connect(lambda: seen.append(True))
    monitor.check()
    monitor.close()
    assert not monitor.timer.isActive()
    before = len(seen)
    _package(roots[0])
    monitor.check()
    assert len(seen) == before, "a closed monitor must not emit"
    assert monitor.watcher.directories() == [] and monitor.watcher.files() == []


def test_monitor_tolerates_missing_watch_targets(app, tmp_path):
    missing = tmp_path / "absent"
    monitor = ModCatalogMonitor(tmp_path / "data", character_roots=[missing])
    seen = []
    monitor.changed.connect(lambda: seen.append(True))
    try:
        monitor.check()
        monitor.check()
        registered = {Path(path) for path in monitor.watcher.directories()}
        assert missing not in registered, "a missing root must not be registered"
        _package(missing, "later")
        monitor.check()
        assert seen
        assert missing in {Path(path) for path in monitor.watcher.directories()}
    finally:
        monitor.close()
