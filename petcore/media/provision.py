"""WebM → WebP 首跑供给（复用主分支的世代/GC 管线）。"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("petcore.media.provision")

_started = False


def provision_character(
    character,
    *,
    budget_seconds: float = 60.0,
    migration_clips: int = 1,
):
    """对单个角色跑一轮供给，返回 ``ProvisionReport``；不可用时返回 None。"""
    root = Path(getattr(character, "root", ""))
    videos = root / "videos"
    if not videos.is_dir():
        return None
    if not any(
        getattr(animation, "path", None) is not None
        and str(getattr(animation, "path")).lower().endswith(".webm")
        for animation in getattr(character, "animations", ())
    ):
        return None
    try:
        from pet import frameseq_provision
    except Exception:
        logger.debug("frameseq_provision unavailable", exc_info=True)
        return None
    try:
        return frameseq_provision.provision_once(
            videos,
            root / "frameseq",
            round_seconds=float(budget_seconds),
            migration_clips=max(1, int(migration_clips)),
        )
    except Exception:
        logger.warning("首跑供给失败", exc_info=True)
        return None


def start_background_provision(host) -> bool:
    """启动一次后台供给（每个进程最多一次）；返回是否真的启动。"""
    global _started
    if _started:
        return False
    window = getattr(host, "window", None)
    character = getattr(window, "character", None)
    if character is None:
        return False
    root = Path(getattr(character, "root", ""))
    if not root.is_dir() or not os.access(root, os.W_OK):
        return False
    _started = True

    def worker() -> None:
        report = provision_character(character)
        if report is None:
            return
        logger.info(
            "首跑供给完成 converted=%s retired=%s deferred=%s locked=%s idle=%s",
            getattr(report, "converted", 0),
            getattr(report, "retired", 0),
            getattr(report, "deferred_budget", 0)
            + getattr(report, "deferred_backoff", 0)
            + getattr(report, "deferred_disk", 0),
            getattr(report, "locked", False),
            getattr(report, "idle", False),
        )

    timer = threading.Timer(5.0, worker)
    timer.daemon = True
    timer.name = "petcore-provision"
    timer.start()
    return True
