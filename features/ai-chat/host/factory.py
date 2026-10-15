# -*- coding: utf-8 -*-
"""固定官方宿主工厂。只接收 Core 绑好的端口，拿不到 Core 对象。

本仓库拓扑适配（相对上游 DLC 同文件）：

* 定义与菜单搬进 :mod:`.contributions`（本仓库的菜单面是两参签名，且定义必须
  带 ``mod/v1`` 挂载契约）；
* ``runtime_factory`` 交 :class:`.runtime_mount.AiPackageRuntime`（mod/v1 挂载
  契约：commands/start/stop/close），窗口的 pet 形定位面由它惰性解析；
* ``bind_lifecycle`` 落到 ``FeatureHostContext.bind_execution``（owner 级执行转换），
  pause/resume 因此由宿主的启用态驱动，不靠"窗口关没关"。

执行契约与上游逐字一致：AI 包是 ``host-only``（无独立 Worker），所以
``desktop`` / ``worker_launch_factory`` 有任何一个非空就是契约不成立——
宁可显式报错，也不在半套端口上跑起来。
"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("AI host requires owner-bound FeatureHostContext")
    return context


def _check_execution_contract(context: FeatureHostContext) -> FeatureHostContext:
    if context.desktop is not None or context.worker_launch_factory is not None or not context.allow_in_process:
        raise PermissionError("ai_execution_contract_invalid")
    return context


def chat_menu(menu, handle):
    from .contributions import chat_menu as build

    return build(menu, handle)


def quick_menu(menu, handle):
    from .contributions import quick_menu as build

    return build(menu, handle)


def create_settings(context, parent=None):
    from .contribution_settings import AiContributionSettings

    return AiContributionSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import AiPackageRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("ai_host_has_no_worker")
    return AiPackageRuntime(_check_execution_contract(_bound(context)))


def create_host():
    return definition()
