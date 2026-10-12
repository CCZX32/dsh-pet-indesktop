# -*- coding: utf-8 -*-
"""设置页「AI 与对话」域：把已建好的 AI 行按组装配成域页。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算已无余量，本域的
整段行构造（约 60 行）搬到这里，对话框只留一处调用（``build_ai_domain``）。

**本域与 ``settings_interaction`` / ``settings_file_interpret`` 的差别**：那两个模块
自己**创建**控件与行；本域的行早已由聊天页（``chat/ai_settings_page.py``，即
``dialog.ai_page``）创建，这里只按设置键把它们认领回来重新分组——所以本模块不做
控件构造，只决定「哪些键进哪个组、组序如何」。

**必须保持的两处外部契约**（都有测试与保存链依赖）：

- 页 ``objectName`` 仍是 ``settingsDomain_ai``（``tests/test_menu_layout.py`` 按它
  定位域页）；
- ``dialog.ai_page`` 仍 ``setParent(dialog)`` + ``hide()``：控件归属者要活到保存
  （``_write_config`` 里有 ``self.ai_page.save()``），可见行则直接归共享域布局。
  no-chat 打包变体没有 AI 页，返回 ``None``（原逻辑同）。

**签名说明**：``claim`` / ``claim_prefix`` / ``page_content`` 是
``_rebuild_domain_navigation`` 的局部装配助手（闭包捕获对话框的行快照与已认领
集合）。这里原样透传而不是另写一份实现——认领顺序与「待分类（开发期）」的归属
因此逐位不变。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QWidget


def build_ai_domain(dialog, claim: Callable[..., Any], claim_prefix: Callable[..., Any],
                    page_content: Callable[..., QWidget]) -> QWidget | None:
    """「AI 与对话」域整页；本构建没有 AI 页（no-chat 变体）时返回 None。"""
    if dialog.ai_page is None:
        return None
    balance_rows = claim_prefix("balance_")
    appearance_rows = claim(
        "chat_ui_style", "chat_background", "chat_background_file", "chat_background_opacity", "chat_background_fill", "chat_bg_crops", "modern_chat_card_opacity"
    )
    ai_sections = page_content(
        [
            ("API 列表", claim("provider_list")),
            (
                "模型与连接",
                claim(
                    "provider_name",
                    "api_url",
                    "model",
                    "api_key",
                    "system_prompt",
                    "connection_test",
                ),
            ),
            (
                "深度思考与联网",
                claim(
                    "thinking_mode",
                    "reasoning_effort",
                    "web_search_enabled",
                    "web_search_engine",
                    "web_search_key",
                    "web_search_max_results",
                    "web_search_fetch_pages",
                ),
            ),
            ("系统通知", claim("system_notifications_enabled")),
            (
                "视觉能力",
                claim(
                    "vision_same",
                    "vision_model",
                    "vision_url",
                    "vision_key",
                ),
            ),
            (
                "生成参数（高级）",
                claim(
                    "timeout",
                    "temperature",
                    "max_tokens",
                    "skip_ssl",
                ),
                True,
            ),
            ("对话窗口", appearance_rows),
            ("余额与服务状态", balance_rows),
        ]
    )
    ai_sections.setObjectName("settingsDomain_ai")
    # Keep the control owner alive for save/dependency behavior, but
    # visible rows now belong directly to the shared domain layout.
    dialog.ai_page.setParent(dialog)
    dialog.ai_page.hide()
    return ai_sections
