# -*- coding: utf-8 -*-
"""子宠设置页的配置读写路由：per-slot 键走 slot 文件，其余键走主配置。

问题（死开关）：overlay 拓扑下右键子宠 → 桌宠设置拉起的是**独立设置进程**
（``--instance slot-N`` → ``Config(instance_id="slot-N")`` → 读写
``config-slot-N.json``），而运行期只有 ``PER_SLOT_SETTING_KEYS`` 里的键逐宠取源
（``overlay_shell._SpriteConfig.get``），**其余键一律读主配置**。于是子宠页上
「语音报时 / 节日 / 待办 / 灵动岛 / 菜单外观 / 窗口级 7 键 …」约百行设置：保存
成功、回显正确、运行期零效果。窗口级 7 行还写着「（对所有桌宠生效）」——实际对
所有桌宠都不生效。

修法：给设置页的配置面套上读写路由（:func:`route_settings_config`），按 key 分流：

- 分流键（:data:`SLOT_ROUTED_KEYS`）→ slot 文件。写走
  ``overlay_spawn_state.write_slot_setting`` 的既有**原子单键写**（保留该身份文件
  的其它键），``user_customized`` 语义照旧；
- 其余键 → 主 ``config.json``。落盘遵守 **reload → set → save**：``Config.save``
  落的是整份内存视图，而设置进程的内存快照从启动起就陈旧，不先重读就会把设置窗
  开着期间主进程/托盘改过的键一起盖回去。

分流只对 **overlay 拓扑下的 slot 身份**生效：

- 主宠设置进程（无 ``--instance``）与 legacy 单窗（含捕获模式）里那只宠读的就是
  自己那份 ``config-slot-N.json`` 的**全部**键（``window.py`` 逐键读 ``self.cfg``），
  分流反而会让它的设置失效，故一律原样返回同一个配置对象；
- ``collision_enabled`` 虽不在 ``PER_SLOT_SETTING_KEYS`` 里，却也有专属的逐宠读点
  （见 :data:`SLOT_ROUTED_KEYS`）。

这里的"本进程拓扑"对设置子进程而言 = **拉起它的那个主进程的运行中拓扑**
（``overlay_settings_command.ENV_PARENT_TOPOLOGY``，主进程拉起设置子进程时注入）：
磁盘上的 ``stream_capture_mode`` 是重启级输入，用户勾了「直播捕获兼容」还没重启时
盘上是 legacy、而运行中的主进程仍是 overlay——按盘分流会把子宠页的全部设置写进
``config-slot-N.json``，而那个主进程对非 per-slot 键只读主配置，于是"保存成功、
实际无效"（2026-10-09 审查 R01）。父进程没发话（旧主进程 / 手工单开设置页）时判定
原样回退到磁盘快照，legacy 运行中的行为逐位不变。

主配置身份（F2 定论，2026-10-09）：:func:`route_settings_config` 构造主配置时不传
``instance_id``，于是 ``Config`` 会读 ``DSH_PET_INSTANCE``（``config.py:846``）——
这不是漏改，两种启动形态下它都恰好指向"该进程真正会读的那份文件"：

- **子宠的设置进程**：主进程按 ``_launch_settings_process`` 只在身份与进程级 env
  不同才追加 ``--instance slot-N``（子宠），env 仍是主窗的 ⇒ ``_main`` = 主窗那份
  ``config.json`` = 该进程运行期非 per-slot 键的读源（壳的 ``shell._config``，
  ``overlay_shell._SpriteConfig.get`` 的兜底分支）；
- **``--slot N`` 兼容启动**（``app.py`` 启动分流设 ``DSH_PET_INSTANCE=slot-N``，设置
  子进程继承它）：``_main`` 解析成 ``config-slot-N.json``——**这正是该进程的主配置**。
  该进程里壳的 ``shell._config`` 就是 ``Config(instance_id="slot-N")``，主 sprite 的
  取值走 ``_sprite_config(主 sprite) -> shell._config``（``overlay_shell.py:1401-1413``），
  legacy 单窗更是逐键读自己那份；换言之 ``_main`` 与运行期读源是同一份文件，
  写进去立刻生效。此时若"按 env 判定"反而**会**写错文件（父进程可能是 slot-2 身份，
  而它的子宠身份是 slot-5）。

结论：保持"主配置 = ``Config(base=<slot 配置目录的上一级>)``（env 决定身份）"，
不显式钉死路径；只有 ``slot_from_instance_id`` 那道门决定分不分流。

``PER_SLOT_SETTING_KEYS`` 的单一来源在 ``overlay_spawn_state``（零 Qt 轻模块）：
独立设置进程禁止导入 ``overlay_shell``（会连带素材库/ffmpeg/托盘），而壳侧只有
取源这一处读点，故键集本体放两侧都能 import 的轻模块。
"""
from __future__ import annotations

