"""随安装包分发的功能扩展授信标记。

`allow_feature_mods` 是全局开关（用户在设置里显式打开）。安装器随包投放的官方
扩展由用户在安装向导里勾选，属于逐包授权：扩展目录里放一个空文件 `.trusted`
即视为已授信，卸载时随目录一起消失，不需要额外的状态文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

TRUST_MARKER = ".trusted"

_logger = logging.getLogger("petcore.mods.trust")


def marker_path(mod_path: Path | str) -> Path:
    return Path(mod_path) / TRUST_MARKER


def is_trusted(mod_path: Path | str) -> bool:
    try:
        return marker_path(mod_path).is_file()
    except OSError:
        return False


def mark_trusted(mod_path: Path | str) -> bool:
    path = marker_path(mod_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        _logger.warning("cannot write trust marker %s", path, exc_info=True)
        return False
    return True


def unmark_trusted(mod_path: Path | str) -> None:
    try:
        marker_path(mod_path).unlink()
    except FileNotFoundError:
        return
    except OSError:
        _logger.warning("cannot remove trust marker %s", mod_path, exc_info=True)
