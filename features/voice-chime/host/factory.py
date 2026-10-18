# -*- coding: utf-8 -*-
"""语音报时包的 host 入口。"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("voice-chime host requires owner-bound FeatureHostContext")
    return context


def create_settings(context, parent=None):
    from .contribution_settings import VoiceChimeSettings

    return VoiceChimeSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import VoiceChimeRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("voice_chime_host_has_no_worker")
    return VoiceChimeRuntime(_bound(context))


def create_host():
    return definition()
