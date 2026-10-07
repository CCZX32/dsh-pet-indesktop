# -*- coding: utf-8 -*-
"""设置页「网络信息」的控件创建 / 行装配 / 保存（issue #172）。

modern_settings_dialog.py 行数预算刚校准到零余量，所以本功能的控件与行全部在
本模块构建，对话框只做三处接线：import 1 行、岛页挂「网络信息」小节 3 行、保存
委托 1 行（菜单域那处是既有「内容与布局」行的追加，净 0；该文件预算已按实测
2420 校准并带日期注释）。

归属（SETTINGS-CHANGE-GATES 的"归属唯一"）：

- ``island_network_enabled`` / ``network_probe_interval_seconds`` 只属于「桌面组件
  · 桌面胶囊（灵动岛）」——岛的信息槽显示什么，只在岛这一处决策；
- ``network_info_menu_enabled`` 只属于「菜单」——它决定右键菜单里那一项显不显示，
  与岛上的信息槽无关；两处不复制对方的状态。

依赖显隐：网络槽开着时「信息槽内容 / 自定义短文本」不生效（内容被网络信息接管），
这里用同族机制（``_set_setting_rows_visible`` 的 dependency 位是 AND 叠加的）挂上
自己那一位，不抢 ``settings_pet_controls`` 的权——两边各写各的依赖键，结果按 AND
合成，与调用顺序无关。
"""
from __future__ import annotations

from . import net_monitor
from .settings_widgets import (
    BrowserDoubleSpinBox,
    SettingRow,
    ToggleSwitch,
    mark_main_pet_only,
)

#: 探测间隔的展示口径（真值口径在 net_monitor.clamp_interval，不在这里重写一份）
_MIN_INTERVAL = net_monitor.MIN_INTERVAL_SECONDS
_MAX_INTERVAL = net_monitor.MAX_INTERVAL_SECONDS
_DEFAULT_INTERVAL = net_monitor.DEFAULT_INTERVAL_SECONDS

#: 流量成本文案（单次探测在网字节 → 每天 MB；进设置行文案）
_KB_PER_ROUND = net_monitor.PROBE_BYTES_PER_ROUND / 1024.0
#: Qt 的 QWIDGETSIZE_MAX（解除基类固定宽度的写法，同 dynamic_island 先例）
_QWIDGETSIZE_MAX = 16777215


def _traffic_hint(interval_seconds: float) -> str:
    """按间隔算出"每天大约多少 MB"——文案里的数字跟着真实间隔走，不写死。"""
    per_day_mb = _KB_PER_ROUND * (86400.0 / max(_MIN_INTERVAL, interval_seconds)) / 1024.0
    return f"{per_day_mb:.1f} MB/天"


def create_network_controls(dialog) -> None:
    """在对话框上创建本功能的控件（幂等；行由下面两个 build_* 装配）。"""
    if getattr(dialog, "island_network_check", None) is None:
        dialog.island_network_check = ToggleSwitch(dialog)
        dialog.island_network_check.setChecked(
            bool(dialog.config.get("island_network_enabled", False)))

        dialog.network_probe_interval_spin = BrowserDoubleSpinBox(dialog)
        dialog.network_probe_interval_spin.setRange(_MIN_INTERVAL, _MAX_INTERVAL)
        dialog.network_probe_interval_spin.setDecimals(1)
        dialog.network_probe_interval_spin.setSingleStep(0.5)
        dialog.network_probe_interval_spin.setSuffix(" 秒")
        dialog.network_probe_interval_spin.setValue(net_monitor.clamp_interval(
            dialog.config.get("network_probe_interval_seconds", _DEFAULT_INTERVAL)))
        _fit_spin_to_content(dialog.network_probe_interval_spin)
        dialog.network_probe_interval_spin.valueChanged.connect(
            lambda _value: _sync_interval_hint(dialog))

    if getattr(dialog, "network_info_menu_check", None) is None:
        dialog.network_info_menu_check = ToggleSwitch(dialog)
        dialog.network_info_menu_check.setChecked(
            bool(dialog.config.get("network_info_menu_enabled", True)))

    # 三个键都是**进程级**（不在 PER_SLOT_SETTING_KEYS，采样器/岛/右键菜单一律读
    # 主配置）：子宠页改了不生效，如实置灰。
    mark_main_pet_only(dialog, getattr(dialog, "island_network_check", None),
                       getattr(dialog, "network_probe_interval_spin", None),
                       getattr(dialog, "network_info_menu_check", None))


def _fit_spin_to_content(spin) -> None:
    """按字体度量给足宽度，并解除基类的固定宽度。

    基类 ``BrowserDoubleSpinBox`` 固定 92px：本项最长值 "60.0 秒" 在默认字体下
    正好占满行编辑区（本机实测 72/72px，零余量），放大字体 / High DPI 就会把数字
    裁掉。这里改成"宽度随内容与字体度量增长"（可视化验收要求：放大字体不得裁切）。
    """
    text = f"{spin.maximum():.{spin.decimals()}f}{spin.suffix()}"
    needed = spin.fontMetrics().horizontalAdvance(text) + 44  # 箭头区 + 内边距
    spin.setMinimumWidth(max(needed, spin.width()))
    spin.setMaximumWidth(_QWIDGETSIZE_MAX)


