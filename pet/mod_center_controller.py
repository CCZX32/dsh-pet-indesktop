# -*- coding: utf-8 -*-
"""「MOD 中心」的逻辑层：一份本地清单 + 一条串行操作队列。

移植自 DLC 分支的 ``pet/mod_center_controller.py``，接线部分
按本仓库的宿主面重写。DLC 那版直接抓 ``dialog.feature_host`` / ``dialog.feature_managers``
/ ``dialog._mod_settings``，并靠 ``pet/mod_resource_ipc.py``（跨进程角色控制通道）把
「换装 / 释放占用」转给主进程；那条通道属 4.4b 淘汰语义，本线放弃（见
``.scratch/dlc-fusion/PLAN.md``）。本仓库的宿主面只有两处：设置页对话框（上游）与桌宠
窗口（``pet/modern_settings_dialog`` 的 ``parent()``；宿主壳 ``pet/overlay_shell.py``
的角色切换最终也落在同一个 ``on_switch_character`` 入口上）。

**本片只移植资源侧。** DLC 那版把「功能扩展」（可执行代码包）与「角色资源」放进同一条
队列，前者的运行闭包是官方功能包安装信任链（``feature_package_transactions`` /
``feature_install_state`` / ``feature_version_lease`` / ``local_package_intents`` +
``pet.plugins`` 验签，合计约 3900 行），本仓库没有这些模块，``pet/plugins`` 又属本片
禁止引入面——范围与判定见 ``.scratch/dlc-fusion/S1b-1-HANDOFF.md`` 的「未落」节。
因此 :data:`KINDS` 只声明 ``角色资源``；非资源包在导入时按包自己声明的 ``kind`` 如实
拒绝（不是静默失败，也不是"看起来成功了"）。队列/结果协议（``perform`` /
``import_source`` / ``result`` / ``batch_finished``）与 DLC 逐位一致，功能扩展侧接回时
的落点就是这里。

**已知缺陷指针（不在本片修）**：DLC 侧用 ZIP 导入**功能扩展**示例包会报
``worker_probe_failed``（探针沙箱只在冻结版创建），改「导入目录」正常；角色资源包走
ZIP 正常。原文在 DLC 分支 ``docs/modding/USER-GUIDE.md`` 的「已知缺陷」节与
``.scratch/mod-authoring-v1/HANDOFF.md``；本线 S4 随文档移植原文，ZIP 探针缺陷单列一轮
（``PLAN.md``「ZIP 导入探针缺陷」）。本文件只按包声明拒收非资源包，不假装已修。

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

#: 本片支持的 MOD 种类。功能扩展侧接入后在这里追加（见模块 docstring）。
KINDS = (KIND_RESOURCE,)

#: 包声明里表示「角色资源」的种类值（DLC 的 ``manifest.json`` 口径）。
RESOURCE_MANIFEST_KIND = "content"
#: 功能扩展包的声明标记：出现任一即判为「本版本接不了」，只读探测、不 import 不执行。
_FEATURE_MANIFEST_MARKERS = ("execution_kind", "format_version", "factory")
_MANIFEST_LIMIT = 2 * 1024 * 1024
_MANIFEST_NAME = "manifest.json"

#: 单次 ``perform`` 允许的动作（与 DLC 同一集合）。
ACTIONS = frozenset({"enable", "disable", "delete", "rollback", "use"})
#: 需要先确认「没有桌宠正在用这个包」的动作（存储层同样会调放行判据，这里提前问一次）。
_RELEASING_ACTIONS = frozenset({"disable", "delete", "rollback"})


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


def unsupported_package_message(source: Path) -> str:
    """非资源包的如实拒绝语；空串 = 交给资源存储层按内容校验。

    判据只有包**自己声明**的东西（``kind`` 与功能扩展的标记字段），不做猜测：
    缺 ``kind`` 的手工角色包照样往下走，由 ``pet.mod_management`` 的边界校验回答
    「是不是一个完整的角色包」。
    """
    manifest = declared_manifest(source)
    kind = manifest.get("kind")
    if isinstance(kind, str) and kind and kind != RESOURCE_MANIFEST_KIND:
        return "本版本只支持角色资源包；功能扩展包的安装子系统尚未接入。"
    if any(marker in manifest for marker in _FEATURE_MANIFEST_MARKERS):
        return "本版本只支持角色资源包；功能扩展包的安装子系统尚未接入。"
    return ""


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
        self.busy = False
        self._queue: deque = deque()
        self._results: list = []
        self._current = None
        self._usage = LiveUsage()
        self._closed = False
        self._finished.connect(self._resource_finished, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------- 清单

    def entries(self) -> list[ModEntry]:
        try:
            rows = self.resources.entries()
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("MOD catalog unavailable")
            return []
        return sorted(rows, key=lambda row: (row.kind, row.name.casefold(), row.id))

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
        message = unsupported_package_message(source)
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
        if action in _RELEASING_ACTIONS:
            refusal = self._release_refusal(entry)
            if refusal:
                self._finish(ModOutcome(False, refusal, True))
                return
        self._background(lambda: self._apply(action, entry))

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

    # ------------------------------------------------------------- 收尾

    def _finish(self, outcome: ModOutcome) -> None:
        if self._current is None:
            return
        _action, entry, _source = self._current
        key = entry.key if isinstance(entry, ModEntry) else (entry or "")
        self._results.append((key, outcome))
        self.result.emit(key, outcome)
        self._current = None
        self.changed.emit()
        QTimer.singleShot(0, self._next)

    def close(self) -> None:
        self._closed = True
        self._queue.clear()
