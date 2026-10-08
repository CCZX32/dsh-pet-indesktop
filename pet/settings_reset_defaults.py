# -*- coding: utf-8 -*-
"""「恢复默认设置」入口（设置页侧栏按钮 → 二次确认 → 整体重置）。

只做一个粒度：**整体重置**。按分页重置在没有"用户到底改坏了哪一页"的信息时帮不上
小白用户（issue #220 的原声场景），而整体重置是唯一有兜底价值的粒度，也把交互压到
按钮 + 一次确认。

唯一保留项是 chat 域的密钥类字段（含非默认 provider 的"只装凭据"容器），清单与理由见
``pet/config.py`` 的 ``CHAT_SECRET_FIELDS``；确认文案必须逐项写明保留了什么（用户按
"不可撤销"决策时看到的就是这段文字）。

重置完成后**关窗**而不是原地刷新：本对话框的控件是一次性从配置构造的（没有"按配置
重建全部控件"的路径），重置后窗口里全是旧值，而关闭路径会把全部控件整表写回
（``_write_config``）——不闸住就把刚写的默认值静默覆盖回去。所以走 ``_saved_via_button``
（既有的"已由按钮完成落盘"闸门）+ ``accept()``：运行中的桌宠由既有的
config watcher → ``reload()`` + ``_apply_external_config_change()`` 链应用默认值。

落盘之外还有两件"只落盘做不到"的收尾（缺一即确认文案里的承诺不成立）：

- **系统登录项按新值收敛**（:func:`sync_system_autostart`）：开机自启是 OS 侧状态，
  配置回默认不会自己关掉注册表/LaunchAgent 里的条目；与对话框既有的
  ``_apply_autostart`` 同一条通道，只是在设置进程里按新值调一次。
- **运行态对齐**（:func:`_request_runtime_alignment`）：位置类键已回 null，运行中的
  窗口不会自己动，而正常退出会把运行态几何写回磁盘——旧位置因此被"合法地"写回去，
  重置被静默抵消。两条路径与「一键退出子肥鱼」同规：进程内直接调窗回调，独立设置
  进程走 D12 指令通道。消费端（``AppShell`` / ``OverlayShell.apply_settings_reset``）
  在动运行态之前必须先 :func:`reload_runtime_config`：对齐会经 ``cfg.save()`` 整表
  落盘，而指令总是先于 300ms 去抖的 reload 到达（见该函数 docstring）。

实现拆出 ``modern_settings_dialog.py`` 的原因与 settings_music / settings_file_interpret
同规：主对话框只留一行接线（该文件有行数预算）。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox, QPushButton

from . import autostart as autostart_mod
from .context_menus.icons import vector_widget_icon

__all__ = [
    "create_reset_button",
    "on_reset_clicked",
    "build_reset_confirm_box",
    "confirm_reset",
    "sync_system_autostart",
    "reload_runtime_config",
]

RESET_BUTTON_TEXT = "恢复默认设置…"
RESET_TITLE = "恢复默认设置"
RESET_HEADLINE = "将重置全部设置为默认值（不可撤销）。"
RESET_KEPT = (
    "保留：AI 对话密钥——各服务商的 API Key 与视觉模型 Key；每个自定义服务商只保留"
    "密钥本身，地址、模型等其它设置会恢复默认。系统钥匙串里的条目不会删除。"
)
RESET_BODY = (
    "其余设置（形象、系统提示词、自定义台词与角色别名、外观与功能开关等）"
    "都会恢复出厂默认。\n"
    "位置立即回默认落位、开机自启按默认关闭；形象与素材类设置需重启后生效。\n"
    "设置窗口将随即关闭。"
)
# 按钮文案自写而不用 StandardButton.Yes：产品没装 Qt 中文翻译（仓库内无
# QTranslator），标准按钮在中文界面上仍显示 "Yes"，破坏性操作不该让人猜。
RESET_CONFIRM_LABEL = "恢复默认设置"
RESET_CANCEL_LABEL = "取消"


def create_reset_button(host, layout) -> QPushButton:
    """在设置窗侧栏底部创建「恢复默认设置…」入口。

    放侧栏而不是设置页行：它是命令不是偏好项（docs/SETTINGS-CHANGE-GATES.md
    的准入清单明确排除命令类），与同侧的「保存并退出」同属应用级操作。
    """
    button = QPushButton(RESET_BUTTON_TEXT, host)
    button.setObjectName("resetDefaults")
    button.setIcon(vector_widget_icon(button, "retry", 16))
    button.setToolTip("把全部设置恢复为出厂默认值；已配置的 AI 对话密钥会保留。")
    button.setAutoDefault(False)
    button.setDefault(False)
    button.clicked.connect(lambda: on_reset_clicked(host))
    host.reset_defaults_btn = button
    layout.addWidget(button)
    return button


def build_reset_confirm_box(parent) -> tuple[QMessageBox, QPushButton]:
    """构造二次确认框（不 exec，便于断言文案与按钮语义）。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(RESET_TITLE)
    box.setText(RESET_HEADLINE)
    box.setInformativeText(f"{RESET_KEPT}\n\n{RESET_BODY}")
    confirm = box.addButton(RESET_CONFIRM_LABEL, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(RESET_CANCEL_LABEL, QMessageBox.ButtonRole.RejectRole)
    # 破坏性操作：默认按钮与 Esc 都落在取消上，回车不会误触重置。
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    return box, confirm


def confirm_reset(parent) -> bool:
    """弹确认框并返回用户是否选择重置（取消/关框一律 False）。"""
    box, confirm = build_reset_confirm_box(parent)
    box.exec()
    return box.clickedButton() is confirm


def sync_system_autostart(host) -> None:
    """把系统登录项收敛到重置后的值（``autostart_wanted`` 默认关闭）。

    与对话框既有的 ``_apply_autostart`` 同一条通道、同一个进程（系统自启是
    OS 侧状态，不需要桌宠运行期配合）；差别只在这里没有"用户勾选值"可比，
    直接按重置后的配置值收敛。子宠页的开机自启控件本就禁用（仅主桌宠可设置），
    故子配置一律不碰 OS 项。系统侧已是目标值时不做任何写入。
    """
    if host.config.instance_id:
        return
    wanted = bool(host.config.get("autostart_wanted", False))
    if autostart_mod.is_enabled() == wanted:
        return
    if autostart_mod.set_enabled(wanted) is False:
        QMessageBox.warning(
            host,
            "开机自启设置失败",
            "写入开机自启失败：可能被安全软件拦截。\n"
            "可在设置页的「开机自启」开关里重试，或检查安全软件/系统优化工具的拦截记录。",
        )


def reload_runtime_config(*configs) -> bool:
    """重置级运行态对齐**之前**，把运行期配置从磁盘拉齐。返回是否真的重载过。

    为什么必须在对齐前做（B1）：对齐的落点要经 ``cfg.save()`` **整表**落盘（legacy
    是 ``win.go_default_corner`` → ``save_position``，overlay 是退出时的
    ``save_position``）。而设置进程是"先写默认值、再写对齐指令"两步目录事件，主
    进程的事件处理顺序是「先消费指令（立刻对齐并落盘）、后按 300ms 去抖排 reload」
    ——对齐那一刻运行期那份 Config 还停在重置前的旧值，一次整表落盘就把刚落盘的
    默认值全部覆盖回去（``no_move`` / ``pet_opacity`` / ``stream_capture_mode`` …），
    重置被静默抵消。

    ``reload()`` 本身是既有的"外部变更合并"口（键清单见 ``Config.reload``），与
    watcher 随后那一拍同源，重复调用幂等。多个候选里同一份配置只重载一次（生产
    路径 ``win.cfg`` 与 ``shell.config`` 常常就是同一个对象）。

    无 ``reload`` 接口的假配置/测试替身跳过（对齐照跑，行为不比修复前更差）。
    """
    reloaded = False
    seen: set[int] = set()
    for config in configs:
        if config is None or id(config) in seen:
            continue
        seen.add(id(config))
        reload_fn = getattr(config, "reload", None)
        if not callable(reload_fn):
            continue
        try:
            reload_fn()
        except Exception:
            logging.exception("恢复默认设置：运行态配置重载失败，对齐可能被旧值覆盖")
            continue
        reloaded = True
    return reloaded


def _request_runtime_alignment(host) -> None:
    """请求「重置级运行态对齐」（位置回默认落位；见 pet/config.py 的位置三键口径）。

    两条路径与「一键退出子肥鱼」同规：进程内设置页有桌宠窗口可依附 → 直接调窗上
    已接线的回调；独立设置进程没有窗口 → 走 D12 指令通道，由主进程消费。

    不对齐的后果不是"少刷新一下"：位置键已回 null，运行期却还在旧位置，本次退出
    ``save_position()`` 会把旧位置写回磁盘，重置被静默抵消（issue #220 M10）。
    """
    parent = host.parentWidget()
    callback = getattr(parent, "on_settings_reset", None)
    if callable(callback):
        callback()
        return
    from .overlay_settings_command import (
        CMD_APPLY_SETTINGS_RESET,
        slot_from_instance_id,
        write_command,
    )

    target = slot_from_instance_id(host.config.instance_id)
    if not write_command(host.config.dir, CMD_APPLY_SETTINGS_RESET, target=target):
        logging.warning("恢复默认设置：运行态对齐指令写盘失败，桌宠位置将在重启后回默认落位")


def on_reset_clicked(host) -> bool:
    """按钮处理：确认 → 重置并落盘 → 运行态对齐 → 关窗。返回是否真的重置成功。

    取消或落盘失败都返回 False 且对磁盘零副作用（调用方据此决定关不关窗）。
    """
    if not confirm_reset(host):
        return False
    if not host.config.reset_to_defaults():
        QMessageBox.warning(
            host,
            "恢复默认设置失败",
            "配置未能写入磁盘，设置未重置。\n\n配置路径：" + str(host.config.path),
        )
        return False
    logging.info("设置已恢复默认：%s", host.config.path)
    sync_system_autostart(host)
    _request_runtime_alignment(host)
    # 关窗但闸住整表写回（控件里是重置前的旧值，见模块 docstring）；
    # flag 语义由对话框自己拥有。
    host._close_after_external_write()
    return True
