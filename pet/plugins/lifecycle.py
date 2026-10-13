# -*- coding: utf-8 -*-
"""事务层 ``runtime=`` 的唯一消费方：回答「现在能不能动这个版本」。

``FeaturePackageTransactionService`` 在每个会动版本目录的操作前后各问一次
:meth:`FeatureHostLifecycle.prepare`，判据有三个可能的结果：

``draft_blocked``
    这个 owner 的设置面板里有**未保存的草稿**。草稿只活在设置面板里，丢它就是丢用户
    的输入，所以先别说"能不能释放"，如实回报并让用户先处置（保存 / 放弃 / 取消）。

``awaiting_release``
    ``install`` / ``upgrade`` / ``rollback`` / ``uninstall`` 要动版本目录，而**另一个
    活进程**的租约还占着这些版本——如实回报「等那个程序自然退出」，不假装已完成。
    ``disable`` 只翻一个布尔量、不碰版本目录，因此**不**受这条判据约束：两个宿主
    （core / settings 角色）同时开着时停用一个扩展必须做得到。

``ready``
    以上都不成立，可以继续。

**并发纪律（本模块存在的理由）**：``prepare`` 由管理器的后台线程调用，而草稿属于
GUI 线程的 Qt 对象。照 ``ModCenterController.LiveUsage`` 的先例：GUI 线程在派发前
把草稿名取成一张**不可变快照**（:meth:`note_drafts` 整体替换，绝不原地改），后台线程
只读快照。面板对象一次都不进后台线程。

**本模块零 Qt**：只应被后台线程路径 import（``tests/test_mod_lifecycle_gate.py`` 用
无 GUI 探针钉住这一点）。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Iterable, Mapping

if TYPE_CHECKING:
    from ..feature_package_transactions import RuntimePreparation

__all__ = ["RELEASE_OPERATIONS", "FeatureHostLifecycle"]

#: 会动版本目录（删除 / 替换 / 新增）的操作：只有这几个会被别的活进程的租约占住。
RELEASE_OPERATIONS = frozenset({"install", "upgrade", "rollback", "uninstall"})

_NO_DRAFTS: Mapping[str, tuple[str, ...]] = {}


class FeatureHostLifecycle:
    """草稿门 + 跨进程占用门；后台线程只读快照，绝不碰 Qt 对象。

    ``process_id`` 可注入是为了测试与子进程场景；生产恒为 ``os.getpid()``。
    """

    def __init__(self, *, process_id: int | None = None) -> None:
        self.process_id = os.getpid() if process_id is None else int(process_id)
        self._drafts = _NO_DRAFTS

    # ------------------------------------------------------------- 快照面

    def note_drafts(self, owner: str, drafts: Iterable[str]) -> None:
        """**GUI 线程**调用：整体替换这个 owner 的草稿名快照（空 = 没有草稿）。

        整体替换而不是原地改：后台线程正在读的那份字典必须是不可变的——它要么看到
        替换前的全文，要么看到替换后的全文，绝不会看到改了一半的中间态。
        """
        names = tuple(dict.fromkeys(str(name) for name in drafts if str(name).strip()))
        current = dict(self._drafts)
        if names:
            current[str(owner)] = names
        else:
            current.pop(str(owner), None)
        self._drafts = current

    def drafts(self, owner: str) -> tuple[str, ...]:
        """这个 owner 当下的草稿名（GUI 侧预检与事务层判据读的是同一份快照）。"""
        return self._drafts.get(str(owner), ())

    # ------------------------------------------------------------- 判据

    def prepare(self, request) -> RuntimePreparation:
        from ..feature_package_transactions import RuntimePreparation

        drafts = self._drafts.get(request.feature_id, ())
        if drafts:
            return RuntimePreparation(
                "draft_blocked",
                "unsaved_settings",
                details={"drafts": tuple(drafts), "pid": self.process_id},
            )
        blocked = self._foreign_versions(request)
        if blocked:
            owners = tuple(owner for owner in request.live_owners if owner[0] != self.process_id)
            return RuntimePreparation(
                "awaiting_release",
                "version_in_use",
                blocked_versions=blocked,
                details={"owners": owners, "pid": self.process_id},
            )
        return RuntimePreparation(details={"pid": self.process_id, "prepared_nonce": request.nonce})

    def _foreign_versions(self, request) -> tuple[str, ...]:
        if request.operation not in RELEASE_OPERATIONS:
            return ()
        if not any(owner[0] != self.process_id for owner in request.live_owners):
            return ()
        # 一个版本都没有（首次安装）：没有可释放的东西，别的进程占不到它头上。
        return tuple(request.versions)
