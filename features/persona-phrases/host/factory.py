# -*- coding: utf-8 -*-
"""日常台词包的 host 入口。"""

from __future__ import annotations

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context) -> FeatureHostContext:
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("persona host requires owner-bound FeatureHostContext")
    return context


def create_settings(context, parent=None):
    from .contribution_settings import PersonaSettings

    return PersonaSettings(_bound(context), parent)


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import PersonaRuntime

    if worker_mode not in ("auto", "in-process"):
        raise ValueError("persona_host_has_no_worker")
    return PersonaRuntime(_bound(context))


def create_host():
    return definition()
