"""Actual production startup: verified import, process pin, ports, then receipt.

This path never starts a Worker and never asks UI to certify a boolean result.
All FeatureHost operations run on its owning thread.

宿主面适配（见 ``.scratch/dlc-fusion/S1c-HANDOFF.md`` §二）：DLC 版本在模块顶层
直接绑死功能扩展**宿主运行时**——``feature_ports.FeatureHostContext`` +
``plugins.feature_packages.FeaturePackageLoader`` + ``plugins.package_binding.
bind_verified_feature``。那套运行时（FeatureHost / 插件清单 / 端口装配）不在本片
范围，本仓库没有。照 S2 处理 ``plugins/worker_launch`` 的先例，只保留**与宿主
无关的那一半**：租约/许可（permit）/回执（receipt）/运行目录边界/授权刷新/状态机
控制流全部逐字保留，把"把已验签的包绑进宿主"这一步改成**宿主注入的 binder**。

``FeatureHostContext`` 因此不再是一个具体类型：绑定结果与上下文由 binder 决定，
本模块只按契约读它们的属性（``owner`` / ``allow_in_process`` /
``worker_launch_factory`` / ``desktop`` / ``handle`` / ``host`` / ``closed``）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from .feature_startup_contract import StartupLoadPermit
from .feature_version_lease import FeatureVersionSelection
from .plugins.package_trust import PackageVerificationError

if TYPE_CHECKING:
    from .feature_package_transactions import FeaturePackageTransactionService, OperationResult

_RECEIPT_SEAL = object()


class FeaturePackageBinder(Protocol):
    """宿主侧唯一缝口：把一份已验签的描述符绑成"本进程可加载的"句柄。

    实现者负责 DLC ``bind_verified_feature`` 的全部职责（加载宿主模块、绑端口、
    建立进程 pin、接租约协调器），并以同一个对象暴露 DLC 的绑定形状：``host`` /
    ``selection`` / ``context`` / ``handle``（含 ``descriptor`` / ``process_pin`` /
    ``closed``）/ ``closed`` / ``refresh_selection``。
    """

    def __call__(
        self, host: object, service: FeaturePackageTransactionService, selection: FeatureVersionSelection, runtime_directory: Path, core_roots: tuple[Path, ...]
    ) -> object: ...


@dataclass(frozen=True)
class StartupLoadReceipt:
    permit: StartupLoadPermit
    binding: Any
    context: Any
    process_id: int
    lease_id: str
    _seal: object = field(repr=False)

    def validate(self, service: FeaturePackageTransactionService, state) -> bool:
        pin = self.binding.handle.process_pin
        return (
            self._seal is _RECEIPT_SEAL
            and self.process_id == os.getpid()
            and service._startup_permits.get(self.permit.nonce) is self.permit
            and self.permit.matches(service.store.root, state)
            and not self.binding.closed
            and not self.binding.handle.closed
            and self.binding.context is not None
            and self.binding.context is self.context
            and self.context.owner == self.permit.version_owner
            and _valid_execution_ports(self.context, self.binding.handle.descriptor.execution_kind)
            and pin is not None
            and not pin.closed
            and pin.kind == "host"
            and pin.lease_id == self.lease_id
            and pin.revision == self.permit.revision
            and pin.version == self.permit.version
            and self.binding.host.state(self.context.owner) == "disabled"
        )


def _valid_execution_ports(context: Any, execution_kind: str) -> bool:
    kind = execution_kind
    if kind == "host-only":
        return context.allow_in_process is True and context.worker_launch_factory is None and context.desktop is None
    return context.allow_in_process is False and callable(context.worker_launch_factory)


class ProductionFeatureStartup:
    def __init__(
        self,
        service: FeaturePackageTransactionService,
        host: Any,
        *,
        runtime_directory: Path,
        context_factory: Callable[[], Any],
        binder: FeaturePackageBinder,
        role: str = "core",
    ):
        self.service = service
        self.host = host
        self.runtime_directory = runtime_directory
        self.context_factory = context_factory
        self.binder = binder
        self.role = role
        self.binding: Any = None
        self.context: Any = None
        self._pending_receipt: StartupLoadReceipt | None = None

    def _bind(self, selection: FeatureVersionSelection) -> Any:
        # 宿主注入的 binder 取代 DLC 的 bind_verified_feature(FeaturePackageLoader(...))。
        return self.binder(self.host, self.service, selection, self.runtime_directory, self._core_roots())

    def _prepare_runtime(self) -> None:
        from .feature_state_io import StateError, safe_path

        runtime = self.runtime_directory
        if not runtime.is_absolute() or not runtime.is_relative_to(self.service.leases.data_root) or runtime.is_relative_to(self.service.store.root):
            raise StateError("runtime_boundary")
        safe_path(runtime)
        runtime.mkdir(parents=True, exist_ok=True)
        safe_path(runtime)

    def _core_roots(self) -> tuple[Path, ...]:
        if not getattr(sys, "frozen", False):
            return ()
        return (Path(sys.executable).parent, Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))

    def _attach_authority(self) -> None:
        assert self.binding is not None
        binding = self.binding

        def allowed():
            selection = binding.selection
            state = self.service.store.read().state
            return (
                not binding.closed
                and selection is not None
                and state is not None
                and state.enabled
                and state.pending_transaction is None
                and state.revision == selection.revision
                and state.active == selection.version
                and state.versions.get(selection.version) == selection.manifest_digest
            )

        self.host.bind_authority(binding.handle.descriptor.id, allowed)

    def _resolve_current_selection(self, purpose: str) -> FeatureVersionSelection:
        from .feature_state_io import StateError

        resolution = self.service.store.resolve_verified(self.service.verifier, purpose=purpose)
        # An unresolved selection normally means invalid/stale authorization;
        # kernel contention is different and must survive the conversion.
        if resolution.status == "lock_busy":
            raise StateError("state_lock_busy")
        return FeatureVersionSelection.from_resolution(resolution)

    def release(self) -> bool:
        """把当前绑定交还宿主（卸载 / 换版本前必须先放掉进程 pin 与 Runtime）。

        ``FeaturePackageBinding.close()`` 会走 ``host.remove(owner)``（停 Runtime、撤销
        贡献、清空状态）并关掉 host handle。本对象随后不再持有已关闭的绑定——下一次
        ``load_current()`` / ``load_pending()`` 会重新绑定。

        **额外放掉跨进程 host pin**：``HostHandle.close()`` 刻意不动 ``process_pin``
        （导入过的代码无法卸载，pin 因此在 DLC 口径里活到进程退出）。但"用户明确卸载 /
        换版本"是另一回事——不放手的话删除动作永远做不到（占用判据全 free 才允许删），
        用户会看到"等你把桌宠退了再说"，而重装又被 pending 事务挡住。这里放掉的是**本
        进程自己那一份**租约：别的进程（例如独立设置进程）的 pin 照旧拦着，那句"等程序
        自然退出"因此仍然是真话。释放后若本次事务失败，下一次 ``load_current`` 会重新
        取租约，恢复到原状。

        宿主拒绝交还时（``host.remove`` 被 ``before_remove`` 闸门否决，例如面板还有
        未保存编辑）返回 False 且**不改变本对象的状态**：撤回动作应当在那里如实中止。
        """
        binding = self.binding
        if binding is None:
            return True
        if not binding.close():
            return False
        pin = getattr(binding.handle, "process_pin", None)
        if pin is not None and not getattr(pin, "closed", True):
            pin.close()
        self.binding = None
        self.context = None
        self._pending_receipt = None
        return True

    def load_current(self) -> OperationResult:
        if self._pending_receipt is not None:
            return self._confirm_receipt()
        if self.binding is not None:
            return self.refresh_authorization()
        try:
            state_result = self.service.store.read()
            state = state_result.state
            if state is None:
                if state_result.status == "lock_busy":
                    return self.service._result("awaiting_release", reason="state_lock_busy")
                return self.service._result("recovery_required", reason="install_state_unavailable")
            if state.pending_transaction:
                return self.load_pending(state.pending_transaction)
            if state.active is None:
                return self.service._result("idempotent", revision=state.revision, reason="not_installed")
            selection = self._resolve_current_selection("configuration")
            self._prepare_runtime()
            self.binding = self._bind(selection)
            raw = self.context_factory()
            if raw is None or getattr(raw, "owner", None) != selection.feature_id:
                raise PackageVerificationError("startup ports are invalid")
            self.context = self.host.bind_context(raw)
            self.binding.context = self.context
            if not _valid_execution_ports(self.context, selection.descriptor.execution_kind):
                raise PackageVerificationError("startup execution ports are invalid")
            self._attach_authority()
            return self.refresh_authorization()
        except Exception as exc:
            from .feature_package_transactions import LOCK_BUSY_REASONS
            from .feature_state_io import StateError

            if self.binding is None and isinstance(exc, StateError) and exc.code in LOCK_BUSY_REASONS:
                return self.service._result("awaiting_release", reason=exc.code)
            self.host.fault(self.service.store.feature_id, "startup_load_failed")
            return self.service._result("recovery_required", reason="startup_load_failed")

    def refresh_authorization(self) -> OperationResult:
        if self.binding is None:
            return self.service._result("awaiting_release", reason="startup_required")
        owner = self.binding.handle.descriptor.id
        from .feature_package_transactions import LOCK_BUSY_REASONS
        from .feature_state_io import StateError

        state_result = self.service.store.read()
        state = state_result.state
        if state is None:
            self.host.disable(owner)
            reason = "state_lock_busy" if state_result.status == "lock_busy" else "install_state_unavailable"
            return self.service._result("awaiting_release" if reason in LOCK_BUSY_REASONS else "recovery_required", reason=reason)
        if state.pending_transaction or state.active != self.binding.handle.descriptor.version:
            self.host.disable(owner)
            return self.service._result("awaiting_release", reason="version_change_requires_restart")
        try:
            purpose = "execution" if state.enabled else "configuration"
            selected = self._resolve_current_selection(purpose)
            self.binding.refresh_selection(selected)
            if state.enabled:
                self.host.enable(owner)
            else:
                self.host.disable(owner)
            return self.service._result("completed", revision=selected.revision)
        except Exception as exc:
            self.host.disable(owner)
            if isinstance(exc, StateError) and exc.code in LOCK_BUSY_REASONS:
                return self.service._result("awaiting_release", reason=exc.code)
            return self.service._result("recovery_required", reason="authorization_refresh_failed")

    def load_pending(self, operation_id: str) -> OperationResult:
        """Only startup/bootstrap calls this before any feature execution."""
        permit = self.service.startup_permit(operation_id, role=self.role)
        try:
            resolution = self.service.store.resolve_verified(self.service.verifier, purpose="startup", permit=permit)
            selection = FeatureVersionSelection.from_resolution(resolution)
            self._prepare_runtime()
            self.binding = self._bind(selection)
            raw_context = self.context_factory()
            if raw_context is None or getattr(raw_context, "owner", None) != selection.feature_id:
                raise PackageVerificationError("startup ports are invalid")
            self.context = self.host.bind_context(raw_context)
            self.binding.context = self.context
            if not _valid_execution_ports(self.context, selection.descriptor.execution_kind):
                raise PackageVerificationError("startup execution ports are invalid")
            self._attach_authority()
            pin = self.binding.handle.process_pin
            if pin is None:
                raise PackageVerificationError("production process pin is missing")
            self._pending_receipt = StartupLoadReceipt(permit, self.binding, self.context, os.getpid(), pin.lease_id, _RECEIPT_SEAL)
            return self._confirm_receipt()
        except Exception:
            # Do not serialize candidate exception text or clear an imported pin.
            if self.binding is not None:
                self.host.fault(self.binding.handle.descriptor.id, "startup_load_failed")
            return self.service._startup_failed(permit)

    def _confirm_receipt(self) -> OperationResult:
        receipt = self._pending_receipt
        assert receipt is not None and self.binding is not None
        result = self.service.confirm_startup(receipt.permit.operation_id, receipt=receipt)
        if result.status in ("completed", "idempotent"):
            # The commit can be durable while a subsequent authority read is
            # contended. Keep the real receipt/pin disabled for a retry rather
            # than treating a transient read failure as candidate load failure.
            authorized = self.refresh_authorization()
            if authorized.status != "completed":
                return authorized
            self._pending_receipt = None
        return result
