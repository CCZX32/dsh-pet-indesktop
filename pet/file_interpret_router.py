# -*- coding: utf-8 -*-
"""拖文件解读的路由：内置解读器与 AI 包解读器只弹一个确认。

本仓库内置聊天与官方 AI 包**共存**（见 ``docs/modding/PORT-STATUS.md`` §九）。
两条投喂链（``sprite_feeding`` / legacy ``file_eater``）只有一个 ``interpret_offer``
接缝，所以选路必须集中在一处：

* 包聊天窗至少开着一个、且包仍处于可接收状态 → 走包的 ``FileInterpretController``；
* 其它情况（包窗没开、包停用/卸载、插件解析失败）→ 回落内置解读器。

路由只持有两个可调用对象与一个开窗计数，不 import Qt、不碰包运行时；包侧在
``runtime_mount._show`` 打开窗口时登记，``destroyed`` 时注销。
"""

from __future__ import annotations

from typing import Any, Callable


class FileInterpretRouter:
    """One ``offer(paths)`` seam, two possible interpreters."""

    def __init__(self) -> None:
        self._builtin: Callable[[Any], Any] | None = None
        self._package: Callable[[Any], Any] | None = None
        self._package_windows = 0

    @property
    def package_open(self) -> bool:
        return self._package_windows > 0

    def set_builtin_offer(self, offer: Callable[[Any], Any] | None) -> None:
        self._builtin = offer

    def set_package_offer(self, offer: Callable[[Any], Any] | None) -> None:
        self._package = offer
        if offer is None:
            self._package_windows = 0

    def package_window_opened(self) -> None:
        self._package_windows += 1

    def package_window_closed(self) -> None:
        self._package_windows = max(0, self._package_windows - 1)

    def __call__(self, paths) -> None:
        package = self._package if self._package_windows > 0 else None
        offer = package if callable(package) else self._builtin
        if callable(offer):
            offer(paths)


__all__ = ["FileInterpretRouter"]
