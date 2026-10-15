# -*- coding: utf-8 -*-
"""Fixed official host factory. Receives only Core-bound ports, never Core objects.

本仓库拓扑适配（相对上游 DLC 同文件）：

* 菜单工厂两参签名（``mod_menu`` 面），偏好经 :mod:`.current` 读取；
* ``runtime_factory`` 交 :class:`.runtime_mount.ScreenPackageRuntime`（mod/v1 挂载
  契约：commands/start/stop/close），watcher/manual 由它持有；
* ``bind_lifecycle`` 落到 ``FeatureHostContext.bind_execution``（owner 级执行转换），
  第三个 dispose 回调由 Runtime 包装器的 ``close()`` 驱动（本拓扑无单窗销毁语义）；
* ``api=None``：识屏包走独立视觉配置（自有 vault + profiles），不读聊天 Key。
"""

from dataclasses import replace

from pet.feature_ports import FeatureHostContext

from .contributions import OWNER, definition


def _bound(context):
    if not isinstance(context, FeatureHostContext) or context.owner != OWNER:
        raise TypeError("screen host requires owner-bound FeatureHostContext")
    return context


def _vision(context):
    from .config import VisionConfigService

    return VisionConfigService(context.configuration, vault=context.credentials, legacy_secret_reader=context.legacy_secret_reader, api=context.api)


def settings_context(context):
    from .settings_context import ScreenSettingsContext

    context = _bound(context)
    return ScreenSettingsContext(_vision(context), context.preferences, context.documents["memory"], context.desktop)


def runtime_context(context):
    from .runtime_context import ScreenRuntimeContext

    context = _bound(context)
    window = context.window
    if window is None:
        raise TypeError("runtime requires bound window ports")

    def worker_factory(parent, budget):
        from .worker_adapter import ProactiveScreenWorkerAdapter

        return ProactiveScreenWorkerAdapter(parent, mode="auto", budget_checker=budget, launch_factory=context.worker_launch_factory)

    def bind_lifecycle(stop, resume, dispose):
        # dispose 由 ScreenPackageRuntime.close() 显式驱动；stop/resume 钉在
        # owner 级执行转换上（bind_execution 由 bind_context 授权后注入）。
        del dispose
        binder = context.bind_execution
        if binder is None:
            return lambda: None
        return binder(stop, resume)

    return ScreenRuntimeContext(
        vision=_vision(context),
        preferences=context.preferences,
        state_document=context.state_documents["state"],
        dry_state_document=context.state_documents["dry_state"],
        memory=context.documents["memory"],
        window_state=window.snapshot,
        agent_busy=window.agent_busy,
        show_bubble=window.show_bubble,
        hold_bubble=window.hold_bubble,
        sync_text=window.sync_text,
        external_text=window.external_text,
        execution_enabled=window.enabled,
        bind_lifecycle=bind_lifecycle,
        worker_factory=worker_factory,
        desktop=context.desktop,
        allow_in_process=context.allow_in_process,
    )


def create_runtime(context, *, worker_mode="auto"):
    from .runtime_mount import ScreenPackageRuntime

    return ScreenPackageRuntime(_bound(context), worker_mode=worker_mode)


def create_manual(context, request, cancel):
    from .manual import ManualScreenHost

    return ManualScreenHost(runtime_context(context), request, cancel)


def create_settings(context, parent=None):
    from .contribution_settings import ScreenContributionSettings

    return ScreenContributionSettings(settings_context(context), parent)


def create_host():
    from ..common.policy import effective_proactive_config

    return replace(
        definition(), settings_factory=create_settings, runtime_factory=create_runtime, manual_factory=create_manual, policy_factory=effective_proactive_config
    )