import logging

from . import overlay_settings_command, overlay_spawn_state
from .config import Config

logger = logging.getLogger(__name__)

__all__ = [
    "SLOT_LOCAL_KEYS",
    "SLOT_ROUTED_KEYS",
    "SlotRoutedConfig",
    "route_settings_config",
]

#: 该写进 slot 文件的键 = per-slot 取源集（``overlay_spawn_state`` 的单一来源）
#: **加上** ``collision_enabled``。
#:
#: 为什么多这一键：它的逐宠读点不在 ``_SpriteConfig.get`` 的第一条分支，而在紧随
#: 其后的专属分支（``_sprite_collision_enabled`` → ``read_slot_collision_enabled``：
#: 读这只宠的 slot 文件、缺文件继承主配置）。也就是说运行期对它的读法**就是**
#: per-slot 的——写进主配置既改不动这只宠（落种时 slot 文件里已有一份旧值压着），
#: 又会顺手改掉其它宠的继承值。
SLOT_ROUTED_KEYS = overlay_spawn_state.PER_SLOT_SETTING_KEYS | {"collision_enabled"}

#: slot 文件的**本地**键：只有落种/身份逻辑读它，运行期一个都不看。
#: 写进主配置会凭空多出第三个真值，故与 per-slot 键同走 slot 文件。
SLOT_LOCAL_KEYS = frozenset({"user_customized"})


