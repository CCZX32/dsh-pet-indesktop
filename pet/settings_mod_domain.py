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
「谁在用这个包」（放行判据） 活桌宠 = runtime 标记文件（``slot_manager``，pid 探活）
                            + **overlay 拓扑**再并入持久化活跃集合
                            （``overlay-active-pets.json``，版本化：子宠是进程内
                            sprite，不写 marker，它们是这条拓扑的唯一身份真值）；
                            逐只读它自己的档案角色，编辑中的那只读设置页自己的配置
动文件的动作                停用/删除/回滚/替换旧版本先问放行判据；答不上来就**拒绝**，
                            不猜（DLC 的 IPC 判据同样是"问不到就拒绝"）
=========================  ============================================================

两条腿是互补的：窗口给得出**素材目录**（精确到"这个包正被渲染"），运行时标记 + 档案
给得出**角色 id**（独立设置进程唯一读得到的东西）。legacy（单窗）拓扑没有活跃集合
语义——那边 marker 就是唯一来源，留存的子宠身份并没有在跑，不参与判据。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
from shiboken6 import isValid

from . import catalog
from . import overlay_settings_command
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


def _active_set_slots(data_root: Path) -> tuple[int, ...] | None:
    """持久化活跃集合的槽位（overlay 拓扑下「谁在跑」的权威身份源）；读不出 = None。

    overlay 壳里只有主 sprite 写 runtime 标记（几何避让），spawn 的子宠不写——
    它们的存在只落在版本化的 ``overlay-active-pets.json``（生成/退出时原子落盘）。
    文件损坏/版本不认识一律答 None：占用判据宁可拒绝也不猜。
    """
    from . import pet_profiles

    try:
        active = pet_profiles.load_active_set(data_root)
    except Exception:  # 读活跃集合不该炸设置页：答不上来即可
        _LOG.debug("MOD 判定：读活跃集合失败", exc_info=True)
        return None
    return tuple(active.slots) if active.ok else None


