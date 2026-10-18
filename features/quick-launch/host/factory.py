# -*- coding: utf-8 -*-
"""快捷启动包的 host 入口。"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("quick-launch host requires owner-bound FeatureHostContext")
    return context


def create_settings(context, parent=None):
    from .contribution_settings import QuickLaunchSettings

    return QuickLaunchSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import QuickLaunchRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("quick_launch_host_has_no_worker")
    return QuickLaunchRuntime(_bound(context))


def create_host():
    return definition()
