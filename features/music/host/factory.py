# -*- coding: utf-8 -*-
"""音乐启动器包的 host 入口。"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("music host requires owner-bound FeatureHostContext")
    return context


def create_settings(context, parent=None):
    from .contribution_settings import MusicSettings

    return MusicSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import MusicRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("music_host_has_no_worker")
    return MusicRuntime(_bound(context))


def create_host():
    return definition()