class DialogModHost:
    """设置页对 MOD 中心的宿主面（DLC ``ResourceClient`` 的进程内等价物）。"""

    def __init__(self, dialog):
        self.dialog = dialog
        self.data_root = Path(dialog.config.dir)
        self.window = dialog.parent()
        #: 已记录、等设置窗关闭时执行的换装请求（见 :meth:`use_resource`）。
        self.pending_use = ""
        #: 扩展宿主：懒解析（见 :meth:`feature_host`）。``_UNSET`` 表示还没问过。
        self._feature_host = _UNSET
        #: 只建"自建宿主"的那个开关（见 :meth:`feature_host`）：只有真正装配了 MOD
        #: 中心页才置位——只建一个对话框不该顺带拉起一份扩展宿主。
        self.allow_own_host = False

    # ------------------------------------------------------- 扩展宿主

    def feature_host(self):
        """进程级扩展宿主；答不上来返回 ``None``（MOD 中心如实显示"宿主未接入"）。

        两条来源，按**拓扑**而不是按偏好选：

        * 有父窗 ⇒ 用**父窗那一份**（主进程 ``AppShell.feature_runtime``）。宿主是
          进程级单例，这里绝不另建第二份——两个宿主会在同一份安装状态上互相打架。
        * 没有父窗（独立设置进程 ``python -m pet --settings``）⇒ 按需建一份
          ``role="settings"`` 的宿主：只 provide + 按需 ``settings_factory``，
          **永不构造 Runtime、永不启 Worker**（见 ``pet/feature_management.py``）。
        """
        if self._feature_host is not _UNSET:
            return self._feature_host
        runtime = getattr(self.window, "feature_runtime", None)
        if runtime is None and self.dialog.parent() is None and self.allow_own_host:
            from .feature_management import LocalFeatureRuntime
            from .settings_slot_config import global_config_of

            try:
                # 扩展运行时是进程级；凭据作用域也必须与 Core 使用的全局身份一致。
                runtime = LocalFeatureRuntime(global_config_of(self.dialog.config), role="settings")
                self._owns_host = True
            except Exception:
                _LOG.exception("设置进程内装配扩展宿主失败；MOD 中心显示宿主不可用")
                runtime = None
        self._feature_host = runtime
        return runtime

    def shutdown(self) -> None:
        """设置窗关闭时的收口：只收**自建**的那一份（主进程那一份归 AppShell）。"""
        runtime = self._feature_host
        self._feature_host = _UNSET
        if runtime is None or not getattr(self, "_owns_host", False):
            return
        try:
            runtime.close()
        except Exception:
            _LOG.exception("关闭设置进程内的扩展宿主失败")

    def extensions(self) -> dict:
        """功能扩展注册表（``feature_id -> 管理器``）。

        真值来自 :class:`pet.feature_management.LocalFeatureRuntime`：每个 owner 一个
        ``FeatureManagementManager``（事务服务 + 启动装载 + 结果信号）。宿主答不上来
        （装配失败、或本进程还没接上）时如实返回**空表**——``ModCenterController``
        见空表就不列「功能扩展」行、导入功能包时给出"宿主未接入"的拒绝语，
        不给占位管理器（占位会让 UI 显示一个点不动的条目）。
        """
        runtime = self.feature_host()
        if runtime is None:
            return {}
        try:
            return runtime.extensions()
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("扩展注册表不可用")
            return {}

    def feature_route(self, source):
        """包声明路由：读一次有界清单，为它建好管理器（不导入、不执行）。

        死锁修复（D2 spec §7.4-1）：注册表由**安装状态**导出，而安装状态只能通过导入
        改变——"这个 id 还没注册"不能反过来否掉一次导入。宿主答不出来 = 现状（``None``）。
        """
        runtime = self.feature_host()
        if runtime is None:
            return None
        try:
            return runtime.route(source)
        except (OSError, ValueError, RuntimeError):
            _LOG.exception("包声明路由不可用")
            return None

    def prepare_feature_revocation(self, owner: str) -> bool:
        """撤回（停用/删除/回滚/更新）前的 GUI 预检：有草稿就问一次三键。

        与事务层的 ``draft_blocked`` 是**同一条判据的两个入口**，读同一份快照
        （``pet/settings_mod_panel.prepare_revocation``）。返回 False = 用户取消，
        调用方必须**中止**这次动作并如实回报。
        """
        runtime = self.feature_host()
        if runtime is None:
            return True
        return bool(runtime.prepare_feature_revocation(owner, self.dialog))

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
        # 路由视图的 ``get("character")`` 是**打开表单那一刻**的档案快照；桌宠换装
        # 之后（或在设置页构造后被合法写者改了档案）它会过时，导致「仍在用旧角色」
        # 的假阳性。占用判据必须跟着**当前档案**走，所以优先按槽位现读。
        # 但档案**不存在**时 `read_slot_profile` 会给出同源默认角色（不是空串），
        # 那不是这只宠的现状——此时仍回答路由视图里的值（表单里刚 set 的也算）。
        from . import pet_profiles

        slot_id = getattr(self.dialog.config, "slot_id", None)
        if slot_id is not None:
            try:
                profile = pet_profiles.read_slot_profile(self.data_root, int(slot_id))
            except Exception:
                profile = None
            if profile is not None and profile.exists:
                character = str(profile.value("character") or "")
                if character:
                    return character
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
        if overlay_settings_command.is_overlay_topology() and live:
            # overlay 拓扑：子宠是进程内 sprite，不写 runtime marker——它们的活跃
            # 身份真值在持久化活跃集合。有活进程（marker 判活）才并入：进程不在了，
            # 残留清单不该挡操作。legacy 拓扑不读它（那边 marker 就是唯一来源，
            # 留存的子宠身份并没有在跑）。
            persisted = _active_set_slots(self.data_root)
            if persisted is None:
                return LiveUsage(verified=False)  # 活跃身份读不出：按「可能在用」拒绝
            live = sorted(set(live).union(persisted))
        if not live and not dirs:
            return LiveUsage(verified=True)  # 没人在跑：动文件伤不到活桌宠
        ids = [_slot_character(self.data_root, slot) for slot in live]
        owner = self._owner_character()
        if owner:
            ids.append(owner)
        verified = bool(dirs) or all(ids)
        return LiveUsage(verified=verified, asset_dirs=dirs,
                         character_ids=tuple(dict.fromkeys(ids)))

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


_UNSET = object()


