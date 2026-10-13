# -*- coding: utf-8 -*-
"""设置页「自动化与联动」域：整段行构造（分组表 + 两个折叠框 + 域页）。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算已无余量，本域
约 55 行构造搬到这里，对话框只留一处调用（``build_automation_domain``）。

**本域包含的分组**（下表顺序即页上顺序，契约见 ``tests/test_settings_ia_first_cut.py``
与旧页分区）：待办提醒 / 免打扰（``settings_quiet`` 构建）/ 主动识屏四组（开关与
节奏 · 什么时候看 · 看哪些软件 · 细调（高级））/ 消费统计 / Agent 联动折叠框
（提示音效）/ 文案风格与模板 / 自定义台词折叠框。

**「语音报时」「节日提醒」不在本域**：这两组的分组表留在对话框里，属另一个域
（「语音」）——本模块只管「自动化与联动」自己那几组。

**签名说明**：``claim`` / ``claim_prefix`` / ``page_content`` 是
``_rebuild_domain_navigation`` 的局部装配助手（闭包捕获对话框的行快照与已认领
集合），``claimed`` 是同一集合本身。这里原样透传而不是另写一份实现——两个折叠框
内的行必须登记进 ``claimed``，否则会再落进「待分类（开发期）」，认领顺序与归属
因此逐位不变。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QWidget

from . import settings_quiet
from .settings_widgets import CollapsibleGroup, SettingRow


def build_automation_domain(dialog, claim: Callable[..., Any], claim_prefix: Callable[..., Any],
                            page_content: Callable[..., QWidget], claimed: set) -> QWidget:
    """「自动化与联动」域整页（行键顺序沿用旧页分区重组口径）。"""
    # 「主动识屏」的旧页分区在域装配时被压平成单张卡片，这里按行键重组（行键以
    # 代码实际为准，顺序同旧页）；「语音报时」「节日提醒」的同名重组留在对话框里
    # （那两组属「语音」域）。
    proactive_sections = [
        # 执行位置两行（S3）：真设置 proactive_execution + 只读状态行
        # proactive_worker_status。放在「开关与节奏」而不是新开一组——本域
        # 的四组划分是既有契约（tests/test_settings_page_guide.py）。
        ("主动识屏 · 开关与节奏", claim("proactive_enabled", "proactive_execution",
                                    "proactive_worker_status", "proactive_preset")),
        ("主动识屏 · 什么时候看", claim("proactive_require_idle", "proactive_idle_seconds", "proactive_through", "proactive_pre_cue")),
        ("主动识屏 · 看哪些软件", claim("proactive_whitelist", "proactive_whitelist_add", "proactive_memory_clear")),
        ("主动识屏 · 细调（高级）", claim("proactive_dry_run", "proactive_dwell", "proactive_cooldown",
                                    "proactive_min_interval", "proactive_daily_cap", "proactive_free"), True),
    ]
    dialogue_rows = claim_prefix("dialogue_")
    # 「自定义台词」＝一个可折叠框（默认折叠）：逐事件文案行全部收进去，
    # 不用自定义台词的用户不该翻过整页文案框；搜索命中时会自动展开
    # （见 _search_settings）。全局风格控件（表达风格/专属文案对象/模板 JSON）
    # 不是事件文案，单独放「文案风格与模板」小节。
    phrases_box = CollapsibleGroup("自定义台词（逐事件文案）", dialog)
    phrase_edit_keys = set(dialog.dialogue_phrase_edits)
    phrase_rows = [row for row in dialogue_rows
                   if row.objectName()[len("settingRow_dialogue_"):] in phrase_edit_keys]
    ungated_dialogue_rows = [row for row in dialogue_rows
                             if row.objectName()[len("settingRow_dialogue_"):] not in phrase_edit_keys]
    if phrase_rows:
        phrases_box.add_group("事件气泡文案", phrase_rows)
    phrases_box.set_expanded(False)
    dialog.dialogue_phrases_box = phrases_box
    # 「Agent 联动」折叠框只装「提示音效」子组（默认折叠）；「消费统计」已独立成
    # 一级分组留在框外（见本域 sections 表）。用现成的 CollapsibleGroup.add_group。
    agent_box = CollapsibleGroup("Agent 联动", dialog)
    agent_cost_rows = [
        SettingRow("agent_cost", "显示本轮消费",
                   "Agent 每轮结束时查询一次余额，与开始时的余额相减得出本轮消费。"
                   "仅 DeepSeek 提供余额接口；余额精度为分，不足 ¥0.01 的消耗测不出。",
                   dialog.agent_cost_check),
    ]
    agent_box.add_group("提示音效", claim_prefix("agent_sound_"))
    # 默认折叠：6 行提示音效不该首屏铺开；消费统计是独立一级分组，留在框外。
    agent_box.set_expanded(False)
    dialog.agent_link_box = agent_box
    # 这些行已被上面的折叠框认领，必须登记，否则会再落进「待分类」。
    claimed.update(agent_cost_rows)
    claimed.update(claim_prefix("agent_sound_"))
    # dialogue_* 里的全局风格控件（表达风格、专属文案对象、弹窗文案模板 JSON）
    # 不是某个事件的气泡文案，已被 claim_prefix("dialogue_") 认领（不再进
    # leftovers），若不显式放回本域就会从设置页里彻底消失。
    # 顶层顺序就是下表顺序（没有倒插）；折叠框是已构造好的 QWidget，直接作为表元素进布局。
    return page_content(
        [
            ("待办提醒", claim("todo_reminder_enabled", "todo_reminder_lead_minutes")),
            # 「免打扰」两行在本模块构建（settings_quiet，行数预算原因）。
            ("免打扰", settings_quiet.build_quiet_rows(dialog)),
            *proactive_sections,
            ("消费统计", agent_cost_rows),
            agent_box,
            ("文案风格与模板", ungated_dialogue_rows),
            phrases_box,
        ]
    )
