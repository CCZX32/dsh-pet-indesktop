# -*- coding: utf-8 -*-
"""“吃垃圾文件”模拟功能：拖文件给桌宠后播放吃动画并记录统计。

重要边界：本模块只做视觉反馈与统计，绝不删除/移动/修改被拖入的文件。
统计写到配置目录下的 file_eaten_stats.json，供用户查看累计吃了多少文件。
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtCore import QUrl

STATS_FILE_NAME = "file_eaten_stats.json"
STATS_HISTORY_LIMIT = 50

# 投喂气泡的副标题（两条投喂链共用；拖文件只是做样子）。
FEEDING_BUBBLE_SUBTITLE = "放心，只是做个样子，文件没有删除或移动哦"

# 投喂扫描预算（B03 + 复审#4）：拖入大目录（几万文件/网络盘）时同步递归 + 逐项
# ``stat()`` 会把整个桌宠 UI 冻在 GUI 线程上。两条预算：**文件数**上限 + **墙钟**上限。
#
# 记账粒度是「项」= 文件 + 目录（``_ScanBudget.visited``）：只数文件的话，空目录树
# 一个文件都不统计（既不耗文件预算、也走不到耗时检查），慢盘上"文件少但每层目录都卡"
# 的树在两次检查之间也不受控——进一个新目录就查一次钟，任何形态的树都有墙钟封顶。
# 触预算即停扫，统计与气泡如实标记截断（截断提示报的是**文件**口径，未变）。
SCAN_FILE_LIMIT = 20000       # 已统计文件数上限（目录不计入，由墙钟兜底）
SCAN_TIME_BUDGET_S = 2.0
SCAN_TIME_CHECK_EVERY = 256   # 每 N 项（文件 + 目录）查一次钟
# 预算时钟（测试注入假钟；生产 = 单调钟）
_SCAN_CLOCK = time.monotonic

# 吃动画候选关键词；找不到时使用普通随机动作兜底。
EAT_KEYWORDS = ("吃", "eat", "啃")
# 如果角色恰好有这些更贴近“吃文件/吃数字垃圾”的动画，优先播放。
PREFERRED_EAT_ANIMATIONS = ("吃Token", "大口吃零食", "偷吃零食被抓住")


def _default_stats() -> dict:
    return {
        "feed_count": 0,
        "file_count": 0,
        "folder_count": 0,
        "item_count": 0,
        "total_bytes": 0,
        "history": [],
    }


def _load_stats(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_stats()
    if not isinstance(raw, dict):
        return _default_stats()
    stats = _default_stats()
    for key in ("feed_count", "file_count", "folder_count", "item_count", "total_bytes"):
        try:
            stats[key] = int(raw.get(key, 0))
        except (TypeError, ValueError):
            stats[key] = 0
    history = raw.get("history")
    if isinstance(history, list):
        stats["history"] = history[-STATS_HISTORY_LIMIT:]
    return stats


def _save_stats(path: Path, stats: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        # 统计只是附加功能：写盘失败不能影响“吃”这个交互本身。
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def format_bytes(size: int) -> str:
    size = max(0, int(size))
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.1f} GB"


def _path_size(path: Path, budget=None) -> int:
    """文件直接返回大小；目录递归累计大小，但不展开成多个“文件数”。

    ``budget``（``_ScanBudget``）非 None 时逐个文件记账，预算用尽即返回已累计的
    部分值——调用方必须查看 ``budget.truncated`` 并据此标记截断。
    """
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for root, _dirs, files in os.walk(path):
            # 进一个目录就记一次账（含 ``os.walk`` 的首个 root）：空目录/目录层数极深
            # 的树靠这一次记账才能被墙钟预算截住。
            if budget is not None and not budget.account_dir():
                return total
            for name in files:
                if budget is not None and not budget.account():
                    return total
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def _measure_path(path: Path, budget=None) -> tuple[int, int, int]:
    """返回 (文件数, 文件夹数, 字节数)；``budget`` 用尽时本路径记 0 项。"""
    try:
        if path.is_file():
            if budget is not None and not budget.account():
                return 0, 0, 0
            return 1, 0, _path_size(path)
        if path.is_dir():
            return 0, 1, _path_size(path, budget)
    except OSError:
        pass
    return 0, 0, 0


class _ScanBudget:
    """一次投喂的扫描预算：文件数上限 + 墙钟上限。

    记账粒度是「项」= 文件 + 目录（``visited`` 计口径）：

    - ``account_dir()`` 每进入一个新目录查一次钟——纯空目录树与"文件少但每层目录都
      卡"的慢盘树靠它封顶；
    - ``account()`` 每 ``SCAN_TIME_CHECK_EVERY`` 项查一次钟（逐项查钟本身也是开销）——
      单层几万文件的目录只有一层目录，靠它封顶。

    越预算即停扫并 ``truncated = True``；``scanned`` = 真正统计到的**文件**数，
    截断提示与统计按它报真实口径（目录数另有 ``folders`` 口径，两者互不相混）。
    """

    def __init__(self, file_limit=None, time_budget=None, clock=None) -> None:
        self._file_limit = max(
            0, int(SCAN_FILE_LIMIT if file_limit is None else file_limit))
        self._clock = _SCAN_CLOCK if clock is None else clock
        budget_s = max(0.0, float(
            SCAN_TIME_BUDGET_S if time_budget is None else time_budget))
        self._deadline = self._clock() + budget_s
        self.scanned = 0   # 已统计的文件数（气泡/统计口径）
        self.visited = 0   # 已记账的项数（文件 + 目录，查钟口径）
        self.truncated = False

    def account_dir(self) -> bool:
        """记一个即将进入的目录；返回 False = 预算用尽，调用方必须停止递归。"""
        if self.truncated:
            return False
        self.visited += 1
        if self._clock() >= self._deadline:
            self.truncated = True
            return False
        return True

    def account(self) -> bool:
        """记一个即将统计的文件；返回 False = 预算用尽，调用方必须立即停扫。"""
        if self.scanned >= self._file_limit:
            self.truncated = True
            return False
        self.visited += 1
        if (self.visited % SCAN_TIME_CHECK_EVERY == 0
                and self._clock() >= self._deadline):
            self.truncated = True
            return False
        self.scanned += 1
        return True


def _measure_paths(paths) -> tuple[int, int, int, bool, int]:
    """批量测量（两条投喂链唯一入口，别各写一份）。

    返回 ``(文件数, 文件夹数, 字节数, 是否截断, 已统计的文件数)``：触预算即停扫，
    后面的路径不再测量，结果只反映已统计的部分。
    """
    budget = _ScanBudget()
    files = folders = total_bytes = 0
    for raw in paths:
        file_count, folder_count, size = _measure_path(Path(raw), budget)
        files += file_count
        folders += folder_count
        total_bytes += size
        if budget.truncated:
            break
    return files, folders, total_bytes, budget.truncated, budget.scanned


def feeding_bubble_text(result: dict) -> str:
    """投喂气泡文案（两条投喂链共用，截断时按真实口径追加提示）。"""
    files = int(result.get("files") or 0)
    folders = int(result.get("folders") or 0)
    total_bytes = int(result.get("bytes") or 0)
    stats = result.get("stats") or {}
    if files and folders:
        batch = f"{files} 个文件、{folders} 个文件夹"
    elif files:
        batch = f"{files} 个文件"
    elif folders:
        batch = f"{folders} 个文件夹"
    else:
        batch = "空气"
    text = (
        f"啊呜～吃掉 {batch}（{format_bytes(total_bytes)}），"
        f"累计吃掉 {stats.get('file_count', 0)} 个文件、"
        f"{stats.get('folder_count', 0)} 个文件夹，"
        f"共 {format_bytes(stats.get('total_bytes', 0))}！"
    )
    if result.get("truncated"):
        text += f"（目录过大，只统计了前 {int(result.get('scanned') or 0)} 项）"
    return text


def _pick_eating_animation(pet) -> str | None:
    """从当前角色的随机动作池里选一个吃相关动画。"""
    acts = list(getattr(pet, "acts", None) or [])
    if not acts:
        return None
    for preferred in PREFERRED_EAT_ANIMATIONS:
        if preferred in acts:
            return preferred
    candidates = [
        name for name in acts
        if any(keyword in name for keyword in EAT_KEYWORDS)
    ]
    return random.choice(candidates) if candidates else random.choice(acts)


class FileEaterDropHandler(QObject):
    """挂在桌宠窗口上的拖放事件过滤器 + 吃文件反馈控制器。"""

    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        cfg_dir = getattr(getattr(pet, "cfg", None), "dir", None)
        self.stats_path = Path(cfg_dir) / STATS_FILE_NAME if cfg_dir else None
        pet.setAcceptDrops(True)
        pet.installEventFilter(self)

    # ------------------------------------------------------------ 事件
    def _local_paths(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [
            url.toLocalFile()
            for url in mime.urls()
            if isinstance(url, QUrl) and url.isLocalFile() and url.toLocalFile()
        ]

    def eventFilter(self, watched, event):  # noqa: N802 (Qt 命名)
        if watched is not self.pet:
            return False
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._local_paths(event.mimeData()):
                event.acceptProposedAction()
                return True
            return False
        if event_type == QEvent.Type.Drop:
            paths = self._local_paths(event.mimeData())
            if paths:
                self.eat_paths(paths)
                event.acceptProposedAction()
                return True
            return False
        return False

    # ------------------------------------------------------------ 反馈
    def eat_paths(self, paths) -> dict:
        """处理一批本地路径：统计、播放动画、气泡提示；文件保持不动。

        扫描走带预算的 ``_measure_paths``（B03）：大目录/网络盘触预算即停扫，
        结果里 ``truncated``/``scanned`` 如实反映截断，统计与气泡都不虚报。
        """
        files, folders, total_bytes, truncated, scanned = _measure_paths(paths)

        stats = self._record(files, folders, files + folders, total_bytes)
        result = {
            "files": files,
            "folders": folders,
            "bytes": total_bytes,
            "stats": stats,
            "truncated": truncated,
            "scanned": scanned,
        }
        self._play_eating_animation()
        self._show_feedback(result)
        # 解读询问接缝（install_file_interpreter 注入；未注入/无 chat 模块时为 None）
        offer = getattr(self, "interpret_offer", None)
        if callable(offer):
            offer(paths)
        return result

    def _record(self, files: int, folders: int, items: int, total_bytes: int) -> dict:
        if self.stats_path is None:
            return _default_stats()
        stats = _load_stats(self.stats_path)
        stats["feed_count"] += 1
        stats["file_count"] += max(0, files)
        stats["folder_count"] += max(0, folders)
        stats["item_count"] += max(0, items)
        stats["total_bytes"] += max(0, total_bytes)
        stats["history"].append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "files": max(0, files),
            "folders": max(0, folders),
            "bytes": max(0, total_bytes),
        })
        del stats["history"][:-STATS_HISTORY_LIMIT]
        _save_stats(self.stats_path, stats)
        return stats

    def _play_eating_animation(self) -> None:
        name = _pick_eating_animation(self.pet)
        if not name:
            return
        request = getattr(self.pet, "request_link_anim", None)
        if callable(request):
            request(name)
            return
        switch = getattr(self.pet, "switch_clip", None)
        if callable(switch):
            switch(name, link_request=True)

    def _show_feedback(self, result: dict) -> None:
        show = getattr(self.pet, "show_bubble", None)
        if not callable(show):
            return
        show(feeding_bubble_text(result), subtitle=FEEDING_BUBBLE_SUBTITLE)