def select_extension_settings(dialog, owner: str) -> bool:
    """设置深链接复用 owner 面板；再次导航不重建草稿，切 owner 先走草稿门。"""
    from .settings_mod_panel import prepare_revocation

    panel = getattr(dialog, "mod_panel", None)
    same_owner = panel is not None and not panel.disposed and dialog.mod_panel_owner == owner
    if not same_owner and not prepare_revocation(panel, dialog):
        return False
    if not dialog.select_page("扩展管理"):
        return False
    if not same_owner and not open_extension_settings(dialog, owner):
        return False
    panel = dialog.mod_panel

    def reveal():
        if not isValid(panel) or panel.disposed:
            return
        scroll = dialog.pages.currentWidget().findChild(QScrollArea, "settingsScroll")
        if scroll is not None:
            scroll.ensureWidgetVisible(panel, 0, 24)
        panel.setFocus()

    # 首开独立设置进程时需等布局完成再滚动；不是新增常驻定时器。
    QTimer.singleShot(0, reveal)
    return True


def open_extension_settings(dialog, owner: str) -> bool:
    """把某个扩展自己的设置面板挂进 MOD 中心页（**按 owner 局部挂载**）。

    切 owner 时先对上一块 ``dispose()``：MOD 列表的刷新只重建它自己的行，别的页与
    上一块面板的草稿都不该因为一次列表刷新而重建（spec §3.2）。返回 False = 这个
    扩展当下没有可用的设置界面（如实拒绝，不假造一个空面板）。
    """
    close_extension_settings(dialog)
    runtime = dialog.mod_host.feature_host()
    host_widget = getattr(dialog, "mod_panel_host", None)
    if runtime is None or host_widget is None:
        return False
    try:
        panel = runtime.settings_panel(owner, host_widget)
    except (OSError, ValueError, RuntimeError):
        _LOG.exception("扩展设置面板不可用: %s", owner)
        return False
    if panel is None:
        return False
    dialog.mod_panel = panel
    dialog.mod_panel_owner = str(owner)
    host_widget.layout().addWidget(panel)
    panel.embedded.show()
    panel.show()
    return True


def close_extension_settings(dialog) -> None:
    """收走当前挂着的扩展设置面板（幂等；没有就什么都不做）。"""
    panel, dialog.mod_panel = getattr(dialog, "mod_panel", None), None
    dialog.mod_panel_owner = ""
    if panel is None:
        return
    try:
        panel.dispose()
    except (RuntimeError, ValueError):
        _LOG.exception("扩展设置面板收尾失败")


def install_mod_domain(dialog) -> QWidget:
    """「扩展管理」域整页（幂等：域导航重建时复用同一个控制器与控件）。"""
    if getattr(dialog, "mod_controller", None) is None:
        host = DialogModHost(dialog)
        # 只有真正装配了 MOD 中心页才允许"本进程自建宿主"（独立设置进程那条路）。
        host.allow_own_host = True
        dialog.mod_host = host
        dialog.mod_controller = ModCenterController(host, parent=dialog)
        dialog.mod_center = ModCenterWidget(dialog.mod_controller, dialog, kinds=dialog.mod_controller.kinds)
        # 扩张自己的设置入口：按 owner 局部挂载（见 open_extension_settings）。
        dialog.mod_center.settings_requested.connect(lambda owner: open_extension_settings(dialog, owner))
        dialog.mod_panel = None
        dialog.mod_panel_owner = ""
        # 关窗即收尾：批处理的后续格子不再继续动文件（正在跑的那一格仍会跑完）；
        # 记下的换装请求此时执行（见 DialogModHost.use_resource 的时序说明）；
        # 扩展设置面板与自建宿主也在这一条链上收（顺序即连接顺序）。
        dialog.finished.connect(dialog.mod_controller.close)
        dialog.finished.connect(lambda *_: close_extension_settings(dialog))
        dialog.finished.connect(host.apply_pending_use)
        dialog.finished.connect(lambda *_: host.shutdown())
    content = QWidget(dialog)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(SettingsSection("MOD 中心", build_mod_rows(dialog), content))
    # 扩展自己的设置面板挂在这里（没有时是空的，不占位、不加新设置行）。
    panel_host = QWidget(content)
    panel_layout = QVBoxLayout(panel_host)
    panel_layout.setContentsMargins(0, 0, 0, 0)
    dialog.mod_panel_host = panel_host
    layout.addWidget(panel_host)
    layout.addStretch(1)
    return content


__all__ = [
    "DialogModHost",
    "USE_HINT",
    "build_mod_rows",
    "close_extension_settings",
    "install_mod_domain",
    "open_extension_settings",
]
