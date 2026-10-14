"""Explicit official feature contributions; in-memory authority, not an installer.

The host owns state and leases, never feature UI objects or persisted settings.
A settings-only process can register factories without attaching runtime commands.

宿主还持有一棵进程级 :class:`CoreEventBus`（Phase 2 内核移植）：owner 的订阅随
``disable`` / ``fault`` / ``remove`` 按 owner 清理，事件回调异常按
``event_callback_failed`` 把该 owner 打成 fault（与执行转换失败同口径），
状态转换同时以 ``feature.lifecycle.changed`` 发布到总线。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable

from .capabilities import CapabilitySet
from .contributions import Contribution, ContributionBatch, ContributionHandle, ContributionRegistry
from .events import CoreEvent, CoreEventBus, ScopedEventBus, Subscription
from .ports import CommandRegistry

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureDefinition:
    owner: str
    menus: tuple[Contribution, ...]
    settings_factory: Callable[..., Any]
    runtime_factory: Callable[..., Any] | None = None
    manual_factory: Callable[..., Any] | None = None
    policy_factory: Callable[..., dict] | None = None
    worker_launch_factory: Callable | None = None
    allow_in_process: bool = True
    mount_contract: str = ""


class FeatureHost:
    def __init__(self, registry: ContributionRegistry | None = None, *, events: CoreEventBus | None = None):
        self.registry = registry or ContributionRegistry(CommandRegistry())
        self._events = events or CoreEventBus()
        self._events.set_error_handler(self._handle_event_error)
        self._definitions: dict[str, FeatureDefinition] = {}
        self._states: dict[str, str] = {}
        self._bindings: dict[tuple[str, str], tuple[dict[str, Callable], Callable]] = {}
        self._menus: dict[tuple[str, str], ContributionBatch] = {}
        self._settings: dict[tuple[str, str], ContributionHandle] = {}
        self._listeners: list[Callable[[str, str], None]] = []
        self._prepare: dict[str, list[Callable[[], bool]]] = {}
        self._diagnostics: dict[str, str] = {}
        self._executions: dict[object, tuple[str, Callable, Callable]] = {}
        self._authorities: dict[str, Callable[[], bool]] = {}

    def state(self, owner: str) -> str:
        return self._states.get(owner, "absent")

    def enabled(self, owner: str) -> bool:
        if self.state(owner) != "enabled":
            return False
        check = self._authorities.get(owner)
        try:
            return bool(check()) if check is not None else True
        except Exception:
            return False

    def bind_authority(self, owner: str, check: Callable[[], bool]) -> None:
        """Fail closed at every execution seam, before watcher delivery."""
        self.registry.check_thread()
        self._authorities[owner] = check

    def configurable(self, owner: str) -> bool:
        return self.state(owner) in ("enabled", "disabled")

    def definition(self, owner: str) -> FeatureDefinition | None:
        """Read-only declaration, not runtime or configuration internals."""
        return self._definitions.get(owner)

    def owners(self) -> tuple[str, ...]:
        return tuple(o for o in self._definitions if self.configurable(o))

    @property
    def events(self) -> CoreEventBus:
        """宿主侧的事件总线入口（发布 / 诊断快照）；feature 作者走 :meth:`event_bus`。"""
        return self._events

    def event_bus(self, owner: str) -> ScopedEventBus:
        """一个 owner 的事件门面：订阅与清理都被钉在这个 owner 上。"""
        self.registry.check_thread()
        if not self.configurable(owner):
            raise PermissionError("feature is not available")
        return ScopedEventBus(self._events, owner)

    def _handle_event_error(self, subscription: Subscription, event: CoreEvent, exc: Exception) -> None:
        """事件回调异常 = 该 owner 的运行期故障；不认识的 owner（宿主自身）只记日志。

        总线在调用本处理器前已摘除故障订阅，因此 fault → 生命周期事件的重入
        派发不会再踩到同一个回调（递归线性收敛，不需要额外闸门）。
        """
        del event, exc  # 细节已随总线日志记录；宿主侧诊断只留固定码
        _LOG.warning("feature event callback failed: %s", subscription.owner)
        if subscription.owner in self._definitions:
            self.fault(subscription.owner, "event_callback_failed")

    def diagnostics(self) -> dict[str, str]:
        return dict(self._diagnostics)

    def provide(self, definition: FeatureDefinition, *, enabled: bool = True) -> None:
        self.registry.check_thread()
        if definition.owner in self._definitions:
            raise ValueError("feature already provided")
        self._definitions[definition.owner] = definition
        self._states[definition.owner] = "enabled" if enabled else "disabled"

    def bind_context(self, context):
        """Only a provided owner's immutable ports can reach its factories."""
        from ..feature_ports import FeatureHostContext

        self.registry.check_thread()
        if not isinstance(context, FeatureHostContext) or not self.configurable(context.owner):
            raise PermissionError("feature is not available")
        definition = self._definitions[context.owner]
        api = context.api
        if api is not None:
            from ..api_ports import FeatureApiPort

            def guarded(callback):
                def call(purpose):
                    if not self.enabled(context.owner):
                        raise PermissionError("execution_not_authorized")
                    return callback(purpose)

                return call

            api_original = api
            api = FeatureApiPort(
                guarded(api.metadata),
                lambda purpose: api_original.effective_version(purpose) if self.enabled(context.owner) else "unavailable",
                guarded(api.resolve),
                api.subscribe,
                api.open_settings,
            )
        return replace(
            context,
            api=api,
            worker_launch_factory=definition.worker_launch_factory,
            allow_in_process=definition.allow_in_process,
            execution_authorized=lambda: self.enabled(context.owner),
            bind_execution=lambda stop, resume: self.bind_execution(context.owner, stop, resume),
        )

    def runtime(self, context, *, worker_mode="auto"):
        context = self.bind_context(context)
        if not self.enabled(context.owner):
            return None
        factory = self._definitions[context.owner].runtime_factory
        return factory(context, worker_mode=worker_mode) if factory else None

    def manual(self, context, request, cancel):
        context = self.bind_context(context)
        if not self.enabled(context.owner):
            return None
        factory = self._definitions[context.owner].manual_factory
        return factory(context, request, cancel) if factory else None

    def policy(self, owner, values):
        if not self.configurable(owner):
            return {}
        factory = self._definitions[owner].policy_factory
        return factory(values) if factory else {}

    def subscribe(self, callback: Callable[[str, str], None]) -> Callable[[], None]:
        self.registry.check_thread()
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def before_remove(self, owner: str, callback: Callable[[], bool]) -> Callable[[], None]:
        self.registry.check_thread()
        callbacks = self._prepare.setdefault(owner, [])
        callbacks.append(callback)
        return lambda: callbacks.remove(callback) if callback in callbacks else None

    def _notify(self, owner: str) -> None:
        for callback in tuple(self._listeners):
            try:
                callback(owner, self.state(owner))
            except Exception:
                _LOG.exception("feature contribution observer failed")
        self._events.publish(
            CoreEvent.now("feature.lifecycle.changed", "core.feature_host", {"owner": owner, "state": self.state(owner)})
        )

    def bind_execution(self, owner: str, stop: Callable, resume: Callable) -> Callable[[], None]:
        """Host-owned runtime, independent of the number of window menus."""
        self.registry.check_thread()
        token = object()
        self._executions[token] = owner, stop, resume

        def release() -> None:
            self.registry.check_thread()
            self._executions.pop(token, None)

        return release

    def _execution_transition(self, owner: str, *, running: bool) -> None:
        for o, stop, resume in tuple(self._executions.values()):
            if o == owner:
                try:
                    (resume if running else stop)()
                except Exception:
                    _LOG.exception("feature execution transition failed")
                    self._diagnostics[owner] = "execution_transition_failed"

    def attach(self, owner: str, scope: str, commands: dict[str, Callable], stop: Callable[[], None]) -> None:
        self.registry.check_thread()
        key = owner, scope
        if key in self._bindings:
            return
        self._bindings[key] = commands, stop
        if self.enabled(owner):
            try:
                self._register_menu(owner, scope)
            except Exception:
                self._bindings.pop(key, None)
                raise

    def _register_menu(self, owner: str, scope: str) -> None:
        port = self.registry.bind(owner, scope, CapabilitySet(["menu.contribute"]))
        self._menus[owner, scope] = port.register(list(self._definitions[owner].menus), commands=self._bindings[owner, scope][0])

    def detach(self, owner: str, scope: str) -> None:
        self.registry.check_thread()
        batch = self._menus.pop((owner, scope), None)
        if batch:
            batch.dispose()
        self._bindings.pop((owner, scope), None)
        handle = self._settings.pop((owner, scope), None)
        if handle:
            handle.revoke()

    def menu(self, owner: str, scope: str, contribution_id: str) -> ContributionHandle | None:
        batch = self._menus.get((owner, scope))
        if not self.enabled(owner) or not batch:
            return None
        return next((h for h in batch.handles if h.descriptor.id == contribution_id and h.active), None)

    def settings(self, owner: str, scope: str) -> ContributionHandle | None:
        self.registry.check_thread()
        if not self.configurable(owner):
            return None
        key = owner, scope
        old = self._settings.get(key)
        if old and old.active:
            return old
        port = self.registry.bind(owner, scope, CapabilitySet(["settings.contribute"]))
        batch = port.register([Contribution("settings", "settings", group="automation", factory=self._definitions[owner].settings_factory)])
        self._settings[key] = batch.handles[0]
        return batch.handles[0]

    def disable(self, owner: str) -> None:
        self.registry.check_thread()
        if self.state(owner) != "enabled":
            return
        # Authority changes before callbacks; stale actions cannot race cleanup.
        self._states[owner] = "disabled"
        self._execution_transition(owner, running=False)
        for (o, scope), (_, stop) in tuple(self._bindings.items()):
            if o != owner:
                continue
            batch = self._menus.pop((o, scope), None)
            if batch:
                batch.dispose()
            try:
                stop()
            except Exception:
                _LOG.exception("feature stop failed")
        self._events.clear_owner(owner)
        self._notify(owner)

    def enable(self, owner: str) -> None:
        self.registry.check_thread()
        if self.state(owner) != "disabled":
            return
        created = []
        try:
            for o, scope in self._bindings:
                if o == owner:
                    self._register_menu(o, scope)
                    created.append((o, scope))
        except Exception:
            for key in created:
                self._menus.pop(key).dispose()
            raise
        self._states[owner] = "enabled"
        self._execution_transition(owner, running=True)
        self._notify(owner)

    def remove(self, owner: str) -> bool:
        """撤回一个 owner 在宿主里的**全部**痕迹（幂等）；False = 被 ``before_remove`` 否决。

        ``disable`` 只停执行；``remove`` 还要摘干净这个 owner 的声明与绑定，否则
        **重装会撞上死代码**：

        * ``provide`` 会因为 ``_definitions`` 里那份旧声明拒绝（"feature already
          provided"），于是卸载后在同一进程里再装一次永远装不进来；
        * 残留的 ``_bindings`` 会让下一次 ``enable`` 把菜单挂回**上一代已经关闭的**
          Runtime 上（菜单能点，命令打在死对象上）。

        撤走的是声明与绑定，**不是**导入过的代码（``sys.modules`` 里那份仍然在
        （Python 没有卸载），所以卸载只删安装副本，代码留到进程退出。
        """
        self.registry.check_thread()
        for prepare in tuple(self._prepare.get(owner, ())):
            if not prepare():
                return False
        self.disable(owner)
        self._states[owner] = "absent"
        self._events.clear_owner(owner)
        self.registry.revoke_owner(owner)
        self._definitions.pop(owner, None)
        self._bindings = {key: value for key, value in self._bindings.items() if key[0] != owner}
        self._authorities.pop(owner, None)
        self._menus = {key: value for key, value in self._menus.items() if key[0] != owner}
        self._settings = {key: value for key, value in self._settings.items() if key[0] != owner}
        self._executions = {token: value for token, value in self._executions.items() if value[0] != owner}
        # ``_prepare``（before_remove 闸门）**故意留着**：它是"动这个 owner 之前必须先问谁"
        # 的**常设**登记，不是随 provide 派生的一份状态。摘掉它会让"卸载→重装"之后的
        # 第二次撤回失去闸门（重装不会再走一遍 attach，闸门没人重挂）。
        self._notify(owner)
        return True

    def fault(self, owner: str, reason: str) -> None:
        self.disable(owner)
        self._states[owner] = "fault"
        self._diagnostics[owner] = reason
        self._events.clear_owner(owner)
        self.registry.revoke_owner(owner)
        self._notify(owner)
