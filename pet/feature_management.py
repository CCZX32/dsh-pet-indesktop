# -*- coding: utf-8 -*-
"""功能扩展的管理侧入口：只读发现 + 每 owner 一个管理器 + 进程级宿主装配。

Ported from the DLC branch ``pet/feature_management.py``；那一半在 DLC 里是
``FeatureManagementRuntime(QObject)``（事务提交、探针恢复、状态监视、生命周期 IPC、
上下文装配……），依赖本仓库没有的 LPAC 探针链与官方内置域（识屏 / AI），属「宿主
管理面」的后续切片。本片落地**本地用户自选包**那一半：

``discover_local_feature_ids(config)``
    只读发现（片 1 已落）：安装状态账本是唯一权威，启动时遍历 ``plugins/*/``
    找出**已经落地过状态**的 owner（含首次安装被打断、只有 pending 事务、没有版本
    目录的那一种）。零 Qt、只读、不导入包代码。

``FeatureManagementManager(QObject)``
    一个 owner 的事务服务 + 启动装载 + 结果回报。``ModCenterController`` 只认契约
    （``service`` / ``submit`` / ``submit_local_source`` / ``result_ready`` /
    ``state_changed`` / ``last_result``），本类就是那份契约的真身。

``LocalFeatureRuntime``
    进程级宿主（``AppShell`` 持有，**会话横跨菜单关闭**）：一个 ``FeatureHost`` +
    每个 owner 一个管理器 + GUI 挂载面（``GenericModMounts``，仅 core 角色）。
    ``DialogModHost.extensions()`` / ``feature_route()`` / 设置面板都从这里取。

**线程纪律（本片最容易写错的一条）**。事务服务（``FeaturePackageTransactionService``
及其租约/状态账本）是 Qt-free 的，跑在管理器自己的后台线程上；而宿主状态机
（``FeatureHost`` / ``ContributionRegistry``）只能在自己的 GUI 线程上动——
``ContributionRegistry.check_thread()`` 是硬约束。所以：

* 后台线程只做"状态账本"那一半，绝不调用 ``host.enable`` / ``host.disable`` /
  ``host.provide`` / ``host.remove``；
* 事务结果一律经**队列信号**回到 GUI 线程，宿主转换在 :meth:`FeatureManagementManager._sync_host`
  里做，之后才 ``result_ready.emit``（控制器在同一个回调里读 ``last_result``）；
* 草稿快照由 GUI 线程在派发前喂给 :class:`pet.plugins.lifecycle.FeatureHostLifecycle`，
  后台线程只读（见 ``pet/plugins/lifecycle.py``）。

**自检器**：本线注入 :class:`LocalUserTrustSelfChecker`（显式用户信任 + 一次装前子进程
预检），取代默认的 fail-closed ``SubprocessFeatureSelfChecker``（无 OS 沙箱时它一律拒装）。
两者都不声称任何 OS 隔离：本地 MOD 是用户自己选择信任的 Python 代码，与桌宠同权限运行；
子进程预检（:mod:`pet.feature_package_preflight`）只在"拒绝"方向有权威——包装不起来、
``create_host()`` 说的 owner 与清单不符，都在**装之前**如实拒掉，说行的那一半仍由宿主
自己按完整验签链重新回答。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .feature_host_bindings import bind_local_context, bind_screen_context
from .feature_package_preflight import LocalPackageProbe
from .feature_package_startup import ProductionFeatureStartup
from .feature_package_transactions import LOCK_BUSY_REASONS, FeaturePackageTransactionService
from .feature_ports import FeatureHostContext  # noqa: F401  （契约面：宿主上下文）
# 能力上限 / API 版本 / 本地包的验签策略只有一份，在零 Qt 的 feature_policy 里
# （作者侧打包脚本与构建门也要用同一份，它们不该为了两个常量把 PySide6 拉起来）。
# 这里再导出一次：既有的 from pet.feature_management import FEATURE_CAPABILITIES 照旧可用。
from .feature_policy import API_VERSION, FEATURE_CAPABILITIES, local_package_verifier  # noqa: F401
from .official_features import OFFICIAL_FEATURES, is_valid_feature_id
from .plugins.feature_host import FeatureHost
from .plugins.feature_packages import FeaturePackageLoader
from .plugins.lifecycle import FeatureHostLifecycle
from .plugins.package_binding import bind_verified_feature
from .plugins.package_trust import FeaturePackageVerifier, PackageVerificationError

_LOG = logging.getLogger(__name__)

#: 设置贡献的 scope（与菜单挂载的 ``GenericModMounts.scope`` 分开：两处生命周期不同）。
SETTINGS_SCOPE = "mod:v1:settings"

#: 事务结果里算「状态已经落盘」的三个（其余一律如实回报，不假装已完成）。
_SETTLED = frozenset({"completed", "idempotent", "awaiting_startup_confirmation"})

#: 需要先把宿主绑定交还才能继续的动作：它们要么删版本目录（卸载），要么换版本
#: （更新 / 回滚）——``FeaturePackageBinding`` 明确拒绝换版本复用，宿主 pin 也必须先释放。
_RELEASING_KINDS = frozenset({"uninstall", "rollback", "upgrade"})

#: 安装状态**干净读到**的样子（``FeatureInstallStateStore.read`` 的 status：三个正常态）。
#: 其余取值（``lock_busy`` / ``io_error`` / ``recovery_required`` / ``corrupt`` …）都算
#: "没读实"——见 :meth:`FeatureManagementManager._transaction_accepted`。
_CLEAN_STATE_READ = frozenset({"uninstalled", "enabled", "disabled"})


@dataclass(frozen=True)
class LocalUserTrustSelfChecker:
    """显式用户信任 + 一次子进程预检，**不是沙箱**。

    本仓库没有 LPAC 原生探针沙箱（``SubprocessFeatureSelfChecker.available is False``），
    默认装配会对任何非卸载操作以 ``self_check_sandbox_unavailable`` 如实拒绝——这是
    "验证不了就别执行"的纪律，不是缺陷。本地功能包走的是另一条**明确**的口子：
    用户自己挑了这份包 ⇒ 显式信任。于是这里只做三件不含糊的事：

    * 重新验签 / 指纹对账（``verifier.reverify``）——它仍然保证"跑的就是验过的那份字节"；
    * host-worker 声明下断言 worker 路径存在且**在版本目录内**；
    * 给上 ``probe`` 时（生产装配默认给），把包交给 :mod:`pet.feature_package_preflight`
      的**子进程**预检一次：装载得起来吗、``create_host()`` 说的 owner 与清单一致吗。
      探针只在"拒绝"方向有权威，说行的那一半仍由宿主自己重新验。

    它不声称任何 OS 隔离，也不做 capability 强制（``allowed_capabilities`` 是兼容上限）。
    """

    verifier: FeaturePackageVerifier
    #: 显式：默认的 fail-closed 不适用于"用户自己选的包"这条路径。
    available: bool = True
    #: 装前子进程预检；``None`` = 只做上面两条（历史行为，既有用例仍走这条）。
    probe: "LocalPackageProbe | None" = None

    def check(self, descriptor) -> "object":
        from .feature_package_transactions import RuntimePreparation

        try:
            self.verifier.reverify(descriptor)
        except (PackageVerificationError, OSError):
            return RuntimePreparation("failed", "self_check_verification_failed")
        if getattr(descriptor, "execution_kind", "host-only") == "host-worker":
            worker = getattr(descriptor, "worker_path", None)
            try:
                inside = worker is not None and Path(worker).is_file() and Path(worker).resolve().is_relative_to(Path(descriptor.root).resolve())
            except (OSError, ValueError):
                inside = False
            if not inside:
                return RuntimePreparation("failed", "self_check_worker_missing")
        if self.probe is not None:
            verdict = self.probe.run(descriptor, self.verifier)
            if not verdict.ok:
                return RuntimePreparation("failed", verdict.reason or "probe_failed")
            # 元信息只作诊断：安装状态里不存它，执行授权也不看它（探针不授权执行）。
            return RuntimePreparation(details={"probe": verdict.metadata.document()} if verdict.metadata else {})
        return RuntimePreparation()


class FeatureManagementManager(QObject):
    """一个 owner 的管理侧真值：事务服务 + 启动装载 + 结果回报。

    ``busy`` 覆盖**整个用户动作**（含"先预检、再放掉宿主、最后应用"这两段），所以
    两段之间不会有第二个命令挤进来。
    """

    result_ready = Signal(object)
    state_changed = Signal(object)
    busy_changed = Signal(bool)
    _finished = Signal(object)

    def __init__(self, config, host: FeatureHost, owner: str, *, role: str = "core", lifecycle=None, parent=None,
                 verifier: FeaturePackageVerifier | None = None, context_factory=None) -> None:
        super().__init__(parent)
        if not is_valid_feature_id(owner):
            raise ValueError("invalid feature owner")
        if role not in ("core", "settings"):
            raise ValueError("invalid feature host role")
        self.config, self.host, self.owner, self.role = config, host, owner, role
        self.lifecycle = lifecycle if lifecycle is not None else FeatureHostLifecycle()
        #: GUI 线程的派发前钩子（刷草稿快照），由 :class:`LocalFeatureRuntime` 接上。
        self.before_dispatch = None
        self._closed = threading.Event()
        self._inflight = 0
        self._auto_apply_requested = False
        #: 两段式的第一段是否已经把宿主绑定交还（第二段失败时据此装回旧版本）。
        self._released_for_apply = False
        self.last_operation = None
        self.last_result = self._result("idempotent", reason="not_installed")
        # 官方闭集包（识屏）由 attach_official 注入官方验签策略与 bind_screen_context；
        # 缺省保持本地 MOD 路径（local_package_verifier + bind_local_context）不变。
        self.verifier = verifier if verifier is not None else local_package_verifier(owner)
        self.service = FeaturePackageTransactionService(
            config.dir,
            self.verifier,
            self_checker=LocalUserTrustSelfChecker(self.verifier, probe=LocalPackageProbe()),
            runtime=self.lifecycle,
        )
        self.startup = ProductionFeatureStartup(
            self.service,
            host,
            runtime_directory=Path(config.dir) / "feature-runtime" / owner,
            context_factory=context_factory if context_factory is not None else (lambda: bind_local_context(config, owner)),
            binder=self._binder,
            role=role,
        )
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------- 只读面

    @property
    def busy(self) -> bool:
        return self._inflight > 0

    def _result(self, *args, **kwargs):
        kwargs["feature_id"] = self.owner
        from .feature_package_transactions import OperationResult

        return OperationResult(*args, **kwargs)

    def inspect(self):
        return self.service.inspect()

    def _binder(self, host, service, selection, runtime_directory, core_roots):
        """宿主注入的 binder：从**已验签的字节**装载 host 代码并绑端口（片 1 已落）。"""
        loader = FeaturePackageLoader(self.verifier)
        return bind_verified_feature(
            host,
            loader,
            selection.descriptor,
            runtime_directory=runtime_directory,
            core_roots=core_roots,
            selection=selection,
            lease_coordinator=service.leases,
            enabled=False,
        )

    # ------------------------------------------------------------- 启动

    def bootstrap(self) -> None:
        """GUI 线程：先重放被打断的事务（元数据那一半），再把当前版本装进宿主。

        重放期间把 ``service.runtime`` 摘掉（DLC 同款）：恢复是**元数据**路径，
        不该在启动的半路上触发 GUI 侧的释放准备；装载由下面这次 ``load_current``
        按落盘后的状态重新走一遍。
        """
        runtime = self.service.runtime
        self.service.runtime = None
        try:
            recovered = self.service.recover_pending()
        except Exception:
            _LOG.exception("feature recovery failed: %s", self.owner)
            recovered = self._result("recovery_required", reason="recovery_failed")
        finally:
            self.service.runtime = runtime
        if recovered.status not in _SETTLED:
            self.last_result = recovered
            return
        self._record_load(self._load_current())

    def _load_current(self):
        try:
            return self.startup.load_current()
        except Exception:
            _LOG.exception("feature load failed: %s", self.owner)
            self.host.fault(self.owner, "startup_load_failed")
            return self._result("recovery_required", reason="startup_load_failed")

    def _transaction_accepted(self) -> bool:
        """事务是否**已经被接受**（``state.pending_transaction`` 是唯一权威）。

        只有**干净读到**的安装状态才算数：读不出来、或读到的是恢复态（``recovery_required``
        / ``corrupt``）都按"已接受"处理。这一问只有一个用途——决定要不要把当前落盘的版本
        装回宿主，而装回一旦走错路就会把宿主打成 ``fault``（见 ``_sync_host``），所以宁可
        少做一件事，也不做错一件。

        读的是 ``store.read()`` 而不是 ``service.inspect()``：后者会把"状态没读出来"一并
        报成 ``pending_transaction is None``，正好与本方法的 fail-closed 方向相反。
        """
        try:
            result = self.service.store.read()
        except Exception:
            _LOG.exception("feature install state unreadable: %s", self.owner)
            return True
        if result.state is None or result.status not in _CLEAN_STATE_READ:
            return True
        return result.state.pending_transaction is not None

    # --------------------------------------------------------- 命令入口

    def submit(self, command: str, value=None, *, confirmation_token=None, expected_revision=None, auto_apply=None) -> bool:
        """**GUI 线程**调用：接受一个动作；返回 False = 忙（请稍后重试）。

        ``auto_apply`` 缺省：``uninstall`` / ``rollback`` 是**一次用户动作**（点了删除 /
        回滚就该做完），它们的两段式在本类内部走完；导入/更新由控制器显式给
        ``submit_local_source(auto_apply=True)``（那条路要先把计划回报出去）。
        """
        if self._closed.is_set() or self.busy:
            return False
        actions = {
            "inspect": self.service.inspect,
            "recover": self.service.recover_pending,
            "gc": self.service.collect_garbage,
            "rollback": self.service.preflight_rollback,
            "uninstall": self.service.preflight_uninstall,
            "install": lambda: self.service.preflight_install(value),
            "import_disabled": lambda: self.service.preflight_install(value, enabled=False),
            "upgrade": lambda: self.service.preflight_upgrade(value),
            "apply": lambda: self.service.apply(value, confirmation_token=confirmation_token),
            "cancel": lambda: self.service.cancel_preflight(value),
            "enable": lambda: self.service.set_enabled(value, expected_revision=expected_revision),
        }
        action = actions.get(command)
        if action is None:
            self.result_ready.emit(self._result("rejected", reason="management_command_invalid"))
            return False
        if command == "apply":
            # 控制器对"事务尚未接受"的失败会用**同一个 plan** 再确认一次
            # （``ModCenterController._retry_apply``）。重试必须跑在与第一段相同的
            # **已交还**状态下，否则 ``_sync_host`` 为 M2 装回的那份绑定会把自己的
            # 版本 pin 带上，把重试永远挡在 ``version_in_use`` 上（见 ``_rearm_apply``）。
            action = self._rearm_apply(value, action)
        self._auto_apply_requested = bool(command in ("uninstall", "rollback") if auto_apply is None else auto_apply)
        # 只有"准备元数据 / 接受新版本"这几条会因为别的进程短暂持锁而值得原样重试；
        # enable=True 同理（要重新验签活动版本）。其余一律如实回报。
        retry_metadata = command in ("install", "import_disabled", "upgrade", "uninstall", "rollback") or (
            command == "enable" and value is True
        )
        self._dispatch(action, command, retry_metadata=retry_metadata)
        return True

    def submit_local_source(self, source, *, auto_apply=False, enabled=True) -> bool:
        """导入 / 更新一个本地包：先按它有界清单确认是**本 owner** 的包，再进事务。"""
        from .local_package_intents import route_local_package

        if self._closed.is_set() or self.busy:
            return False
        try:
            route = route_local_package(source)
        except (OSError, RuntimeError, TypeError, ValueError):
            self.result_ready.emit(self._result("rejected", reason="local_package_route_invalid"))
            return False
        if route.feature_id != self.owner:
            self.result_ready.emit(self._result("rejected", reason="local_package_target_invalid"))
            return False
        try:
            inspection = self.service.inspect()
        except Exception:
            self.result_ready.emit(self._result("rejected", reason="management_state_unavailable"))
            return False
        command = "upgrade" if inspection.active is not None else ("install" if enabled else "import_disabled")
        if not self.submit(command, route.source, auto_apply=auto_apply):
            return False
        return True

    # ---------------------------------------------------------- 后台执行

    def _dispatch(self, action, command: str, *, retry_metadata: bool) -> None:
        """GUI 线程：计数、刷草稿快照，然后把事务那一半丢到后台线程。"""
        self._inflight += 1
        self.busy_changed.emit(True)
        refresher = self.before_dispatch
        if callable(refresher):
            try:
                refresher()  # GUI 线程：把草稿取成快照，后台只读它
            except Exception:
                _LOG.exception("feature draft snapshot failed: %s", self.owner)
        self._start(action, command, retry_metadata=retry_metadata)

    def _start(self, action, command: str, *, retry_metadata: bool) -> None:
        threading.Thread(
            target=self._run,
            args=(action, command, retry_metadata),
            name="feature-management-" + self.owner,
            daemon=False,
        ).start()

    def _run(self, action, command: str, retry_metadata: bool) -> None:
        try:
            result = action()
            # 元数据读取与刚发现的 Core 可能短暂持锁：保持这一次**显式用户操作**
            # 忙态，在同一批输入上重试；版本冲突/无效包/活代码占用永不在这里重试。
            if retry_metadata:
                for delay in (0.1, 0.25, 0.5, 1.0, 2.0):
                    if not hasattr(result, "reason") or result.reason not in LOCK_BUSY_REASONS:
                        break
                    if self._closed.wait(delay):
                        return
                    result = action()
        except Exception:
            _LOG.exception("feature management failed: %s", self.owner)
            result = self._result("failed", reason="management_background_failed")
        if not self._closed.is_set():
            try:
                self._finished.emit(result)
            except RuntimeError:
                pass

    # ---------------------------------------------------- GUI 线程：收口

    def _deliver(self, result) -> None:
        if self._closed.is_set():
            self._settle()
            return
        if (
            getattr(result, "phase", None) == "awaiting_confirmation"
            and getattr(result, "plan", None) is not None
            and self._auto_apply_requested
        ):
            # 两段式全程算一个用户动作：busy 不放开，中间态不外报（控制器只认终态）。
            self._auto_apply_requested = False
            plan = result.plan
            if not self._release_host(plan.kind):
                self.last_result = self._result("rejected", reason="unsaved_settings")
                self._settle()
                self.result_ready.emit(self.last_result)
                return
            # 第二段是**同一个**动作的续跑：不另外计数，也不在这里减计数
            # （否则两段之间 busy 会瞬时为假，第二个命令就能挤进来）。
            # ``_released_for_apply`` 记下"绑定已经交还"：第二段失败时，旧绑定要装回来
            # （见 ``_sync_host``），否则交还就是净损失。
            self._released_for_apply = True
            QTimer.singleShot(0, lambda: self._apply_plan(plan))
            return
        self._auto_apply_requested = False
        if hasattr(result, "status"):
            self.last_operation = result
            self._sync_host(result)
        else:  # 不走 OperationResult 的异常路径：如实回报，不碰宿主
            self.last_result = result
        self._settle()
        if getattr(result, "status", None) in _SETTLED or getattr(result, "status", None) == "awaiting_release":
            try:
                from .mod_catalog import publish_catalog_change

                publish_catalog_change(self.config.dir)
            except (OSError, ValueError):
                _LOG.debug("catalog change notification failed", exc_info=True)
        self.result_ready.emit(result)

    def _apply_plan(self, plan) -> None:
        if self._closed.is_set():
            return
        self._start(lambda: self.service.apply(plan, confirmation_token=plan.confirmation_token), "apply", retry_metadata=False)

    def _settle(self) -> None:
        self._inflight = max(0, self._inflight - 1)
        self.busy_changed.emit(self._inflight > 0)

    def _release_host(self, kind: str) -> bool:
        """GUI 线程：动版本目录前先把宿主绑定交还（放掉进程 pin、停 Runtime）。

        只有 ``uninstall`` / ``rollback`` / ``upgrade`` 需要这一步：卸载要删版本目录、
        更新与回滚要换版本，两者都要求租约全 free 且版本不再被本进程 pin 住。
        """
        if kind not in _RELEASING_KINDS:
            return True
        if self.startup.binding is None:
            return True
        if self.startup.release():
            return True
        # 宿主拒绝交还（例如刚取到的草稿快照里还有未保存编辑）：如实中止，不硬来。
        _LOG.warning("feature host refused to release: %s", self.owner)
        return False

    def _rearm_apply(self, plan, action):
        """GUI 线程：重跑一段``apply``之前把宿主**重新交还**（拿不动就如实回报）。

        控制器的重试阶梯（``_retry_apply``）用同一个 plan 再确认一次，而重试要跑在与
        第一段相同的**已交还**状态下：``_sync_host`` 为 M2 装回的那份绑定会重新占住
        版本 pin，重试于是被本进程自己挡在 ``version_in_use`` 上——而且重试超时也解不开
        （挡路的不是别的程序，是这只桌宠自己）。交还之后照常走事务：这一趟要还是没落定，
        ``_sync_host`` 会再装回一次。

        宿主要是在这个当口拒绝交还（面板里有未保存草稿），就当这一趟本来就不该跑：
        如实回报 ``unsaved_settings``，不进事务。
        """
        kind = getattr(plan, "kind", None)
        if not self._release_host(kind):
            return lambda: self._result("rejected", reason="unsaved_settings")
        # 与第一段（``_deliver`` 的自动续跑那一段）同一口径：绑定已经交还出去了，这一趟
        # 要还是没落定，就得靠 ``_sync_host`` 装回来。非交还类（``install``）本来没交还
        # 过，装回也就无从谈起。
        self._released_for_apply = kind in _RELEASING_KINDS
        return action

    def _sync_host(self, result) -> None:
        """GUI 线程：把**已经落盘**的状态落到宿主，并把装载结果记进 ``last_result``。

        控制器在 ``result_ready`` 的回调里读 ``last_result`` 判断"能用不能用"，所以
        这一步必须发生在 ``result_ready.emit`` 之前。
        """
        if getattr(result, "status", None) not in _SETTLED:
            if self._released_for_apply:
                # 两段式的第二段没落定，而第一段已经把宿主绑定交还了（``host.remove``
                # 之后菜单与设置已经从界面上消失）。此时**当前落盘的**版本仍是原来那一份
                # ——把它重新装回宿主：用户看到的应当是"这次操作失败"，而不是"失败 +
                # 菜单不见了，重启才回来"。
                self._released_for_apply = False
                if self._transaction_accepted():
                    # 事务已经被接受（``state.pending_transaction`` 是唯一权威）：落盘的
                    # active 已经指向候选版本，装回会走 ``load_pending`` 的启动确认路，
                    # 而本进程不是那个启动方（``startup_permit`` 以 ``not_awaiting_startup``
                    # 拒绝）——"装回"于是变成一次带假理由的 ``host.fault``。这种局面交给
                    # 启动确认那条路，这里只如实回报事务的结论。
                    self.last_result = result
                else:
                    self._record_load(self._load_current())
                return
            self.last_result = result
            return
        self._released_for_apply = False
        if getattr(result, "status", None) == "awaiting_startup_confirmation":
            operation_id = getattr(result, "operation_id", None)
            if not operation_id:
                self.last_result = result
                return
            self._record_load(self._confirm_pending(operation_id))
            return
        try:
            state_result = self.service.store.read()
        except Exception:
            _LOG.exception("feature state read failed: %s", self.owner)
            self.last_result = self._result("recovery_required", reason="install_state_unavailable")
            return
        state = state_result.state
        if state is None:
            self.last_result = self._result("recovery_required", reason="install_state_unavailable")
            return
        if state.active is None:
            self._record_load(self._result("idempotent", revision=state.revision, reason="not_installed"))
            return
        binding = self.startup.binding
        if binding is not None and not binding.closed and binding.handle.descriptor.version != state.active:
            # 版本被换掉：绑定必须重来（binding 明确拒绝换版本复用）。
            self.startup.release()
        self._record_load(self._load_current())

    def _confirm_pending(self, operation_id: str):
        try:
            return self.startup.load_pending(operation_id)
        except Exception:
            _LOG.exception("feature startup confirmation failed: %s", self.owner)
            self.host.fault(self.owner, "startup_load_failed")
            return self._result("recovery_required", reason="startup_load_failed")

    def _record_load(self, result) -> None:
        self.last_result = result
        self.state_changed.emit(result)
        return result

    # ------------------------------------------------------------- 收口

    def refresh_from_ledger(self) -> None:
        """**GUI 线程**：把宿主收敛到**当前落盘**的安装状态（跨进程变更的消费侧）。

        独立设置进程改完账本只落一枚修订令牌（``mod_catalog.publish_catalog_change``），
        本进程的宿主不会自己知道。这里复用 ``load_current`` 的既有决策链：
        被打断的事务照启动口径重放、未安装就空转、已有绑定走 ``refresh_authorization``
        按 ``state.enabled`` 启停宿主——那边停了，这边的 Runtime 也得停。
        本进程自己的事务在途时不插一手：那条路自己会经 ``_deliver`` 收口。
        """
        if self._closed.is_set() or self.busy:
            return
        self._record_load(self._load_current())

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._auto_apply_requested = False
        # 宿主进程 pin 故意不在这里释放（与片 1 同口径）：导入过的代码留到进程退出。


class LocalFeatureRuntime:
    """进程级功能扩展宿主；``AppShell``（core）或设置对话框（settings）持有。

    **会话横跨菜单关闭**：宿主是长寿命对象，菜单/面板每次弹出即建即用——撤销因此是
    结构性的（未挂载的 owner 根本不渲染），不需要在菜单关掉时做任何事。

    ``role="settings"`` 的宿主**只** provide 与按需 settings_factory，没有挂载面
    （``mounts is None``）：它永不构造 Runtime、永不启 Worker。
    """

    def __init__(self, config, *, role: str = "core") -> None:
        if role not in ("core", "settings"):
            raise ValueError("invalid feature host role")
        self.config, self.role = config, role
        self.lifecycle = FeatureHostLifecycle()
        self.host = FeatureHost()
        self.managers: dict[str, FeatureManagementManager] = {}
        self.panels: dict[str, object] = {}
        self.mounts = None if role == "settings" else self._build_mounts()
        self._unsubscribe = self.host.subscribe(self._on_state)
        for owner in discover_local_feature_ids(config):
            self.attach(owner)
        # 官方闭集（识屏包）：Core 自有链，不走本地导入路由，但账本发现同口径。
        for owner in discover_official_feature_ids(config):
            self.attach_official(owner)

    @property
    def scope(self) -> str:
        return self.mounts.scope if self.mounts is not None else ""

    def _build_mounts(self):
        from .mod_runtime import GenericModMounts

        return GenericModMounts(self.host, self._context_for)

    def _context_for(self, owner: str):
        manager = self.managers.get(owner)
        return getattr(manager.startup, "context", None) if manager is not None else None

    # ------------------------------------------------------------- 装配

    def attach(self, owner: str) -> FeatureManagementManager | None:
        """GUI 线程：为一个 owner 建管理器并把它装进宿主（幂等）。"""
        if not is_valid_feature_id(owner) or owner in OFFICIAL_FEATURES:
            return None
        existing = self.managers.get(owner)
        if existing is not None:
            return existing
        try:
            manager = FeatureManagementManager(self.config, self.host, owner, role=self.role, lifecycle=self.lifecycle)
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("feature manager could not be created: %s", owner)
            return None
        self.managers[owner] = manager
        manager.before_dispatch = self.refresh_drafts
        # 宿主侧的第二道草稿闸门：卸载/换版本要走 host.remove(owner)，有草稿就拒绝
        # （与事务层的 draft_blocked 是同一条判据的两个入口，读同一份快照）。
        self.host.before_remove(owner, lambda owner=owner: not self.lifecycle.drafts(owner))
        manager.bootstrap()
        return manager

    def attach_official(self, owner: str) -> FeatureManagementManager | None:
        """**Core 自有**的官方包入口：官方验签策略 + 官方宿主绑定（DLC 识屏包线）。

        与 :meth:`attach` 的差异：验签走 :func:`official_package_verifier`（能力上限 =
        官方登记闭集），上下文走 ``bind_screen_context``（凭据/偏好/窗口/桌面四端口）。
        本地导入路由（``route``）依旧拒收官方 id——冒名 guard 不变；这里只接受 Core
        自己点名的 owner。当前只接识屏包（其余官方 id 的宿主绑定属聊天包线）。
        """
        from .feature_policy import official_package_verifier

        if owner not in OFFICIAL_FEATURES:
            raise ValueError("invalid feature owner")
        existing = self.managers.get(owner)
        if existing is not None:
            return existing
        try:
            manager = FeatureManagementManager(
                self.config,
                self.host,
                owner,
                role=self.role,
                lifecycle=self.lifecycle,
                verifier=official_package_verifier(owner),
                context_factory=lambda: bind_screen_context(
                    self.config, authorized=lambda: self.host.enabled(owner), host=self.host
                ),
            )
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("official feature manager could not be created: %s", owner)
            return None
        self.managers[owner] = manager
        manager.before_dispatch = self.refresh_drafts
        self.host.before_remove(owner, lambda owner=owner: not self.lifecycle.drafts(owner))
        manager.bootstrap()
        return manager

    def route(self, source) -> str | None:
        """读一次包自己的**有界清单**（不导入、不执行），为它建好管理器。

        这是 ``ModCenterController.feature_route`` 的宿主侧实现：注册表由安装状态导出，
        而安装状态只能靠一次导入改变——所以"这个 id 还没注册"不能反过来否掉一次导入，
        否则首次安装永远进不去（见 D2 spec §7.4-1）。

        **未知 owner 一律按第三方 DLC 接受**（Phase 5A 的显式导入口径）；唯一例外是
        官方登记表里的 owner：那条链是 Core 自有的，本地包占不了它的名字，这里如实
        答不上来（``None``），由 ``unsupported_package_message`` 给出可照做的拒绝语。
        """
        from .local_package_intents import route_local_package

        try:
            route = route_local_package(source)
        except (OSError, ValueError, RuntimeError, TypeError):
            return None
        if route.is_official:
            return None
        self.attach(route.feature_id)
        return route.feature_id

    # --------------------------------------------------------- 跨进程收敛

    def refresh_catalog(self) -> None:
        """**GUI 线程**：MOD 账本被**别的进程**改过后，把本宿主收敛到落盘状态。

        消费侧触发源是修订令牌（``mod_catalog.publish_catalog_change``，操作落盘后
        写 ``mod-catalog.revision``）：重新按账本发现 owner（那边新装的包不用重启
        就在这里出现），再让每个既有管理器按落盘状态刷新授权（那边停用的，这边的
        Runtime 停掉）。全程幂等：本进程自己事务落盘同样会写令牌，再来一遍只是
        一次无害的重复读。
        """
        for owner in discover_local_feature_ids(self.config):
            self.attach(owner)
        for manager in tuple(self.managers.values()):
            manager.refresh_from_ledger()

    # ------------------------------------------------------------- 宿主面

    def extensions(self) -> dict:
        """``feature_id -> 管理器``（``DialogModHost.extensions()`` 的真值）。"""
        return dict(self.managers)

    def manager(self, owner: str):
        return self.managers.get(owner)

    def startup(self, owner: str):
        manager = self.managers.get(owner)
        return getattr(manager, "startup", None) if manager is not None else None

    def menu_owners(self) -> tuple[str, ...]:
        """当下真的挂着菜单贡献的 owner（未挂载的 owner 根本不渲染）。"""
        if self.mounts is None:
            return ()
        return tuple(
            owner
            for owner in self.host.owners()
            if self.host.registry.list(owner=owner, scope=self.mounts.scope, kind="menu")
        )

    # --------------------------------------------------------- 设置面板面

    def settings_panel(self, owner: str, parent=None):
        """GUI 线程：按 owner 造/复用一块设置面板（没有装载好的绑定 = None）。"""
        existing = self.panels.get(owner)
        if existing is not None and not getattr(existing, "disposed", False) and shiboken6.isValid(existing):
            return existing
        self.panels.pop(owner, None)
        manager = self.managers.get(owner)
        context = self._context_for(owner)
        if manager is None or context is None:
            return None
        handle = self.host.settings(owner, SETTINGS_SCOPE)
        if handle is None:
            return None
        try:
            component = handle.create(context, parent)
        except Exception:
            _LOG.exception("feature settings component failed: %s", owner)
            handle.revoke()
            return None
        from .settings_mod_panel import OwnerSettingsPanel

        try:
            panel = OwnerSettingsPanel(owner, component, title=self.display_name(owner), lifecycle=self.lifecycle, parent=parent)
        except Exception:
            _LOG.exception("feature settings container failed: %s", owner)
            _dispose_component(component)
            handle.revoke()
            return None
        panel.destroyed.connect(lambda *_args, handle=handle: handle.revoke())
        self.panels[owner] = panel
        return panel

    def prepare_feature_revocation(self, owner: str, parent=None) -> bool:
        """撤回（停用/删除/回滚/更新）前的 GUI 预检：有草稿就问三键。"""
        panel = self.panels.get(owner)
        if panel is None or not shiboken6.isValid(panel):
            return True
        from .settings_mod_panel import prepare_revocation

        return prepare_revocation(panel, parent)

    def refresh_drafts(self) -> None:
        """**GUI 线程**：把每个开着面板的草稿取成快照（派发前调用）。"""
        for owner, panel in tuple(self.panels.items()):
            if getattr(panel, "disposed", False) or not shiboken6.isValid(panel):
                self.panels.pop(owner, None)
                self.lifecycle.note_drafts(owner, ())
                continue
            try:
                panel.push_drafts()
            except Exception:
                _LOG.exception("feature draft snapshot failed: %s", owner)

    def display_name(self, owner: str) -> str:
        """面板标题 = 包的显示名（读它自己的有界清单），读不到就用 owner。"""
        manager = self.managers.get(owner)
        service = getattr(manager, "service", None)
        if service is None:
            return owner
        try:
            info = service.inspect()
            if info.active is None:
                return owner
            from .mod_center_controller import declared_manifest

            metadata = declared_manifest(service.store.root / "versions" / info.active)
        except (OSError, ValueError, RuntimeError):
            return owner
        return str(metadata.get("name") or owner)

    # ------------------------------------------------------------- 收口

    def _on_state(self, owner: str, state: str) -> None:
        if state in ("absent", "fault"):
            self._dispose_panel(owner)

    def _dispose_panel(self, owner: str) -> None:
        panel = self.panels.pop(owner, None)
        if panel is None:
            return
        try:
            # 面板自己会清草稿快照；这里兜一次，防止 dispose 半路抛。
            self.lifecycle.note_drafts(owner, ())
            panel.dispose()
        except Exception:
            _LOG.exception("feature settings panel could not be disposed: %s", owner)

    def close(self) -> None:
        """唯一收口点：``AppShell._on_about_to_quit`` 里**先**调它，再收 workers。"""
        try:
            self._unsubscribe()
        except Exception:
            _LOG.debug("feature host unsubscribe failed", exc_info=True)
        for owner in tuple(self.panels):
            self._dispose_panel(owner)
        # 先把每个 owner 停掉（撤销菜单/执行），再收挂载面：进程要走了，宿主状态机
        # 不该停在"还开着"上——托盘/菜单在退出链里还读得到它。
        for owner in self.host.owners():
            try:
                self.host.disable(owner)
            except Exception:
                _LOG.exception("feature could not be disabled at shutdown: %s", owner)
        mounts, self.mounts = self.mounts, None
        if mounts is not None:
            try:
                mounts.close()
            except Exception:
                _LOG.exception("feature mounts could not be closed")
        for owner, manager in tuple(self.managers.items()):
            try:
                manager.close()
            except Exception:
                _LOG.exception("feature manager could not be closed: %s", owner)
            self.lifecycle.note_drafts(owner, ())


def _dispose_component(component) -> None:
    method = getattr(component, "dispose", None)
    try:
        if callable(method):
            method()
        else:
            delete = getattr(component, "deleteLater", None)
            if callable(delete):
                delete()
    except Exception:
        _LOG.debug("feature settings component could not be disposed", exc_info=True)


def discover_local_feature_ids(config) -> tuple[str, ...]:
    """Return installed user-selected feature IDs without importing package code.

    The install-state directory is the durable discovery index.  Official IDs
    stay on the explicit Core-owned path; every other syntactically valid ID
    is eligible for a generic management runtime only after its own verifier
    and startup path re-check the package manifest.
    """
    from .feature_install_state import FeatureInstallStateStore
    from .official_features import OFFICIAL_FEATURES, is_valid_feature_id

    root = Path(config.dir) / "plugins"
    try:
        entries = tuple(root.iterdir())
    except OSError:
        return ()
    discovered: list[str] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir() or entry.name in OFFICIAL_FEATURES:
            continue
        if not is_valid_feature_id(entry.name):
            continue
        try:
            state = FeatureInstallStateStore(config.dir, feature_id=entry.name).read()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        # A first install can stop after acceptance but before versions exist.
        # Discover its pending transaction so normal startup can replay it.
        if state.state is not None and (state.state.versions or state.state.pending_transaction):
            discovered.append(entry.name)
        elif state.status == "lock_busy":
            # A notification is not replayed after an unchanged read stamp.
            # Retain the valid owner for normal bounded startup retry; this does
            # not authorize/import anything until the ledger can be verified.
            discovered.append(entry.name)
    return tuple(sorted(discovered))


def discover_official_feature_ids(config) -> tuple[str, ...]:
    """官方闭集里**已有安装账本**的 owner（与本地发现同口径，方向相反）。

    官方包不进本地发现（防冒名路由不变）；它们的启动回放走 :meth:`attach_official`。
    """
    from .feature_install_state import FeatureInstallStateStore

    discovered: list[str] = []
    for owner in OFFICIAL_FEATURES:
        try:
            state = FeatureInstallStateStore(config.dir, feature_id=owner).read()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if state.state is not None and (state.state.versions or state.state.pending_transaction):
            discovered.append(owner)
        elif state.status == "lock_busy":
            discovered.append(owner)
    return tuple(discovered)


__all__ = [
    "API_VERSION",
    "FEATURE_CAPABILITIES",
    "FeatureManagementManager",
    "LocalFeatureRuntime",
    "LocalUserTrustSelfChecker",
    "discover_local_feature_ids",
    "discover_official_feature_ids",
]
