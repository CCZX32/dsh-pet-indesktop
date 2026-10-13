# -*- coding: utf-8 -*-
"""「MOD 中心」的逻辑层：一份本地清单 + 一条串行操作队列。

移植自 DLC 分支的 ``pet/mod_center_controller.py``，接线部分
按本仓库的宿主面重写。DLC 那版直接抓 ``dialog.feature_host`` / ``dialog.feature_managers``
/ ``dialog._mod_settings``，并靠 ``pet/mod_resource_ipc.py``（跨进程角色控制通道）把
「换装 / 释放占用」转给主进程；那条通道属 4.4b 淘汰语义，本线放弃（见
``.scratch/dlc-fusion/PLAN.md``）。本仓库的宿主面只有两处：设置页对话框（上游）与桌宠
窗口（``pet/modern_settings_dialog`` 的 ``parent()``；宿主壳 ``pet/overlay_shell.py``
的角色切换最终也落在同一个 ``on_switch_character`` 入口上）。

**本片（S1c）接回功能扩展侧。** DLC 那版把「功能扩展」（可执行代码包）与「角色资源」放进同
一条队列，靠 ``dialog.feature_managers`` 里每只包一个 ``FeatureManagementManager`` 驱动。
本仓库没有那套管理器（它的闭包是功能扩展宿主运行时 + 官方功能包安装信任链的一整层），
所以照 S1b-2 定下的同一手法处理：**控制器只认契约，注册表由宿主提供**。

宿主额外契约（可选能力，缺省 = 没有任何功能扩展）：

``extensions() -> Mapping[str, object]``
    **GUI 线程**调用：``feature_id -> 扩展管理器``。管理器契约（与 DLC 的
    ``FeatureManagementManager`` 同名同义，控制器只用这几项）：

    ``service``
        安装信任链的事务服务（``FeaturePackageTransactionService`` 或同形状）；
        ``service.inspect()`` 给出 ``active`` / ``enabled`` / ``pending_transaction``，
        ``service.store.root / "versions" / active`` 是该版本的安装目录。
    ``submit(action, *args, expected_revision=...) -> bool``
        接受一个安装/启停/卸载动作（``enable`` / ``disable`` / ``uninstall`` /
        ``rollback`` / ``apply``）；返回 False = 忙、请稍后重试。
    ``submit_local_source(source, auto_apply=True, enabled=False) -> bool``
        导入一个本地包目录/ZIP。
    ``result_ready`` / ``state_changed`` 信号，及 ``last_result``。
        前者（``object`` 一个 ``OperationResult`` 参数）驱动:meth:`_feature_finished`
        的结果映射与忙等重试阶梯；后者转成 ``changed``。

DLC 原文在 ``.scratch/dlc-fusion/src/mod_center_controller.py``；本文件保留同一套队列、
结果协议与重试阶梯，只把 `managers` 换成宿主给的 `extensions` 注册表。功能扩展的
**包声明路由**（``local_package_intents.route_local_package``）与 `FeatureManagementManager`
本身仍未移植——本仓库的宿主面（``pet/settings_mod_domain.py``）目前返回空注册表，
所以「功能扩展」这一格在真实运行里还不会出现；接回时的落点就是 ``extensions()``。

**ZIP 导入探针缺陷（S4 收口，逐环判定）**：DLC 侧用 ZIP 导入**功能扩展**示例包会报
``worker_probe_failed``，处置结果分两半，**不要**笼统表述为"已修复"：

* **可修的那一环已修**——冻结版 onedir 的密封依赖目录查找。
  ``_dsh_probe_native.pyd`` 只存在于执行文件自己的 ``_internal`` 里；安装路径一长，
  ``LoadLibrary`` 就以「文件名或扩展名太长」失败，探针永远拿不到沙箱证据。修复在
  ``pet/frozen_runtime_paths.py``（S4 新增）+ ``pet/workers/screen_entry.py`` 首行接线；
  before/after 原始输出见 ``.scratch/dlc-fusion/S4-HANDOFF.md``。
* **筑在其上的那一环在本拓扑不存在**——LPAC 原生探针沙箱与其
  ``_internal/feature-probe`` 密封 bundle。本仓库没有这条构建流水线，
  ``FeaturePackageTransactionService`` 因此在更上游就以
  ``self_check_sandbox_unavailable`` **如实拒绝**功能包导入（``tests/
  test_feature_package_transactions.py::test_default_selfcheck_fails_closed_without_os_sandbox``
  是这条纪律的守卫）——所以 ZIP 与「导入目录」两条路在本仓库收敛到同一处拒绝，
  DLC 报告里的"目录可以、ZIP 不行"这个差异**没有**复现面。

原文在 DLC 分支 ``docs/modding/USER-GUIDE.md`` 的「已知缺陷」节与
``.scratch/mod-authoring-v1/HANDOFF.md``。本文件只按包声明路由，不假装已修。

宿主面（Host）——本仓库的面：

``data_root: Path``
    MOD 托管根（= ``Config.dir``）。托管布局（``characters/`` / ``mod-disabled/`` /
    ``mod-versions/`` / ``mod-staging``）见 :mod:`pet.mod_management` 的模块 docstring。
``live_usage() -> LiveUsage``
    **GUI 线程**调用：派发一批操作前取「谁正在用哪个角色包」的快照。工作线程只读这张
    不可变快照，绝不碰窗口对象（Qt 对象只在属主线程上动；这是 DLC 那次跨进程 IPC 在
    进程内的等价物：IPC 把「问主进程」变成了一次线程安全的问答，这里把它变成一张快照）。
``use_resource(entry) -> ModOutcome``
    **GUI 线程**调用：「使用」= 把本设置页所属的那只桌宠换装到该角色包。
``catalog_changed() -> None``
    操作完成后的失效通知：至少写一次 ``mod-catalog.revision`` 令牌
    （``pet.mod_catalog.publish_catalog_change``），进程内宿主再顺手清 catalog 缓存
    （角色体框是 ``lru_cache``，覆盖同名包时不失效就会拿旧框）。
``extensions() -> Mapping[str, object]``
    见上；可选，缺省按「没有任何功能扩展」处理。
"""
from __future__ import annotations

