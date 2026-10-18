# -*- coding: utf-8 -*-
"""账户用量包的 host 入口：``create_host`` + Runtime / 设置工厂。

本模块在预检子进程里被 import，**顶层不许拉起 Qt**；GUI 相关实现都在函数体
里延迟导入。
"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("account-usage host requires owner-bound FeatureHostContext")
    return context


def create_settings(context, parent=None):
    from .contribution_settings import AccountUsageSettings

    return AccountUsageSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import AccountUsageRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("account_usage_host_has_no_worker")
    return AccountUsageRuntime(_bound(context))


def create_host():
    return definition()
