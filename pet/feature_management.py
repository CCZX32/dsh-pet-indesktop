# -*- coding: utf-8 -*-
"""功能扩展的管理侧入口；本片只落地**与宿主无关的只读发现**。

Ported from the DLC branch ``pet/feature_management.py``；那一半在 DLC 里是
GUI 线程上的 ``FeatureManagementRuntime(QObject)``（事务提交、探针恢复、状态
监视、生命周期 IPC、上下文装配……），依赖本仓库没有的 LPAC 探针链与官方内置域
（识屏 / AI），属「宿主管理面」的后续切片，不在本片。

本片只搬 :func:`discover_local_feature_ids`：安装状态账本是唯一权威，启动时
遍历 ``plugins/*/`` 找出**已经落地过状态**的 owner（含首次安装被打断、只有
pending 事务、没有版本目录的那一种）。它零 Qt、只读、不导入包代码。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["discover_local_feature_ids"]


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
