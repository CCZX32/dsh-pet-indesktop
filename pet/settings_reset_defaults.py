# -*- coding: utf-8 -*-
"""「恢复默认设置」入口（设置页侧栏按钮 → 二次确认 → 整体重置）。

只做一个粒度：**整体重置**。按分页重置在没有"用户到底改坏了哪一页"的信息时帮不上
小白用户（issue #220 的原声场景），而整体重置是唯一有兜底价值的粒度，也把交互压到
按钮 + 一次确认。

唯一保留项是 chat 域的密钥类字段，清单与理由见 ``pet/config.py`` 的
``CHAT_SECRET_FIELDS``；确认文案必须逐项写明保留了什么（用户按"不可撤销"决策时看
到的就是这段文字）。

重置完成后**关窗**而不是原地刷新：本对话框的控件是一次性从配置构造的（没有"按配置
重建全部控件"的路径），重置后窗口里全是旧值，而关闭路径会把全部控件整表写回
（``_write_config``）——不闸住就把刚写的默认值静默覆盖回去。所以走 ``_saved_via_button``
（既有的"已由按钮完成落盘"闸门）+ ``accept()``：运行中的桌宠由既有的
config watcher → ``reload()`` + ``_apply_external_config_change()`` 链应用默认值。

实现拆出 ``modern_settings_dialog.py`` 的原因与 settings_music / settings_file_interpret
同规：主对话框只留一行接线（该文件有行数预算）。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox, QPushButton

from .context_menus.icons import vector_widget_icon

__all__ = ["create_reset_button", "on_reset_clicked", "build_reset_confirm_box", "confirm_reset"]

RESET_BUTTON_TEXT = "恢复默认设置…"
RESET_TITLE = "恢复默认设置"
RESET_HEADLINE = "将重置全部设置为默认值（不可撤销）。"
RESET_KEPT = "保留：AI 对话密钥——各服务商的 API Key 与视觉模型 Key（系统钥匙串里的条目不会删除）。"
RESET_BODY = (
    "其余设置（自定义服务商条目、形象、系统提示词、自定义台词与角色别名、"
    "外观与功能开关等）都会恢复出厂默认。\n"
    "设置窗口将随即关闭，桌宠立即应用默认设置。"
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


def on_reset_clicked(host) -> bool:
    """按钮处理：确认 → 重置并落盘 → 关窗。返回是否真的重置成功。

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
    # 关窗但闸住整表写回（控件里是重置前的旧值，见模块 docstring）；
    # flag 语义由对话框自己拥有。
    host._close_after_external_write()
    return True