class SlotRoutedConfig:
    """子宠设置页的配置视图：按 key 把读写分到 slot 文件或主配置。

    与 ``_SpriteConfig``（运行期那只宠的配置视图）是同一份契约的两端：这里按
    "谁写"分流，那里按"谁读"取源，两边共用 ``overlay_spawn_state`` 的键集。

    非路由属性（``chat_settings`` / 角色别名 / 点击台词 / 密钥）一律转发**主配置**：
    它们本就是进程级数据，子宠页以前读的是 slot 文件里的陈旧副本（AI 服务商列表
    显示成落种那一刻的样子），本身就是同一个 bug 的另一种表现。``instance_id`` /
    ``dir`` / ``path`` 仍取 slot 身份那份——"我是哪只桌宠"以及报错文案里的路径都
    以它为准（两份文件同目录，路径同源）。
    """

    def __init__(self, instance_config, main_config, slot_id: int) -> None:
        self._instance = instance_config
        self._main = main_config
        self._slot_id = int(slot_id)
        # slot 文件内容按需读一次（配置同步边界才重读）；pending 是"用户这次改了什么"，
        # 与磁盘缓存是两件事——``reload()`` 只作废缓存，不丢 pending。
        self._slot_data: dict | None = None
        # 分流键的清洗读源（绑定同一份 slot 文件的 Config，按需构造，与原始快照同代）
        self._slot_reader: Config | None = None
        self._pending_slot: dict = {}
        self._pending_main: dict = {}

    # ------------------------------------------------------------ 身份 / 路径面
    @property
    def instance_id(self) -> str:
        return str(getattr(self._instance, "instance_id", "") or "")

    @property
    def dir(self):
        return self._instance.dir

    @property
    def path(self):
        return self._instance.path

    @property
    def data(self) -> dict:
        """有效配置数据 = 主配置（``get`` 的读源，非 per-slot 键都从这里来）。"""
        return self._main.data

    # ------------------------------------------------------------ 读写路由
    def get(self, key, default=None):
        """读一个设置键：分流键先看 slot 文件，其余键看主配置。

        与运行期 ``_SpriteConfig.get`` 同口径：slot 文件里**缺键 / 值为 null** →
        回落到主配置（不是回落到出厂默认）——子宠的 per-slot 键本来就是这个继承语义。

        但"键在 slot 文件里"只回答**取谁**，不回答**值长什么样**：slot 文件是手改/
        半截 JSON 的一手数据，设置页各行却按"值已过 Config 清洗"的前提消费
        （``float(playback_speed)`` / 遍历 ``self_talk_texts`` / ``int(bubble_text_scale)``）。
        脏值原样交出去 = ValueError/TypeError → 整个设置窗构造失败（点「桌宠设置」
        什么也打不开）。故值一律过一遍 :meth:`_cleaned_slot_value`。
        """
        if key in SLOT_ROUTED_KEYS:
            if key in self._pending_slot:
                return self._pending_slot[key]
            value = self._slot_values().get(key)
            if value is not None:
                return self._cleaned_slot_value(key, value)
        return self._main.get(key, default)

    def set(self, key, value):
        """写一个设置键：分流键 → slot 文件（延后到 :meth:`save` 原子写），其余 → 主配置。

        主配置这一路先写内存（写后读立刻可见，与改动前同进程语义一致）并记 pending：
        真正落盘在 :meth:`save`，且先 ``reload()`` 再重放 pending。
        """
        if key in SLOT_ROUTED_KEYS or key in SLOT_LOCAL_KEYS:
            self._pending_slot[key] = value
            return
        self._pending_main[key] = value
        self._main.set(key, value)

    def set_chat_settings(self, settings) -> None:
        """chat 域（AI 页）是进程级数据：写主配置，并记 pending 供落盘重放。

        ``Config.set_chat_settings`` 是绕过 ``set`` 的直写口（写 ``data["chat"]``），
        不记 pending 就会被 :meth:`save` 里的 reload 当成"外部改动"冲掉。
        """
        self._main.set_chat_settings(settings)
        self._pending_main["chat"] = self._main.data.get("chat")

    def set_click_talk_bindings(self, character_id: str, bindings: dict) -> None:
        """点击动画台词绑定：写主配置 + 按本视图的落盘纪律立即持久化。

        必须显式实现，不能靠 ``__getattr__`` 转发：``Config.set_click_talk_bindings``
        改完内存就自己 ``save()``，而那是**整表**写——设置进程的内存快照从启动起就
        陈旧，设置窗开着期间主进程/托盘改过的键会被一起盖回去。

        两件事都走本视图的既有口径：

        - 写内存走 ``Config.set``：``character_profiles`` 在那个会触发
          ``_normalize_pet_settings`` 的键集里，清洗实现与 ``Config`` 同一份；
        - 落盘走 :meth:`_flush_main`（reload → 重放 pending → save）：既吸外部改动，
          又保住 ``Config.set_click_talk_bindings`` 的"保存即落盘"契约（台词绑定对话框
          点保存即生效，不必等设置页再点一次保存）。pending 里其余主配置键一并重放：
          它们是用户当前的界面值，而设置页关窗必走 ``_write_config``（没有"取消不保存"
          的出口），提前落盘不改变最终状态。
        """
        profiles = self._main.data.get("character_profiles")
        profiles = dict(profiles) if isinstance(profiles, dict) else {}
        profile = profiles.get(str(character_id))
        profile = dict(profile) if isinstance(profile, dict) else {}
        profile["click_talk_bindings"] = bindings
        profiles[str(character_id)] = profile
        self._main.set("character_profiles", profiles)
        self._pending_main["character_profiles"] = self._main.data.get("character_profiles")
        self._flush_main()

    def reload(self):
        """从磁盘重读两份配置（主配置 + slot 文件缓存）。

        ``reload`` 是既有的"外部变更合并"口：吸外部，同时保留 pending（用户这次改的
        键由 :meth:`save` 在重读之后重放）。
        """
        self._main.reload()
        self._invalidate_slot_snapshot()

    def save(self) -> bool:
        """落盘：先写 slot 文件，再按 reload → set → save 写主配置。"""
        ok_slot = self._flush_slot()
        ok_main = self._flush_main()
        return bool(ok_main and ok_slot)

    def reset_to_defaults(self) -> bool:
        """子宠页的「恢复默认设置」：只重置 slot 身份文件，**主配置一个键都不碰**。

        闸门所在：``Config.reset_to_defaults`` 把整份内存换成出厂默认再**整表**落盘。
        在子宠页上（本视图已把非路由键接到主配置）那份"整表"就是所有桌宠共用的主
        配置——点一次会把主宠与其它子宠的设置一起抹掉。子宠页能重置的只有它自己那份
        身份文件（per-slot 键 + 位置记忆，默认值同源 ``Config._initial_data``）。

        pending 一并作废：重置后的控件值已无意义，调用方随即走
        ``_close_after_external_write`` 跳过整表写回（见 pet/settings_reset_defaults.py）。
        """
        self._pending_slot.clear()
        self._pending_main.clear()
        self._invalidate_slot_snapshot()
        return bool(self._instance.reset_to_defaults())

    def __getattr__(self, name):
        """其余属性面一律转发主配置（chat / 角色别名 / 点击台词 / 密钥 / 域入口）。"""
        return getattr(self._main, name)

    # ------------------------------------------------------------ 清洗读源
    def _cleaned_slot_value(self, key, raw_value):
        """slot 文件原值 → **Config 口径**的清洗值（读源不可用时原样返回）。

        "清洗"= ``Config._normalize_pet_settings``（区间夹取、类型强转、枚举白名单），
        由读源的 Config 在构造时对同一份 slot 文件跑一遍。关键在**同一份实现**：
        在这里另写一张按键清洗表（``_float_or_default`` + 各键区间字面量）等于把
        Config 的默认值与范围抄第二遍，两边迟早漂移。
        """
        data = self._cleaned_slot_data()
        return data.get(key, raw_value) if isinstance(data, dict) else raw_value

    def _cleaned_slot_data(self) -> dict | None:
        """清洗读源的 data（按需构造一份绑定本 slot 文件的 Config）。

        ``Config`` 构造即 ``reload`` + ``_normalize_pet_settings``，所以读源
        **不能长期缓存**成"读过的那份内存"：``reload`` 自身不做归一化，读源随原始
        快照一起换代（见 :meth:`_invalidate_slot_snapshot`），每次换代重新构造，
        保证读到的清洗结果永远出自"构造时的 Config 口径"。

        只读路径的副作用边界：``Config(instance_id=...)`` 对已存在的 slot 文件只读
        （落种只在该身份还没有文件时发生，而那时 :meth:`get` 也走不到这里——原始
        快照里没有这个键）。
        """
        reader = self._slot_reader
        if reader is None:
            # 与 ``route_settings_config`` 的目录口径同源：``Config.dir = base/APP_DIR_NAME``。
            reader = Config(base=self._instance.dir.parent,
                            instance_id=f"slot-{self._slot_id}")
            self._slot_reader = reader
        return getattr(reader, "data", None)

    # ------------------------------------------------------------ 落盘内部
    def _invalidate_slot_snapshot(self) -> None:
        """作废 slot 文件的原始快照与清洗读源（落盘/重读后按需重取，两者同代）。"""
        self._slot_data = None
        self._slot_reader = None

    def _slot_values(self) -> dict:
        """slot 文件内容（读一次缓存；缺失/损坏 → 空 dict = 逐键回退主配置）。"""
        if self._slot_data is None:
            data = overlay_spawn_state.read_slot_config(self._instance.dir, self._slot_id)
            self._slot_data = data if isinstance(data, dict) else {}
            # 清洗读源与原始快照同代：换快照就必须换读源（否则读到上一代文件的清洗值）
            self._slot_reader = None
        return self._slot_data

    def _flush_slot(self) -> bool:
        """把 pending 的 slot 键逐个原子写进 slot 文件（保留该身份的其它键）。

        ``user_customized`` 与 per-slot 键走同一路：它是 slot 文件的本地键（运行期不
        看它，只有落种逻辑看），写进主配置会是第三个真值。本次落盘带着它就按
        ``write_slot_setting`` 的既有旗标语义置位（用户在这只子肥鱼自己的设置页保存
        过 ⇒ 下次生成不被主设置刷新）；pending 里没有该键时传 None 保持原值。
        """
        pending = dict(self._pending_slot)
        self._pending_slot.clear()
        self._invalidate_slot_snapshot()
        if not pending:
            return True
        flag = bool(pending["user_customized"]) if "user_customized" in pending else None
        ok = True
        for key, value in pending.items():
            if not overlay_spawn_state.write_slot_setting(
                    self._instance.dir, self._slot_id, key, value,
                    user_customized=flag):
                ok = False
                continue
            # 写盘成功即同步 slot 身份那份 Config 的内存视图：视图与文件是同一份身份
            # 的两种表示，保存完不该各说各话（任何仍持有启动时那个 Config 的调用方
            # 读到的必须是刚写下的值）。
            self._instance.data[key] = value
        return ok

    def _flush_main(self) -> bool:
        """主配置落盘：``reload`` → 重放 pending → ``save``（整表写，见类 docstring）。

        没有 pending 时一个字节都不写：子宠页只改 per-slot 键的那一次保存不该去动
        主配置文件（也就不会与主进程的写入互相踩）。
        """
        if not self._pending_main:
            return True
        pending = dict(self._pending_main)
        self._pending_main.clear()
        self._main.reload()
        for key, value in pending.items():
            self._main.set(key, value)
        return bool(self._main.save())


