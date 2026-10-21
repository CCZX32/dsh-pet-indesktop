"""拖文件投喂的纯逻辑：统计预算、字节格式化、吃动画选择。"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

STATS_FILE_NAME = "file_eaten_stats.json"
STATS_HISTORY_LIMIT = 50
SCAN_FILE_LIMIT = 20000
SCAN_TIME_BUDGET_S = 2.0

EAT_KEYWORDS = ("吃", "eat", "啃")
PREFERRED_EAT_ANIMATIONS = ("吃Token", "大口吃零食", "偷吃零食被抓住")


@dataclass(frozen=True)
class FeedingResult:
    files: int
    folders: int
    total_bytes: int
    truncated: bool
    scanned: int


class ScanBudget:
    def __init__(self, *, file_limit: int = SCAN_FILE_LIMIT, seconds: float = SCAN_TIME_BUDGET_S, clock=None):
        self.file_limit = max(1, int(file_limit))
        self.seconds = max(0.0, float(seconds))
        self._clock = clock if callable(clock) else time.monotonic
        self._started = self._clock()
        self.files = 0
        self.folders = 0
        self.scanned = 0
        self.truncated = False

    def expired(self) -> bool:
        return self._clock() - self._started >= self.seconds

    def account_file(self) -> bool:
        if self.files >= self.file_limit or self.expired():
            self.truncated = True
            return False
        self.files += 1
        self.scanned += 1
        return True

    def account_folder(self) -> bool:
        if self.expired():
            self.truncated = True
            return False
        self.folders += 1
        self.scanned += 1
        return True


def format_bytes(size: int) -> str:
    size = max(0, int(size))
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.1f} GB"


def _measure_path(path: Path, budget: ScanBudget) -> tuple[int, int, int]:
    total = 0
    files = 0
    folders = 0
    try:
        if path.is_file():
            if not budget.account_file():
                return 0, 0, 0
            total += path.stat().st_size
            return 1, 0, total
        if not path.is_dir():
            return 0, 0, 0
    except OSError:
        return 0, 0, 0

    for root, _dirs, names in os.walk(path):
        if not budget.account_folder():
            break
        folders += 1
        for name in names:
            if not budget.account_file():
                break
            try:
                total += (Path(root) / name).stat().st_size
                files += 1
            except OSError:
                continue
        if budget.truncated:
            break
    return files, folders, total


def measure_paths(paths, *, budget: ScanBudget | None = None) -> FeedingResult:
    budget = budget or ScanBudget()
    files = folders = total = 0
    for raw in paths or ():
        path = Path(raw)
        found_files, found_folders, found_bytes = _measure_path(path, budget)
        files += found_files
        folders += found_folders
        total += found_bytes
        if budget.truncated:
            break
    return FeedingResult(files, folders, total, budget.truncated, budget.scanned)


def pick_eating_animation(names, *, rng: random.Random | None = None) -> str | None:
    """优先精确偏好名，其次包含吃/啃关键词的名字。"""
    candidates = [str(name) for name in names or ()]
    if not candidates:
        return None
    for preferred in PREFERRED_EAT_ANIMATIONS:
        if preferred in candidates:
            return preferred
    matched = [name for name in candidates if any(keyword in name.lower() for keyword in EAT_KEYWORDS)]
    if not matched:
        return None
    randomizer = rng or random
    return randomizer.choice(matched)
