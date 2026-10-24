"""功能包来源与授信标记的契约（只依赖标准库）。

来源决定两件事：是否可以写入 `.trusted` 标记，以及授权口径。
按 `petcore/AGENTS.md`：`.trusted` 只由安装向导在用户显式勾选时写入；
市场下载与本地导入都**不得**写它，市场包内自带的 `.trusted` 也必须剔除。
"""

from __future__ import annotations

from enum import Enum


class PackageOrigin(str, Enum):
    """功能包从哪来。"""

    MARKET = "market"
    LOCAL_DIR = "local-dir"
    LOCAL_ZIP = "local-zip"
    BUNDLED = "bundled"


def writes_trusted_marker(origin: PackageOrigin | str) -> bool:
    """只有安装向导投放的 ``BUNDLED`` 包允许带 `.trusted`。"""
    try:
        value = PackageOrigin(origin)
    except ValueError:
        return False
    return value is PackageOrigin.BUNDLED
