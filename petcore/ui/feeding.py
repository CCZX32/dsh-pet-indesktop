"""拖文件投喂：统计、吃动画与气泡反馈；绝不删除或移动文件。"""

from __future__ import annotations

import json
import os
import time
import random
from pathlib import Path

from ..engine.feeding import (
    STATS_FILE_NAME,
    STATS_HISTORY_LIMIT,
    format_bytes,
    measure_paths,
    pick_eating_animation,
)


def _default_stats() -> dict:
    return {
        "feed_count": 0,
        "file_count": 0,
        "folder_count": 0,
        "item_count": 0,
        "total_bytes": 0,
        "history": [],
    }


class FeedingController:
    def __init__(self, window, *, rng=None) -> None:
        self.window = window
        self._rng = rng or random
        self.stats_path = Path(window.config.root) / STATS_FILE_NAME

    def _paths(self, mime) -> list[Path]:
        if mime is None or not mime.hasUrls():
            return []
        return [
            Path(url.toLocalFile())
            for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile()
        ]

    def accepts(self, event) -> bool:
        if not bool(self.window.config.get("file_feeding_enabled", True)):
            return False
        paths = self._paths(event.mimeData())
        if not paths:
            return False
        return not self.window.is_transparent_at(event.position().toPoint())

    def handle_drag_enter(self, event) -> None:
        if self.accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def handle_drop(self, event) -> dict | None:
        if not self.accepts(event):
            event.ignore()
            return None
        paths = self._paths(event.mimeData())
        result = self.eat_paths(paths)
        event.acceptProposedAction()
        return result

    def eat_paths(self, paths) -> dict:
        report = measure_paths(paths)
        stats = self._record(report)
        names = [spec.name for spec in (self.window.character.animations if self.window.character else ())]
        animation = pick_eating_animation(names, rng=self._rng)
        if animation is not None:
            self.window.play_animation(animation)
        text = f"吃掉了 {report.files} 个文件、{report.folders} 个文件夹（{format_bytes(report.total_bytes)}）"
        if report.truncated:
            text += "，文件太多，只统计了一部分"
        self.window.say(f"{text}。放心，只是做个样子，文件没有删除或移动哦。", 5200)
        return {
            "files": report.files,
            "folders": report.folders,
            "bytes": report.total_bytes,
            "stats": stats,
            "truncated": report.truncated,
            "scanned": report.scanned,
        }

    def _load_stats(self) -> dict:
        try:
            raw = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _default_stats()
        stats = _default_stats()
        if isinstance(raw, dict):
            for key in ("feed_count", "file_count", "folder_count", "item_count", "total_bytes"):
                try:
                    stats[key] = int(raw.get(key, 0))
                except (TypeError, ValueError):
                    stats[key] = 0
            history = raw.get("history")
            if isinstance(history, list):
                stats["history"] = history[-STATS_HISTORY_LIMIT:]
        return stats

    def _record(self, report) -> dict:
        stats = self._load_stats()
        stats["feed_count"] += 1
        stats["file_count"] += report.files
        stats["folder_count"] += report.folders
        stats["item_count"] += report.files + report.folders
        stats["total_bytes"] += report.total_bytes
        stats["history"].append(
            {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": report.files,
                "folders": report.folders,
                "bytes": report.total_bytes,
            }
        )
        stats["history"] = stats["history"][-STATS_HISTORY_LIMIT:]
        self._save_stats(stats)
        return stats

    def _save_stats(self, stats: dict) -> None:
        tmp = None
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.stats_path.with_name(f"{self.stats_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.stats_path)
        except OSError:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
