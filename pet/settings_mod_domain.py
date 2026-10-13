# -*- coding: utf-8 -*-
"""设置页「扩展管理」域：MOD 中心的宿主面 + 整页装配。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算（``tests/
test_architecture.py``）没有余量，本域的主体是「谁能动活桌宠」的宿主判定与整页装配，
与对话框框体无关——按本仓库既有口径（``settings_file_interpret`` / ``settings_network``
/ ``settings_quiet`` 都是同一个原因拆出来的），对话框只留一处
``settings_mod_domain.install_mod_domain(self)`` 接线。

**宿主面（本模块的主要职责）**：DLC 侧的 MOD 中心靠 ``pet/mod_resource_ipc.py``
（QLocalServer 跨进程角色控制通道）问主进程「谁在用这个包」「把这只宠换到这个角色」；
那条通道属 4.4b 淘汰语义、本线放弃（``.scratch/dlc-fusion/PLAN.md``）。本仓库的等价物
是**设置页所属的桌宠窗口**（``dialog.parent()``）上的 ``on_switch_character``
（capture/legacy 拓扑的 ``AppShell`` 与 overlay 壳的 ``OverlayShell.switch_character``
共用这个入口）。可观察范围随之收窄，如实体现在两条能力上：

=========================  ============================================================
能力                        本仓库怎么答
=========================  ============================================================
「使用」（换装）            有窗口 ⇒ **记下请求、设置窗关闭时执行**（换角色会重建那只窗，
                            而设置窗是它的子窗口，当场换=把设置窗一起销毁；见
                            ``DialogModHost.use_resource``）；没有窗口（独立设置进程、
                            overlay 壳没有 PetWindow）⇒ 按钮置灰并说明从右键菜单换装
「谁在用这个包」（放行判据） 活桌宠 = runtime 标记文件（``slot_manager``，pid 探活）；
                            逐只读它自己的档案角色，编辑中的那只读设置页自己的配置
动文件的动作                停用/删除/回滚/替换旧版本先问放行判据；答不上来就**拒绝**，
                            不猜（DLC 的 IPC 判据同样是"问不到就拒绝"）
=========================  ============================================================

两条腿是互补的：窗口给得出**素材目录**（精确到"这个包正被渲染"），运行时标记 + 档案
给得出**角色 id**（独立设置进程唯一读得到的东西）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import catalog
from .mod_catalog import publish_catalog_change
from .mod_center_controller import LiveUsage, ModCenterController
from .mod_center_ui import ModCenterWidget
from .mod_management import ModEntry, ModOutcome
from .settings_widgets import SettingRow, SettingsSection

_LOG = logging.getLogger(__name__)

#: 运行时标记文件名里的槽位标签（``pet-runtime-v2-<pid>-slot-<N>.json``）。
_SLOT_LABEL = re.compile(r"slot-(\d+)\Z")

#: 「使用」不可用时按钮上的说明（没有窗口可依附：独立设置进程，或宿主没挂窗口）。
USE_HINT = "本次设置页没有连到桌宠窗口：请从桌宠右键菜单「切换角色」换装。"


def _live_slots(data_root: Path) -> list[int]:
    """当前活着的桌宠槽位表（runtime 标记 + pid 探活；旧名单窗名 = 主实例 0）。

    标记文件由桌宠自己在启动/移动时写、退出时删；判活走 ``slot_manager.pid_alive``
    的同一口径，不另写一套。槽位号取自标记文件名
    （``pet-runtime-v2-<pid>-slot-<N>.json``），旧名 ``runtime-<pid>.json`` 是单窗
    形态 ⇒ 主实例 0。
    """
    from . import slot_manager as slot_manager_mod

    slots: list[int] = []
    for path in slot_manager_mod.list_runtime_marker_files(data_root):
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid", 0))
        except (OSError, ValueError, AttributeError, TypeError):
            continue  # 半写/损坏：判不出 pid 就跳过（与 slot_manager 同口径，不删文件）
        if pid <= 0 or not slot_manager_mod.pid_alive(pid):
            continue
        match = _SLOT_LABEL.search(path.stem)
        slots.append(int(match.group(1)) if match else 0)
    return list(dict.fromkeys(slots))


def _slot_character(data_root: Path, slot: int) -> str:
    """某槽位档案里记着的角色（读不到给空串 = 这一只答不上来）。"""
    from . import pet_profiles

    try:
        profile = pet_profiles.read_slot_profile(data_root, slot)
    except Exception:  # 档案坏了不该炸设置页：答不上来即可
        _LOG.debug("MOD 判定：读槽档案失败 slot=%s", slot, exc_info=True)
        return ""
    value = profile.value("character")
    return str(value or "")


class DialogModHost:
    """设置页对 MOD 中心的宿主面（DLC ``ResourceClient`` 的进程内等价物）。"""

    def __init__(self, dialog):
        self.dialog = dialog
        self.data_root = Path(dialog.config.dir)
        self.window = dialog.parent()
        #: 已记录、等设置窗关闭时执行的换装请求（见 :meth:`use_resource`）。
        self.pending_use = ""

    # ------------------------------------------------------------- 能力

    def _use_hook(self):
        hook = getattr(self.window, "on_switch_character", None)
        return hook if callable(hook) else None

    @property
    def can_use(self) -> bool:
        return self._use_hook() is not None

    @property
    def use_hint(self) -> str:
        """不能换装时按钮上那句说明（能换就是空串）。"""
        return "" if self.can_use else USE_HINT

    # --------------------------------------------------------- 只读判定

    def _owner_character(self) -> str:
        try:
            return str(self.dialog.config.get("character") or "")
        except Exception:
            _LOG.debug("MOD 判定：读当前角色失败", exc_info=True)
            return ""

    def _window_asset_dirs(self) -> tuple[Path, ...]:
        """本设置页所属那只桌宠正在渲染的素材目录（读不出就是空）。"""
        path = getattr(getattr(self.window, "lib", None), "_asset_dir", None)
        return (Path(path),) if path is not None else ()

    def live_usage(self) -> LiveUsage:
        """派发前快照（**GUI 线程**调用，此后工作线程只读）。"""
        live = _live_slots(self.data_root)
        dirs = self._window_asset_dirs()
        if not live and not dirs:
            return LiveUsage(verified=True)  # 没人在跑：动文件伤不到活桌宠
        ids = [_slot_character(self.data_root, slot) for slot in live]
        owner = self._owner_character()
        if owner:
            ids.append(owner)
        verified = bool(dirs) or all(ids)
        return LiveUsage(verified=verified, asset_dirs=dirs,
                         character_ids=tuple(dict.fromkeys(ids)))

    def extensions(self) -> dict:
        """功能扩展注册表（``feature_id -> 管理器``）；本版本恒为空。

        功能扩展的管理器要接上官方功能包安装信任链（``feature_package_transactions``
        等）与宿主运行时，本仓库尚未接入——**这里如实返回空表**而不是给一个占位管理器：
        ``ModCenterController`` 见空表就不列「功能扩展」行，导入功能扩展包时给出
        「宿主未接入」的拒绝语（见 ``pet/mod_center_controller.py`` 的模块 docstring）。
        接回时把管理器填进这张表即可，控制器侧不用改。
        """
        return {}

    # ------------------------------------------------------------- 动作

    def use_resource(self, entry: ModEntry) -> ModOutcome:
        """「使用」= 把本设置页所属的那只桌宠换装到该角色包（**关设置页时执行**）。

        为什么不当场换：换角色会**重建**那只桌宠的窗口（``AppShell.switch_character``
        → ``_build_window``：建新窗 + 对旧窗 ``deleteLater``），而设置窗是旧窗的
        **子窗口**——本机实测（offscreen，Qt 6）父窗 deleteLater 之后子对话框
        ``shiboken6.isValid`` 即为 False，当场换装等于把设置窗一起销毁。所以这里只
        记下请求，等 ``finished``（那时设置窗本来就在销毁）再由
        :meth:`apply_pending_use` 执行；没有窗口可依附（独立设置进程、overlay 壳没有
        PetWindow）时如实拒绝并指路右键菜单。
        """
        if not entry.enabled:
            return ModOutcome(False, "请先启用角色资源")
        if self._use_hook() is None:
            return ModOutcome(False, USE_HINT)
        if entry.character_id and entry.character_id == self._owner_character():
            return ModOutcome(True, "这只桌宠已经在该角色上")
        self.pending_use = entry.character_id
        return ModOutcome(True, "已记录换装：关闭设置页后生效")

    def apply_pending_use(self) -> None:
        """设置窗关闭时执行记下的换装（幂等；没有请求、或窗口已不可用则什么都不做）。"""
        character_id, self.pending_use = self.pending_use, ""
        if not character_id:
            return
        hook = self._use_hook()
        if hook is None:
            return
        try:
            hook(character_id)
        except Exception:
            _LOG.exception("MOD 换装失败: %s", character_id)

    def catalog_changed(self) -> None:
        """失效通知：跨进程令牌 + 进程内 catalog 缓存（角色体框是 ``lru_cache``）。"""
        publish_catalog_change(self.data_root)
        catalog.character_body_box.cache_clear()
        catalog.character_head_box.cache_clear()


def build_mod_rows(dialog) -> list[SettingRow]:
    """本域的设置行（控件由 :func:`install_mod_domain` 建好，行壳每次域重建时新建）。"""
    return [
        SettingRow(
            "mod_center",
            "已安装的扩展与资源",
            "在这里导入、启用、停用、更新和删除扩展包。新导入的包默认停用；"
            "正在使用的角色包要先换装才能停用或删除。",
            dialog.mod_center,
            stacked=True,
        )
    ]


def install_mod_domain(dialog) -> QWidget:
    """「扩展管理」域整页（幂等：域导航重建时复用同一个控制器与控件）。"""
    if getattr(dialog, "mod_controller", None) is None:
        host = DialogModHost(dialog)
        dialog.mod_host = host
        dialog.mod_controller = ModCenterController(host, parent=dialog)
        dialog.mod_center = ModCenterWidget(dialog.mod_controller, dialog, kinds=dialog.mod_controller.kinds)
        # 关窗即收尾：批处理的后续格子不再继续动文件（正在跑的那一格仍会跑完）；
        # 记下的换装请求此时执行（见 DialogModHost.use_resource 的时序说明）。
        dialog.finished.connect(dialog.mod_controller.close)
        dialog.finished.connect(host.apply_pending_use)
    content = QWidget(dialog)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(SettingsSection("MOD 中心", build_mod_rows(dialog), content))
    layout.addStretch(1)
    return content


__all__ = ["DialogModHost", "USE_HINT", "build_mod_rows", "install_mod_domain"]