def _interval_hint(dialog) -> str:
    """间隔行的文案（"每天多少流量"跟着当前值算，不写死）。"""
    return (
        f"延迟探测间隔（{_MIN_INTERVAL:g}–{_MAX_INTERVAL:g} 秒）。越短越灵敏、流量越多："
        f"当前设置约 {_traffic_hint(_spin_value(dialog))}。"
        "探测目标固定为 223.5.5.5（阿里公共 DNS，境内），不发往国外地址。"
    )


def _sync_interval_hint(dialog) -> None:
    """间隔一变就把文案重算一遍（数字必须跟真实间隔一致）。"""
    row = dialog.findChild(SettingRow, "settingRow_network_probe_interval")
    if row is None or not hasattr(row, "hint_label"):
        return
    row.hint_label.setText(_interval_hint(dialog))


def _spin_value(dialog) -> float:
    spin = getattr(dialog, "network_probe_interval_spin", None)
    if spin is None:
        return _DEFAULT_INTERVAL
    try:
        return net_monitor.clamp_interval(spin.value())
    except Exception:  # pragma: no cover - 控件被销毁等
        return _DEFAULT_INTERVAL


def build_island_network_rows(dialog) -> list[SettingRow]:
    """岛侧两行（objectName 前缀 settingRow_island_network / network_probe_interval）。

    行随域导航每次重建（行壳随旧页 deleteLater，控件对象复用），与 island /
    file_interpret 行的重建口径一致。
    """
    create_network_controls(dialog)
    rows = [
        SettingRow(
            "island_network",
            "信息槽显示网络",
            "开启后岛的信息槽改为显示 ↓下行 / ↑上行速率与延迟：速率读网卡字节计数器"
            "（零流量），延迟用 UDP 往返探测（每次约 0.16 KB）。默认关闭——开着会持续"
            "发探测包；关闭后信息槽回到「信息槽内容」选的内容。",
            dialog.island_network_check,
        ),
        SettingRow(
            "network_probe_interval",
            "延迟探测间隔",
            _interval_hint(dialog),
            dialog.network_probe_interval_spin,
        ),
    ]
    _install_visibility(dialog, rows)
    return rows


def build_menu_rows(dialog) -> list[SettingRow]:
    """菜单侧一行：右键菜单「网络信息」入口显隐。"""
    create_network_controls(dialog)
    return [
        SettingRow(
            "network_info_menu",
            "「网络信息」菜单入口",
            "右键菜单里显示「网络信息」：公网 IP、IP 属地（及是否在中国大陆）、"
            "Google / GitHub 可达性。只在打开弹窗时取一次（约 1 KB），不轮询；"
            "关掉后菜单里不再出现该入口。",
            dialog.network_info_menu_check,
        ),
    ]


def _install_visibility(dialog, rows: list[SettingRow]) -> None:
    """把岛侧三级的显隐依赖接上（岛开关 → 信息槽开关 → 网络槽开关）。

    依赖位（``_visibility_dependencies``）与 ``settings_pet_controls`` 写的那些位
    按 AND 合成，两边互不干扰、与调用顺序无关。信号只连一次；行壳每次域导航重建
    都是新的，故信号回调统一读 ``dialog._island_network_sync`` 上的最新闭包。
    """
    by_key = {row.objectName()[len("settingRow_"):]: row for row in rows}

    def apply(key: str, visible: bool, dependency: str) -> None:
        dialog._set_setting_rows_visible((key,), visible, dependency=dependency)
        row = by_key.get(key)
        # 行壳刚构造出来、还没进卡片时 ``findChild`` 找不到它（父对象尚未设置），
        # 上面那条通道会落空——这里对本体补一次，语义完全相同（进卡片后不再走）。
        if row is not None and row.parent() is None:
            row.setVisible(visible)

    def sync(*_args) -> None:
        island_on = bool(dialog.island_enabled_check.isChecked())
        info_on = bool(dialog.island_info_check.isChecked())
        net_on = bool(dialog.island_network_check.isChecked())
        apply("island_network", island_on and info_on, "island_info_slot_shown")
        apply("network_probe_interval", island_on and info_on and net_on,
              "island_network_on")
        # 网络槽开着时信息槽内容不由 info_mode 决定：同族依赖位把它隐掉，避免
        # 留下"改了没反应"的控件（关掉网络槽后自动恢复）。
        dialog._set_setting_rows_visible(
            ("dynamic_island_info_mode", "dynamic_island_custom_text"), not net_on,
            dependency="island_network_off")

    dialog._island_network_sync = sync
    if not getattr(dialog, "_island_network_visibility_wired", False):
        dialog._island_network_visibility_wired = True
        for checkbox in (dialog.island_enabled_check, dialog.island_info_check,
                         dialog.island_network_check):
            checkbox.toggled.connect(lambda *_a, host=dialog: host._island_network_sync())
    sync()


def save_network_settings(dialog) -> None:
    """_write_config 委托：把三键写回 config（设置页保存时调用一次）。"""
    if getattr(dialog, "island_network_check", None) is None:
        return
    dialog.config.set("island_network_enabled",
                      bool(dialog.island_network_check.isChecked()))
    dialog.config.set("network_probe_interval_seconds", _spin_value(dialog))
    dialog.config.set("network_info_menu_enabled",
                      bool(dialog.network_info_menu_check.isChecked()))