import json
import logging
import threading
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal

import shiboken6

from .mod_management import KIND_RESOURCE, ModEntry, ModOutcome, ResourceMods

_LOG = logging.getLogger(__name__)

#: 功能扩展（可执行代码包）这一格的种类名。DLC 用的就是同一个字面量，MOD 中心 UI
#: 的筛选按钮直接按 ``KINDS`` 生成，所以这里加一项就等于给 UI 加一个筛选。
KIND_EXTENSION = "功能扩展"

#: 本片支持的 MOD 种类（顺序即 UI 筛选按钮顺序）。
KINDS = (KIND_RESOURCE, KIND_EXTENSION)

#: 包声明里表示「角色资源」的种类值（DLC 的 ``manifest.json`` 口径）。
RESOURCE_MANIFEST_KIND = "content"
#: 功能扩展包的声明标记：出现任一即判为「功能扩展」。
_FEATURE_MANIFEST_MARKERS = ("execution_kind", "format_version", "factory")
_MANIFEST_LIMIT = 2 * 1024 * 1024
_MANIFEST_NAME = "manifest.json"

#: 单次 ``perform`` 允许的动作（与 DLC 同一集合）。
ACTIONS = frozenset({"enable", "disable", "delete", "rollback", "use"})
#: 需要先确认「没有桌宠正在用这个包」的动作（存储层同样会调放行判据，这里提前问一次）。
_RELEASING_ACTIONS = frozenset({"disable", "delete", "rollback"})
#: 忙等重试阶梯（毫秒），与 DLC 逐位一致；两处不同状态各记一次尝试数。
_RETRY_DELAYS = (100, 250, 500, 1000, 2000)
#: 事务层报「锁忙」时仍算可重试的原因（DLC 从 ``feature_package_transactions`` 取；
#: 本仓库把它写死在这里，避免为一个常量把事务层拉进 UI 进程的导入图）。
_LOCK_BUSY_REASONS = frozenset({"management_lock_busy", "leases_lock_busy", "state_lock_busy", "lock_busy"})


