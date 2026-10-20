# -*- coding: utf-8 -*-
"""功能模块激活层（期 1）：启用集合的迁移判定 + 进程级快照。

设计见 ``.scratch/feature-modules/SPEC.md``。本模块只管三件事：

1. **一次性迁移判定**：``feature_activation`` 为 ``None``（未判定）时，区分
   新装/升级写回初始启用集合——升级继承 ``MIGRATION_BASELINE``（全模块），
   新装在期 5 之前同样继承全集（``PURE_CORE_FOR_NEW_INSTALL`` 届时才翻
   True，且必须等全部模块过完「不出现、不启动、不写回」验收）。
2. **本次运行快照**：主进程在创建任何可选服务之前 ``decide_and_freeze`` 一次，
   之后 ``is_active`` 只读快照——功能页写盘（下次启动生效）绝不影响本次运行。
3. **写下次启动值**：``write_enabled`` 给功能管理页用，校验后整值提交。

快照未冻结时（测试、工具脚本、独立设置进程）``is_active`` 一律 True——
门控是调用点可选接入的，旧行为默认不变。

本模块禁止 import Qt（启动早期使用，import 必须便宜）。
"""
from __future__ import annotations

import logging

from .features import FEATURES, MIGRATION_BASELINE, normalize_enabled

log = logging.getLogger(__name__)

#: 启用集合结构的当前版本（不认识的高版本按损坏处理：保留原数据 + 诊断）。
CURRENT_VERSION = 1

#: 新装用户是否默认纯核心（enabled=[]）。期 5 才允许翻 True——那是「全部
#: 模块过完验收矩阵」之后的最后一步，见 SPEC §6。
PURE_CORE_FOR_NEW_INSTALL = False

#: 本次运行冻结的启用集合；None = 未冻结（is_active 一律 True）。
_snapshot: frozenset[str] | None = None


def _is_upgrade_install(config) -> bool:
    """升级安装判定：有任一既有数据痕迹即按升级处理（继承全部模块）。

    「config.json 缺失但 slot 档案/会话目录在」不能判新装（SPEC §4）。
    """
    if config.path.is_file():
        return True
    try:
        if any(config.dir.glob("config-slot-*.json")):
            return True
        if (config.dir / "sessions").is_dir():
            return True
    except OSError:
        # 目录不可读时按升级处理（保守：宁可多激活，不可藏掉用户在用的功能）
        return True
    return False


def decide_and_freeze(config) -> frozenset[str]:
    """启动早期调用一次：完成迁移判定（若需要）并冻结本次运行快照。

    - 已判定（盘上有合法值）：直接冻结，未知 ID 进不了快照但保留在盘上；
    - 未判定（None）：按新装/升级写回初始集合（整值提交，走正常 save 链）；
    - 损坏（非 dict / 版本不认识 / enabled 不是 list）：保留原数据、打诊断，
      保守冻结全模块——绝不拿默认值覆盖用户数据；
    - 合法空列表是明确选择，原样冻结（绝不回退成全激活）。
    """
    global _snapshot
    raw = config.data.get("feature_activation")
    if raw is None:
        upgrade = _is_upgrade_install(config)
        enabled = [] if (not upgrade and PURE_CORE_FOR_NEW_INSTALL) else list(MIGRATION_BASELINE)
        payload = {"version": CURRENT_VERSION, "enabled": enabled}
        config.set("feature_activation", payload)
        if config.save():
            log.info("功能模块激活：%s安装，初始启用集合已落盘（%d 项）",
                     "升级" if upgrade else "新装", len(enabled))
        else:
            # 写失败不冒充成功：快照照常冻结（本次运行可用），诊断留给日志
            log.warning("功能模块激活：初始启用集合落盘失败，仅本次运行生效")
        _snapshot = frozenset(enabled)
        return _snapshot
    if not isinstance(raw, dict) or raw.get("version") != CURRENT_VERSION \
            or not isinstance(raw.get("enabled"), list):
        log.warning("功能模块激活：配置值损坏或版本不认识（保留原数据，本次按全模块运行）: %r",
                    type(raw).__name__)
        _snapshot = frozenset(MIGRATION_BASELINE)
        return _snapshot
    try:
        enabled, unknown = normalize_enabled(raw["enabled"])
    except ValueError:
        # 元素级损坏（如 ["weather", 3]）：同整体损坏口径——保留原数据 + 诊断，
        # 保守冻结全模块，不拿默认值覆盖
        log.warning("功能模块激活：启用列表元素损坏（保留原数据，本次按全模块运行）")
        _snapshot = frozenset(MIGRATION_BASELINE)
        return _snapshot
    if unknown:
        log.info("功能模块激活：%d 个未知模块 ID 保留在盘上但不激活: %s", len(unknown), unknown)
    _snapshot = frozenset(enabled)
    return _snapshot


def is_active(feature_id: str) -> bool:
    """本次运行该模块是否激活。快照未冻结（测试/工具/独立设置进程）恒 True。"""
    return _snapshot is None or feature_id in _snapshot


def snapshot() -> frozenset[str] | None:
    """当前冻结的快照（诊断/测试用）；None = 未冻结。"""
    return _snapshot


def pending_enabled(config) -> list[str]:
    """功能页展示的「下次启动」启用集：盘上已判定的值；未判定给迁移基线预览。"""
    raw = config.data.get("feature_activation")
    if isinstance(raw, dict) and isinstance(raw.get("enabled"), list):
        try:
            enabled, _ = normalize_enabled(raw["enabled"])
        except ValueError:
            return list(MIGRATION_BASELINE)
        return enabled
    return list(MIGRATION_BASELINE)


def write_enabled(config, enabled: list[str]) -> bool:
    """功能页保存入口：校验后整值提交「下次启动」启用集；返回是否落盘成功。

    未知/非法 ID 直接拒绝（调用方是 UI，给的是清单内的 id）；合法空列表允许。
    只写盘，不动本次运行快照——重启才生效。
    """
    unknown = [fid for fid in enabled if fid not in FEATURES]
    if unknown:
        log.warning("功能模块激活：拒绝写入未知模块 ID: %s", unknown)
        return False
    deduped = list(dict.fromkeys(enabled))
    config.set("feature_activation", {"version": CURRENT_VERSION, "enabled": deduped})
    return bool(config.save())


def reset_snapshot_for_tests() -> None:
    """测试专用：解除冻结，恢复 is_active 恒 True 的默认态。"""
    global _snapshot
    _snapshot = None
