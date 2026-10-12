"""Cross-process catalog invalidation; package state remains in its own service.

Ported from the DLC branch `pet/mod_catalog.py`. The DLC monitor watched
``content/characters``; this topology has no ``content/`` tree, so the watch set
is derived from the character roots owned by :mod:`pet.catalog` (built-in
``assets/characters`` plus the external roots) instead.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from . import catalog as pet_catalog
from .feature_state_io import StateError, atomic_write, safe_path

_LOG = logging.getLogger(__name__)

REVISION_FILENAME = "mod-catalog.revision"

#: Directory under the data root that holds the live, catalog-visible copies.
LIVE_CHARACTERS_DIRNAME = "characters"


def default_character_roots() -> list[Path]:
    """Character roots a MOD change can appear in, in catalog resolution order."""
    roots = [pet_catalog.characters_dir()]
    roots.extend(pet_catalog.external_character_dirs())
    return roots


def catalog_watch_paths(data_root: Path | str, *, character_roots: Iterable[Path] | None = None) -> list[Path]:
    """Every path whose mtime change means "the offered MOD list may differ"."""
    root = Path(data_root)
    candidates = [root, root / LIVE_CHARACTERS_DIRNAME, root / REVISION_FILENAME]
    candidates.extend(default_character_roots() if character_roots is None else character_roots)
    seen: set[str] = set()
    paths: list[Path] = []
    for candidate in candidates:
        path = Path(candidate)
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def publish_catalog_change(data_root: Path) -> None:
    # A notification token only: no second ledger, paths, credentials or drafts.
    atomic_write(Path(data_root) / REVISION_FILENAME, uuid4().hex.encode("ascii"))


class ModCatalogMonitor(QObject):
    changed = Signal()

    def __init__(self, data_root: Path, parent=None, *, character_roots: Iterable[Path] | None = None):
        super().__init__(parent)
        self.root = Path(data_root)
        self.watch_paths = catalog_watch_paths(self.root, character_roots=character_roots)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.check)
        self.watcher.fileChanged.connect(self.check)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.check)
        self._stamp = None
        self._closed = False
        self.check()
        self.timer.start()

    def check(self, *_args):
        if self._closed:
            return
        stamp = []
        watch = []
        for path in self.watch_paths:
            try:
                safe_path(path)
                info = path.stat()
                stamp.append((str(path), info.st_mtime_ns, info.st_size))
                watch.append(str(path))
            except (OSError, ValueError, StateError):
                stamp.append((str(path), None, None))
        registered = set(self.watcher.files() + self.watcher.directories())
        missing = [path for path in watch if path not in registered]
        if missing:
            self.watcher.addPaths(missing)
        if stamp != self._stamp:
            self._stamp = stamp
            self.changed.emit()

    def close(self):
        self._closed = True
        self.timer.stop()
        paths = self.watcher.files() + self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)