def route_settings_config(config):
    """给设置页的配置面套上读写路由；不适用时**原样返回同一个对象**。

    适用条件（两者都满足才分流）：

    1. 配置身份是 ``slot-N``（子宠的独立设置进程；主身份 / 非 slot 实例不分流）；
    2. 本进程拓扑是 overlay（legacy 单窗那只宠读的就是自己那份 slot 文件的全部键，
       分流会让它的设置失效）。设置子进程的这条判定 = **拉起它的主进程运行中拓扑**
       （``DSH_PET_PARENT_TOPOLOGY``），不是磁盘上下一次启动的配置，见模块 docstring。

    幂等：已套过路由的配置原样返回。
    """
    if config is None or isinstance(config, SlotRoutedConfig):
        return config
    slot_id = overlay_settings_command.slot_from_instance_id(
        getattr(config, "instance_id", ""))
    if slot_id is None:
        return config
    base = getattr(config, "dir", None)
    if base is None:
        return config
    if not overlay_settings_command.is_overlay_topology():
        return config
    # 主配置与 slot 身份配置同目录（``<config_dir>/config.json`` 对
    # ``<config_dir>/config-slot-N.json``）：复用 config 的既有目录解析口径
    # （``Config.dir = base/APP_DIR_NAME``，故 base 取 slot 配置的上一级）。
    main_config = Config(base=base.parent)
    return SlotRoutedConfig(config, main_config, slot_id)