@dataclass(frozen=True)
class LiveUsage:
    """「谁正在用哪个角色包」的派发前快照（GUI 线程取，工作线程只读）。

    ``verified=False`` = 宿主答不上来（既不认识窗口、也读不到运行时标记）：此时按
    「可能在用」处理，拒绝会动文件的操作而不是猜（DLC 对无活实例的判据是"没有实例就
    通过"，本字段把这个语义显式化：**读得到、且读到的就是全部**才算 verified）。
    """

    verified: bool = False
    asset_dirs: tuple[Path, ...] = ()
    character_ids: tuple[str, ...] = ()


def _is_within(candidate: Path, package: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(package)
    except (OSError, ValueError):
        return False


def _package_is_in_use(entry: ModEntry, usage: LiveUsage) -> bool:
    """该包是否仍被某只活桌宠使用（素材目录判据优先，其次角色 id）。"""
    if usage.asset_dirs:
        try:
            package = entry.path.resolve()
        except OSError:
            return True
        return any(_is_within(path, package) for path in usage.asset_dirs)
    # 独立设置进程看不到素材库，只能看"每只活桌宠档案里写着哪个角色"。
    return bool(entry.character_id) and entry.character_id in usage.character_ids


def declared_manifest(source: Path) -> dict:
    """只读取出包根部的 ``manifest.json``（有界；读不到/不是对象一律给空 dict）。"""
    path = Path(source)
    try:
        if path.is_dir():
            raw = (path / _MANIFEST_NAME).read_bytes()
        elif path.is_file():
            with zipfile.ZipFile(path) as archive:
                name = next((item for item in archive.namelist()
                             if item.replace("\\", "/") == _MANIFEST_NAME), None)
                if name is None:
                    return {}
                member = archive.getinfo(name)
                if member.file_size > _MANIFEST_LIMIT:
                    return {}
                raw = archive.read(name)
        else:
            return {}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {}
    if len(raw) > _MANIFEST_LIMIT:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def declared_kind(manifest: dict) -> str:
    """包**自己声明**的种类：``content`` = 角色资源，功能扩展标记出现 = 功能扩展。

    判据只有声明本身，不做猜测：缺 ``kind`` 又没有任何功能扩展标记的手工角色包返回
    空串，交给 :mod:`pet.mod_management` 的边界校验回答「是不是一个完整的角色包」。
    """
    kind = manifest.get("kind")
    if isinstance(kind, str) and kind and kind != RESOURCE_MANIFEST_KIND:
        return kind
    if any(marker in manifest for marker in _FEATURE_MANIFEST_MARKERS):
        return KIND_EXTENSION
    return ""


def unsupported_package_message(source: Path, *, extensions=()) -> str:
    """非资源包的如实拒绝语；空串 = 交给资源存储层按内容校验。

    ``extensions`` = 已注册的功能扩展 id 集合。一个功能扩展包只有在**声明的 id 已有
    注册表条目**（即本进程真的能驱动它的安装信任链）时才被路由；否则如实说清是哪一个
    环节没接上，而不是静默失败。缺 ``kind`` 的手工角色包照样往下走。
    """
    manifest = declared_manifest(source)
    if declared_kind(manifest) != KIND_EXTENSION:
        kind = manifest.get("kind")
        if isinstance(kind, str) and kind:
            return "本版本只支持角色资源包；该包声明的种类是「" + kind[:32] + "」。"
        return ""
    declared_id = manifest.get("id")
    if isinstance(declared_id, str) and declared_id in set(extensions):
        return ""
    return "这个包是功能扩展包，但本版本还没有接上它对应的功能扩展宿主：安装子系统未接入。"


class ModCenterController(QObject):
    """串行执行 MOD 操作，结果与忙碌态通过信号回报。

    一次只跑一个操作（``busy``）：清单是同一份磁盘状态的视图，并行操作只会让
    「先停用再删除」这类批处理互相踩；队列化之后批处理的每一格都有确定的先后。
    """

    changed = Signal()
    busy_changed = Signal(bool)
    result = Signal(str, object)
    batch_finished = Signal(object)
    _finished = Signal(object)

    kinds = KINDS

    #: 宿主能力转发：桩后端可以不带这两项，那按"能换装"处理（控件据此置灰按钮）。
    @property
    def can_use(self) -> bool:
        return bool(getattr(self.host, "can_use", True))

    @property
    def use_hint(self) -> str:
        return str(getattr(self.host, "use_hint", "") or "")

    def __init__(self, host, parent: QObject | None = None):
        super().__init__(parent)
        self.host = host
        self.resources = ResourceMods(host.data_root, prepare_removal=self._may_remove)
        self.extensions: dict[str, object] = {}
        self.busy = False
        self._queue: deque = deque()
        self._results: list = []
        self._current = None
        self._usage = LiveUsage()
        self._closed = False
        self._connected: set[str] = set()
        self._load_retries = 0
        self._apply_retries = 0
        self._finished.connect(self._resource_finished, Qt.ConnectionType.QueuedConnection)
        self.connect_extensions()

    # ----------------------------------------------------- 功能扩展注册表

    def connect_extensions(self) -> None:
        """把宿主给的功能扩展管理器接上结果信号；已接过的按 id 去重。

        DLC 的对应方法是 ``connect_managers``（靠 ``dialog.feature_managers`` 逐个接）。
        这里同样在每次 ``extensions()`` 之后调用，新增的包（例如刚导入的那一只）当次
        即可回报结果。**Qt 对象只在属主线程上接**——本方法只在 GUI 线程调用。
        """
        for owner, manager in dict(self.extension_managers()).items():
            if owner in self._connected:
                continue
            self._connected.add(owner)
            self.extensions[owner] = manager
            ready = getattr(manager, "result_ready", None)
            if ready is not None:
                ready.connect(lambda result, owner=owner: self._feature_finished(owner, result))
            state = getattr(manager, "state_changed", None)
            if state is not None:
                state.connect(lambda *_: self.changed.emit())

    def extension_managers(self) -> dict:
        """宿主提供的 ``feature_id -> 管理器``；宿主答不上来 = 没有功能扩展。"""
        provider = getattr(self.host, "extensions", None)
        if provider is None:
            return {}
        try:
            values = provider()
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("Extension registry unavailable")
            return {}
        return dict(values) if values else {}

    def feature_route(self, source: Path) -> str | None:
        """问一次宿主：「这个包该交给哪个功能扩展？」答不上来 = ``None``（现状）。

        死锁修复（见 ``.scratch/dlc-fusion/D2-RUNTIME-SPEC.md`` §7.4-1）：注册表由
        **安装状态**导出，而安装状态只能通过导入改变——所以"这个 id 还没注册"
        不能反过来否掉一次导入，否则首次安装一个功能包永远进不去。宿主在这一步
        读的是包自己的有界清单（不导入、不执行），答得出 owner 就当场把该 owner 的
        管理器装上，本方法再让控制器重新接一遍注册表。

        没有这个缝的宿主（含全部既有测试替身）行为与之前**完全一致**。
        """
        provider = getattr(self.host, "feature_route", None)
        if provider is None:
            return None
        try:
            owner = provider(source)
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("Feature route unavailable")
            return None
        return owner if isinstance(owner, str) and owner else None

    # ------------------------------------------------------------- 清单

    def entries(self) -> list[ModEntry]:
        rows = self._extension_entries()
        try:
            rows.extend(self.resources.entries())
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("MOD catalog unavailable")
        return sorted(rows, key=lambda row: (row.kind, row.name.casefold(), row.id))

    def _extension_entries(self) -> list[ModEntry]:
        """已安装的功能扩展行（与 DLC 同判据：读安装目录里的清单做展示元数据）。"""
        self.connect_extensions()
        rows = []
        for owner, manager in tuple(self.extensions.items()):
            service = getattr(manager, "service", None)
            if service is None:
                continue
            try:
                info = service.inspect()
                if info.active is None:
                    continue
                path = service.store.root / "versions" / info.active
                metadata = declared_manifest(path)
                rows.append(
                    ModEntry(
                        str(owner),
                        KIND_EXTENSION,
                        str(metadata.get("name") or owner),
                        str(info.active),
                        str(metadata.get("description") or ""),
                        bool(info.enabled),
                        path,
                        pending="等待自然退出后完成操作" if info.pending_transaction else "",
                    )
                )
            except (OSError, ValueError, RuntimeError):
                _LOG.warning("extension metadata unavailable: %s", owner)
        return rows

    # --------------------------------------------------------- 操作入口

    def _begin(self, jobs) -> bool:
        if self.busy or self._closed:
            return False
        self.busy = True
        # 快照必须在**派发前、GUI 线程上**取：此后工作线程只读这张不可变表。
        self._usage = self.host.live_usage()
        self.busy_changed.emit(True)
        self._results = []
        self._queue.extend(jobs)
        self._next()
        return True

    def perform(self, action: str, keys) -> bool:
        if action not in ACTIONS:
            return False
        visible = {entry.key: entry for entry in self.entries()}
        return self._begin([(action, visible[key], None) for key in dict.fromkeys(keys) if key in visible])

    def import_source(self, path, expected: str | None = None) -> bool:
        """导入一个所选 ZIP / 目录；``expected`` = 被「更新」那一行的键。"""
        try:
            source = Path(path).resolve(strict=True)
        except (OSError, ValueError) as exc:
            self.result.emit(expected or "", ModOutcome(False, "导入失败：请选择完整的 MOD ZIP 或包目录。" + str(exc)[:160]))
            return False
        self.connect_extensions()
        manifest = declared_manifest(source)
        if declared_kind(manifest) == KIND_EXTENSION and manifest.get("id") in self.extensions:
            owner = str(manifest["id"])
            if expected is not None and expected != KIND_EXTENSION + ":" + owner:
                self.result.emit(expected, ModOutcome(False, "导入失败：更新文件不是同一个包。"))
                return False
            return self._begin([("import_feature", owner, source)])
        routed = self.feature_route(source)
        if routed is not None and declared_kind(manifest) == KIND_EXTENSION and routed == manifest.get("id"):
            # 首次安装：宿主刚刚为这只包建好管理器，注册表要重新接一遍才看得见它。
            self.connect_extensions()
            if expected is not None and expected != KIND_EXTENSION + ":" + routed:
                self.result.emit(expected, ModOutcome(False, "导入失败：更新文件不是同一个包。"))
                return False
            return self._begin([("import_feature", routed, source)])
        message = unsupported_package_message(source, extensions=self.extensions)
        if message:
            self.result.emit(expected or "", ModOutcome(False, message))
            return False
        return self._begin([("import", expected, source)])

    # ------------------------------------------------------------- 队列

    def _may_remove(self, entry: ModEntry) -> bool:
        """存储层动一个已安装包之前的放行判据（工作线程调用，只读快照）。

        答不上来（``verified=False``）时拒绝：宁可不做，也不把正在渲染中的包搬走
        ——移动/删除之后桌宠还持有素材句柄，下次启动会因角色素材缺失而报错。
        """
        return self._release_refusal(entry) == ""

    def _release_refusal(self, entry: ModEntry) -> str:
        """不能动这个包时的**如实**原因（空串 = 可以动）。

        「正在用」与「答不上来」是两回事，文案必须分开：前者用户可以自己解决（换装），
        后者是宿主能力缺失——混成一句话会把「我没法确认」说成「你在用」。
        """
        if not self._usage.verified:
            return "无法确认桌宠是否正在使用这个角色包：请退出桌宠后再操作。"
        if _package_is_in_use(entry, self._usage):
            return "这只桌宠正在使用该角色包：请先换装或退出桌宠后再操作。"
        return ""

    def _next(self) -> None:
        # ``QTimer.singleShot(0, self._next)`` 可能在设置窗关闭之后才轮到：对话框
        # ``WA_DeleteOnClose``，它的子对象此时已被销毁——先验一次对象还活着，否则
        # 会往已删除的 C++ 对象上发信号（RuntimeError: Signal source has been deleted）。
        if self._closed or not shiboken6.isValid(self):
            return
        if not self._queue:
            self._current = None
            self.busy = False
            self.busy_changed.emit(False)
            self.changed.emit()
            self.batch_finished.emit(tuple(self._results))
            return
        self._current = self._queue.popleft()
        self._load_retries = 0
        self._apply_retries = 0
        action, entry, source = self._current
        if action == "use":
            # 换装是 GUI 线程的活（要动窗口与素材库），不进后台线程。
            self._finish(self.host.use_resource(entry))
            return
        if action == "import":
            conflict = self._import_conflict(source)
            if conflict:
                self._finish(ModOutcome(False, conflict, True))
                return
            self._background(lambda: self._install(source, entry))
            return
        if action == "import_feature":
            self._import_feature(str(entry), source)
            return
        if entry.kind == KIND_EXTENSION:
            self._extension_action(action, entry)
            return
        if action in _RELEASING_ACTIONS:
            refusal = self._release_refusal(entry)
            if refusal:
                self._finish(ModOutcome(False, refusal, True))
                return
        self._background(lambda: self._apply(action, entry))

    def _extension_action(self, action: str, entry: ModEntry) -> None:
        """把一个动作交给该功能扩展的管理器；管理器忙/答不上来 = 如实拒绝。"""
        manager = self.extensions.get(entry.id)
        if manager is None:
            self._finish(ModOutcome(False, "这个功能扩展已经不可用：请重新打开设置页。"))
            return
        submit = getattr(manager, "submit", None)
        if submit is None:
            self._finish(ModOutcome(False, "这个功能扩展的管理器不支持该操作。"))
            return
        try:
            if action in ("enable", "disable"):
                info = manager.service.inspect()
                accepted = submit("enable", action == "enable", expected_revision=info.revision)
            else:
                accepted = submit("uninstall" if action == "delete" else "rollback")
        except (OSError, ValueError, RuntimeError) as exc:
            _LOG.warning("extension action refused: %s", entry.id)
            self._finish(ModOutcome(False, "操作未完成：" + str(exc)[:160]))
            return
        if not accepted:
            self._finish(ModOutcome(False, "该包正在操作，请稍后重试"))

    def _import_feature(self, owner: str, source: Path) -> None:
        """导入一个本地功能扩展包：走该扩展管理器自己的本地源入口。"""
        manager = self.extensions.get(owner)
        submit = getattr(manager, "submit_local_source", None) if manager is not None else None
        if submit is None:
            self._finish(ModOutcome(False, "这个功能扩展已经不可用：请重新打开设置页。"))
            return
        try:
            accepted = submit(source, auto_apply=True, enabled=False)
        except (OSError, ValueError, RuntimeError) as exc:
            _LOG.warning("extension import refused: %s", owner)
            self._finish(ModOutcome(False, "导入未完成：" + str(exc)[:160]))
            return
        if not accepted:
            self._finish(ModOutcome(False, "导入未开始；该包可能正在操作中"))

    def _import_conflict(self, source: Path) -> str:
        """要替换的包正被使用时的如实拒绝（空串 = 可以继续导入）。

        这是**提前**问一次，只为让「更新」与「停用/删除」给同一句可照做的话；真正
        的权威判据仍在下游（``ResourceMods`` 在版本变化时自己调放行判据）。包声明的
        版本与现装版本相同 = 重复导入、根本不落盘，也就不必拦。
        """
        declared = declared_manifest(source)
        target_id = declared.get("id")
        if not isinstance(target_id, str) or not target_id:
            return ""
        current = next((row for row in self.resources.entries(include_unmanaged=False)
                        if row.id == target_id), None)
        if current is None or declared.get("version") == current.version:
            return ""
        return self._release_refusal(current)

    def _install(self, source: Path, expected: str | None) -> ModOutcome:
        expected_id = expected.split(":", 1)[1] if expected and ":" in expected else None
        previous = {row.id: row.version for row in self.resources.entries(include_unmanaged=False)}
        installed = self.resources.install(source, expected_id=expected_id)
        if previous.get(installed.id) == installed.version:
            return ModOutcome(True, "已存在，不重复导入")
        return ModOutcome(True, f"已导入 {installed.name}；" + ("保持启用" if installed.enabled else "点击启用即可使用"))

    def _apply(self, action: str, entry: ModEntry) -> ModOutcome:
        if action == "enable":
            return self.resources.set_enabled(entry.id, True)
        if action == "disable":
            return self.resources.set_enabled(entry.id, False)
        if action == "delete":
            return self.resources.remove(entry.id)
        return self.resources.rollback(entry.id)

    def _background(self, operation) -> None:
        def run() -> None:
            try:
                outcome = operation()
            except (OSError, ValueError, RuntimeError) as exc:
                _LOG.exception("MOD operation failed")
                outcome = ModOutcome(False, "操作未完成：" + str(exc)[:160])
            if not self._closed:
                self._finished.emit(outcome)

        threading.Thread(target=run, name="mod-resource-operation", daemon=False).start()

    def _resource_finished(self, outcome: ModOutcome) -> None:
        if not shiboken6.isValid(self):
            return
        try:
            self.host.catalog_changed()
        except (OSError, ValueError):
            _LOG.exception("MOD notification failed")
        self._finish(outcome)

    # ------------------------------------------------- 功能扩展的结果映射

    def _feature_finished(self, owner: str, result) -> None:
        """把事务层的 ``OperationResult`` 映射成一行如实的结果（DLC 同款阶梯）。

        - ``awaiting_startup_confirmation`` 算成功（状态已持久、等下次启动确认）；
        - 锁忙 / 生命周期所有者变化走 100→2000 ms 重试阶梯，超限再如实报；
        - ``awaiting_release`` 时先问一次「这次事务到底被接受了没有」，
          **不接受**的就别说成"已保存，等退出"（DLC 原话：never pretend a
          pre-acceptance wait is already a durable transaction）。
        """
        if self._current is None or self._closed:
            return
        action, entry, _source = self._current
        expected = entry if action == "import_feature" else getattr(entry, "id", None)
        status = getattr(result, "status", None)
        phase = getattr(result, "phase", None)
        if owner != expected or (phase == "awaiting_confirmation" and not getattr(result, "reason", None)):
            return
        if status in ("completed", "idempotent", "awaiting_startup_confirmation"):
            manager = self.extensions.get(owner)
            loaded = getattr(manager, "last_result", None)
            reason = getattr(loaded, "reason", None) if loaded is not None else getattr(result, "reason", None)
            if reason in _LOCK_BUSY_REASONS and self._retry_load(owner, result):
                return
            if action not in {"delete", "disable"} and loaded is not None and getattr(loaded, "status", None) not in {"completed", "idempotent"}:
                # 安装状态已持久，但这次加载没走完（例如宿主进了 fault）：两件事分开说，
                # 不许把"状态存下了"讲成"已经能用"。
                outcome = ModOutcome(False, "安装状态已保存，但加载未完成：" + str(getattr(loaded, "reason", None) or getattr(loaded, "status", None)))
            elif getattr(result, "status", None) == "idempotent" and getattr(result, "reason", None) == "same_version_same_digest":
                outcome = ModOutcome(True, "已存在，不重复导入")
            else:
                outcome = ModOutcome(True, {
                    "import_feature": "已导入；点击启用即可使用",
                    "enable": "已启用",
                    "disable": "已停用",
                    "delete": "已删除安装副本，个人数据保留",
                    "rollback": "已恢复上一版",
                }.get(action, "已完成"))
        elif status == "awaiting_release":
            if getattr(result, "plan", None) is not None and getattr(result, "reason", None) in {*_LOCK_BUSY_REASONS, "lifecycle_owners_changed"} and self._retry_apply(owner, result):
                return
            accepted = self._transaction_accepted(owner, result)
            outcome = (
                ModOutcome(False, "等待相关程序自然退出后完成操作", True)
                if accepted
                else ModOutcome(False, "操作尚未接受，请自然退出相关程序后重试")
            )
        else:
            outcome = ModOutcome(False, "操作未完成：" + str(getattr(result, "reason", None) or status))
        self.changed.emit()
        self._finish(outcome)

    def _transaction_accepted(self, owner: str, result) -> bool:
        """这次事务是否已落成 pending（唯一权威是安装状态的 ``pending_transaction``）。"""
        manager = self.extensions.get(owner)
        service = getattr(manager, "service", None)
        operation_id = getattr(result, "operation_id", None)
        if service is None or not operation_id:
            return False
        try:
            return service.inspect().pending_transaction == operation_id
        except (OSError, ValueError, RuntimeError):
            return False

    def _retry_load(self, owner: str, result) -> bool:
        """「加载撞锁」的阶梯重试（DLC 的 ``_load_retries``）：返回 True = 已排上。

        管理器自己会在重试期间再试一次加载；这里只是**再问一次**它的结果，
        不在控制器侧重复提交（DLC 原样）。
        """
        if self._load_retries >= len(_RETRY_DELAYS):
            return False
        delay = _RETRY_DELAYS[self._load_retries]
        self._load_retries += 1
        self._schedule(delay, lambda: self._feature_finished(owner, result))
        return True

    def _retry_apply(self, owner: str, result) -> bool:
        """「事务尚未接受」的阶梯重试（DLC 的 ``_apply_retries``）：用同一个 plan 再确认一次。

        为什么必须重试而不是直接报失败：停一个 Worker 可能在"准备"与"接受"之间
        把 owner 拿掉——状态变了，但**同一份计划与同一个确认令牌**照样是有效的，
        用户不该因为一次时序碰撞重来一遍。
        """
        plan = getattr(result, "plan", None)
        manager = self.extensions.get(owner)
        submit = getattr(manager, "submit", None)
        if plan is None or submit is None or self._apply_retries >= len(_RETRY_DELAYS):
            return False
        delay = _RETRY_DELAYS[self._apply_retries]
        self._apply_retries += 1

        def retry() -> None:
            if not submit("apply", plan, confirmation_token=plan.confirmation_token):
                self._feature_finished(owner, result)

        self._schedule(delay, retry)
        return True

    def _schedule(self, delay_ms: int, callback) -> None:
        """排一次重试，并再验一次「这格还是同一格」且对象还活着。"""
        current = self._current

        def guarded() -> None:
            if self._closed or not shiboken6.isValid(self) or self._current is not current:
                return
            callback()

        QTimer.singleShot(delay_ms, guarded)

    # ------------------------------------------------------------- 收尾

    def _finish(self, outcome: ModOutcome) -> None:
        if self._current is None:
            return
        action, entry, _source = self._current
        if action == "import_feature":
            key = KIND_EXTENSION + ":" + str(entry)
        elif isinstance(entry, ModEntry):
            key = entry.key
        else:
            key = entry or ""
        self._results.append((key, outcome))
        self.result.emit(key, outcome)
        self._current = None
        self.changed.emit()
        QTimer.singleShot(0, self._next)

    def close(self) -> None:
        self._closed = True
        self._queue.clear()
