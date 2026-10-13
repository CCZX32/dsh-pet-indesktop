# -*- coding: utf-8 -*-
"""「主动识屏」的执行位置与 worker 状态行（构建 / 刷新 / 保存）。

**为什么单独一个模块**：``modern_settings_dialog.py`` 有行数预算且已无余量
（同 ``settings_file_interpret.py`` / ``settings_quiet.py`` 的先例），而 S3 新增的
「在哪执行 + 现在实际状态」是一组自足的控件：一个下拉（真设置）+ 一个只读状态
标签（读主进程写的快照）。

**为什么状态要落盘读**：设置页可能是**独立进程**（``python -m pet --settings``），
那时进程里根本没有 worker 对象；主进程在状态变化时写
``proactive_worker_status.json``，两侧都能读到同一份事实。这里不猜、不编：
读不到就显示「未知」，故障就显示故障。

**契约**（对话框侧只有三处调用）：

* :func:`build_controls` —— 造控件并挂在 ``dialog`` 上（``pro_execution_select`` /
  ``pro_worker_status_label``），接线刷新时机；
* :func:`section` —— 域页里那一段 SettingRow；
* :func:`apply_to_config` —— 保存时把下拉的值写回 ``proactive_screen``。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel

from .proactive import effective_proactive_config
from .proactive_worker_status import (
    EXECUTION_IN_PROCESS,
    EXECUTION_WORKER,
    describe,
    read_status,
    worker_mode,
)
from .settings_widgets import ModernSelect, SettingRow, SettingsSection


def build_controls(dialog) -> None:
    """在 dialog 上造出执行位置下拉 + 只读状态标签。"""
    pro = effective_proactive_config(dialog.config.get("proactive_screen", {}))

    dialog.pro_execution_select = ModernSelect(dialog, width=180)
    dialog.pro_execution_select.addItem("独立子进程（推荐）", EXECUTION_WORKER)
    dialog.pro_execution_select.addItem("进程内（旧路径）", EXECUTION_IN_PROCESS)
    dialog.pro_execution_select.setCurrentIndex(0 if worker_mode(pro) == EXECUTION_WORKER else 1)
    dialog.pro_execution_select.currentIndexChanged.connect(lambda *_: refresh(dialog))

    dialog.pro_worker_status_label = QLabel("", dialog)
    dialog.pro_worker_status_label.setObjectName("settingValue")
    dialog.pro_worker_status_label.setWordWrap(True)
    dialog.pro_worker_status_label.setMinimumWidth(200)
    refresh(dialog)

    sidebar = getattr(dialog, "sidebar", None)
    if sidebar is not None:
        sidebar.currentRowChanged.connect(lambda *_: refresh(dialog))


def refresh(dialog, *_args: Any) -> None:
    """读快照并如实展示「谁在执行 / 有没有故障」。

    用户在页面上改了执行位置但还没保存时，状态行至少要反映「打算改成什么」，
    否则会出现「选了进程内、状态却还说 worker」的假象。
    """
    label = getattr(dialog, "pro_worker_status_label", None)
    if label is None:
        return
    snapshot = read_status(dialog.config.dir)
    select = getattr(dialog, "pro_execution_select", None)
    if select is not None and snapshot:
        snapshot = dict(snapshot)
        snapshot["mode"] = str(select.currentData() or snapshot.get("mode", ""))
    value, hint = describe(snapshot)
    label.setText(value if not hint else f"{value}\n{hint}")
    label.setToolTip(hint)


def section(dialog, content) -> SettingsSection:
    """域页里的「执行位置」分段（两个 SettingRow）。"""
    return SettingsSection(
        "执行位置",
        [
            SettingRow(
                "proactive_execution",
                "识屏在哪执行",
                "独立子进程：截图与视觉请求都在单独的 worker 里做，不占用桌宠主进程；"
                "进程内：旧的同进程后台线程路径。worker 出故障时不会自动改用进程内，"
                "只会停止识屏并如实显示状态。",
                dialog.pro_execution_select,
            ),
            SettingRow(
                "proactive_worker_status",
                "当前实际状态（只读）",
                "由主进程写入、设置页读取：现在是谁在执行、有没有故障。打开本页会刷新一次。",
                dialog.pro_worker_status_label,
                stacked=True,
            ),
        ],
        content,
    )


def apply_to_config(dialog, pro_data: dict) -> None:
    """保存：把下拉里选的执行位置写回配置。"""
    pro_data["execution"] = str(
        dialog.pro_execution_select.currentData() or EXECUTION_WORKER
    )
