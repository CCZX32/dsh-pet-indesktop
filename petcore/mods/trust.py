"""随安装包分发的功能扩展授信标记。

`allow_feature_mods` 是全局开关（用户在设置里显式打开）。安装器随包投放的官方
扩展由用户在安装向导里勾选，属于逐包授权：扩展目录里放一个空文件 `.trusted`
即视为已授信，卸载时随目录一起消失，不需要额外的状态文件。

**授信的判据是「位置 + 标记」，不是「标记本身」**：只有安装目录（冻结包的
`{app}\\mods`，见 :func:`petcore.paths.install_mods_dir`）下的标记才算数。
用户数据目录里的 `.trusted` 一律无效——否则任何导入的 ZIP 只要自带一个空文件
就能跳过 `allow_feature_mods` 在用户进程里执行代码。对应地，
:func:`petcore.mods.install.install` 在落盘前会剥掉包里自带的标记。
"""

from __future__ import annotations

import logging
from pathlib import Path

TRUST_MARKER = ".trusted"

_logger = logging.getLogger("petcore.mods.trust")


def marker_path(mod_path: Path | str) -> Path:
    return Path(mod_path) / TRUST_MARKER


def install_trust_root() -> Path | None:
    """允许承载授信标记的根目录（安装器投放位置）；源码树返回 ``None``。"""
    try:
        from .. import paths
    except Exception:  # pragma: no cover - 循环导入时的保守兜底
        return None
    try:
        return paths.install_mods_dir()
    except Exception:  # pragma: no cover - 平台异常不该让加载器崩
        return None


def is_trusted(mod_path: Path | str) -> bool:
    """标记存在**且**位于安装目录之下才算已授信。"""
    try:
        if not marker_path(mod_path).is_file():
            return False
    except OSError:
        return False
    root = install_trust_root()
    if root is None:
        return False
    try:
        target = Path(mod_path).resolve()
        base = Path(root).resolve()
    except OSError:
        return False
    return target == base or base in target.parents


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
