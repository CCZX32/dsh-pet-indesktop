# -*- coding: utf-8 -*-
"""设置页「按区直找」（2026-10-08）的行为验收。

三件事一起验：

1. **被压平的子分区恢复回来**：域装配原先把旧页的行用 ``findChildren`` 一把捞出、
   整体塞进单张卡片，旧页的「总开关与节奏 / 频率参数 / 触发条件 / 白名单」等子分区
   就此消失。``sections_in_layout_order`` 走真实布局树取回它们（创建顺序 ≠ 布局顺序
   时也得对，见第一个用例的合成页）。
2. **«自动化与联动» 顶层顺序 = 装配表顺序**：倒插（``insertWidget(0/1)``）已删除，
   顺序必须是 待办提醒 → 免打扰 → 主动识屏四组 → 消费统计 → Agent 联动（折叠）→
   文案风格与模板 → 自定义台词（折叠）。
3. **行一个不漏**：拆组只换容器，不换归属；任何一行掉进「待分类（开发期）」都算红。

纪律：断言走真实 ``ModernSettingsDialog`` 这个公开 seam；布局顺序由测试自己走
``layout().itemAt(...)`` 取（不调被测函数自证）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

import pet.modern_settings_dialog as settings_mod
from pet import settings_page_guide
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow, SettingsSection
from pet.settings_widgets import CollapsibleGroup, SettingsTabContainer

app = QApplication.instance() or QApplication([])

#: «自动化与联动» 域顶层顺序（定稿口径，见 ``_rebuild_domain_navigation`` 的装配表）。
_AUTOMATION_ORDER = [
    "待办提醒",
    "免打扰",
    "主动识屏 · 开关与节奏",
    "主动识屏 · 什么时候看",
    "主动识屏 · 看哪些软件",
    "主动识屏 · 细调（高级）",
    "消费统计",
    "box:Agent 联动",
    "文案风格与模板",
    "box:自定义台词（逐事件文案）",
]

#: 「主动识屏」四组 → 行键（顺序即组内呈现顺序）。
_PROACTIVE_GROUPS = (
    ("主动识屏 · 开关与节奏", ("proactive_enabled", "proactive_preset")),
    ("主动识屏 · 什么时候看",
     ("proactive_require_idle", "proactive_idle_seconds", "proactive_through", "proactive_pre_cue")),
    ("主动识屏 · 看哪些软件",
     ("proactive_whitelist", "proactive_whitelist_add", "proactive_memory_clear")),
    ("主动识屏 · 细调（高级）",
     ("proactive_dry_run", "proactive_dwell", "proactive_cooldown",
      "proactive_min_interval", "proactive_daily_cap", "proactive_free")),
)


def _dialog(tmp_path, monkeypatch, *, include_ai: bool = True):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return ModernSettingsDialog(Config(base=tmp_path), include_ai=include_ai)


def _page(dialog, domain: str) -> QWidget:
    index = next(i for i in range(dialog.sidebar.count())
                 if dialog.sidebar.item(i).text() == domain)
    return dialog.pages.widget(index)


def _content(dialog, domain: str, tab_key: str | None = None) -> QWidget:
    """域页的可滚动内容；页内标签域取指定标签的页内容。"""
    content = _page(dialog, domain).findChild(QScrollArea, "settingsScroll").widget()
    tabs = content if isinstance(content, SettingsTabContainer) else content.findChild(
        SettingsTabContainer, "settingsTaskTabs")
    if tabs is not None:
        if tab_key is not None:
            tabs.setCurrentKey(tab_key)
        content = tabs.stack.currentWidget()
    return content


def _top_level_titles(content: QWidget) -> list[str]:
    """内容里顶层块的标题，按真实布局顺序；折叠框用 ``box:`` 前缀标出。"""
    titles = []
    layout = content.layout()
    for position in range(layout.count()):
        widget = layout.itemAt(position).widget()
        if isinstance(widget, CollapsibleGroup):
            titles.append(f"box:{widget.toggle.text()}")
        elif isinstance(widget, SettingsSection):
            titles.append(_title_of(widget))
    return titles


def _title_of(section: SettingsSection) -> str:
    if section.toggle is not None:
        return section.toggle.text()
    label = section.findChild(QLabel, "sectionTitle")
    return label.text() if label is not None else ""


def _section(dialog, domain: str, title: str, tab_key: str | None = None) -> SettingsSection:
    content = _content(dialog, domain, tab_key)

    def find(node: QWidget):
        layout = node.layout()
        if layout is None:
            return None
        for position in range(layout.count()):
            widget = layout.itemAt(position).widget()
            if widget is None:
                continue
            if isinstance(widget, CollapsibleGroup):
                hit = find(widget.body)
                if hit is not None:
                    return hit
            elif isinstance(widget, SettingsSection) and _title_of(widget) == title:
                return widget
        return None

    found = find(content)
    assert found is not None, f"「{domain}」域里没有标题为「{title}」的分区"
    return found


def _row(dialog, key: str) -> SettingRow:
    row = dialog.findChild(SettingRow, f"settingRow_{key}")
    assert row is not None, f"缺少设置行 {key}"
    return row


# ------------------------------------------------------------------ 布局顺序辅助函数
def test_layout_order_helper_follows_the_layout_not_the_creation_order():
    """创建顺序与布局顺序不一致时，取到的必须是用户在页面上看到的顺序。

    旧机制（``findChildren``）给的是创建顺序：两处偶然一致，一处不一致就静默错位
    ——这正是「按区直找」要拆掉的隐患，故用合成页正面钉住。
    """
    page = QWidget()
    layout = QVBoxLayout(page)
    built = [
        SettingsSection(title, [SettingRow(key, title, "", QWidget(), page)], page)
        for key, title in (("c", "第三"), ("a", "第一"), ("b", "第二"))
    ]
    for section in (built[1], built[2], built[0]):  # 布局顺序 第一 / 第二 / 第三
        layout.addWidget(section)

    assert page.findChildren(SettingsSection) == built, "合成页的创建顺序必须是 第三/第一/第二"
    assert [title for title, _rows in settings_page_guide.sections_in_layout_order(page)] == [
        "第一", "第二", "第三"]
    assert [row.objectName() for row in settings_page_guide.rows_in_layout_order(page)] == [
        "settingRow_a", "settingRow_b", "settingRow_c"]


def test_rows_in_layout_order_keeps_rows_outside_any_section():
    """没被分区收走的行不许静默丢失（按创建顺序垫在后面）。"""
    page = QWidget()
    layout = QVBoxLayout(page)
    loose = SettingRow("loose", "散行", "", QWidget(), page)
    section = SettingsSection("有主的", [SettingRow("owned", "有主", "", QWidget(), page)], page)
    layout.addWidget(section)
    layout.addWidget(loose)

    assert [row.objectName() for row in settings_page_guide.rows_in_layout_order(page)] == [
        "settingRow_owned", "settingRow_loose"]


# --------------------------------------------------------------------- 主动识屏四组
def test_proactive_rows_are_split_back_into_four_groups(tmp_path, monkeypatch):
    """15 行拆成 4 组（开关与节奏 / 什么时候看 / 看哪些软件 / 细调（高级）），一个不漏。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        titles = [title for title, _rows in settings_page_guide.sections_in_layout_order(
            _content(dialog, "自动化与联动"))]
        for title, _keys in _PROACTIVE_GROUPS:
            assert title in titles, f"「{title}」必须作为独立分区出现在页面上"

        for title, keys in _PROACTIVE_GROUPS:
            section = _section(dialog, "自动化与联动", title)
            assert [row.objectName() for row in section.rows] == [
                f"settingRow_{key}" for key in keys], f"「{title}」的成员或顺序不符"
        # 只有「细调」是高级折叠组（低频参数一层披露）。
        assert _section(dialog, "自动化与联动", "主动识屏 · 细调（高级）").advanced is True
        for title, _keys in _PROACTIVE_GROUPS[:3]:
            assert _section(dialog, "自动化与联动", title).advanced is False

        # 15 行全部有主、没有漏进「待分类（开发期）」。
        total = sum(len(keys) for _title, keys in _PROACTIVE_GROUPS)
        assert total == 15, "分组表自身必须覆盖旧页全部 15 行"
        for _title, keys in _PROACTIVE_GROUPS:
            for key in keys:
                assert _page(dialog, "自动化与联动").isAncestorOf(_row(dialog, key))
        assert "待分类（开发期）" not in [
            label.text() for label in dialog.findChildren(QLabel)]
    finally:
        dialog.close()


# --------------------------------------------------------- 自动化与联动：顶层顺序重排
def test_automation_domain_top_level_order_is_the_assembly_table(tmp_path, monkeypatch):
    """顶层顺序 = 装配表顺序；「消费统计」不再靠 insertWidget 倒插到最前面。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert _top_level_titles(_content(dialog, "自动化与联动")) == _AUTOMATION_ORDER
        # 折叠框仍在表里、默认收起（口径未变）。
        assert dialog.agent_link_box.is_expanded() is False
        assert dialog.dialogue_phrases_box.is_expanded() is False
    finally:
        dialog.close()


def test_agent_box_and_phrase_box_are_prebuilt_widgets_in_the_table(tmp_path, monkeypatch):
    """两个折叠框作为已构造好的 QWidget 直接进装配表（``page_content`` 可收 widget）。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        box = dialog.agent_link_box
        content = _content(dialog, "自动化与联动")
        assert box.parentWidget() is content, "折叠框必须被 page_content 收养进页内容"
        assert dialog.dialogue_phrases_box.parentWidget() is content
        assert box.isAncestorOf(_row(dialog, "agent_sound_enabled"))
        assert not box.isAncestorOf(_row(dialog, "agent_cost")), "消费统计留在折叠框外"
    finally:
        dialog.close()


# ------------------------------------------------------------------- 语音域：3 + 3 组
def test_voice_and_festival_domains_split_into_three_groups_each(tmp_path, monkeypatch):
    """语音报时 12 行（何时报 / 用什么声音 / 说什么）与节日提醒 12 行（开关 / 时间 /
    文案）各自拆回 3 个小分组；行数与行归属一个不变。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert _top_level_titles(_content(dialog, "语音")) == [
            "语音报时 · 何时报",
            "语音报时 · 用什么声音",
            "语音报时 · 说什么",
            "节日提醒 · 开关",
            "节日提醒 · 时间",
            "节日提醒 · 文案",
        ]
        expected = {
            "语音报时 · 何时报": ("voice_chime_enabled", "voice_chime_schedule", "voice_chime_custom_times"),
            "语音报时 · 用什么声音": ("voice_chime_voice", "voice_chime_rate", "voice_chime_pitch", "voice_chime_volume"),
            "语音报时 · 说什么": ("voice_chime_show_bubble", "voice_chime_show_quote",
                             "voice_chime_custom_quotes_zh", "voice_chime_custom_quotes_en", "voice_chime_preview"),
            "节日提醒 · 开关": ("festival_reminder_enabled", "festival_reminder_cn",
                           "festival_reminder_solar_terms", "festival_reminder_west", "festival_reminder_speak"),
            "节日提醒 · 时间": ("festival_reminder_mode", "festival_reminder_count", "festival_reminder_times"),
            "节日提醒 · 文案": ("festival_reminder_show_quote", "festival_custom_quotes_cn",
                           "festival_custom_quotes_west", "festival_preview"),
        }
        for title, keys in expected.items():
            section = _section(dialog, "语音", title)
            assert [row.objectName() for row in section.rows] == [
                f"settingRow_{key}" for key in keys], f"「{title}」的成员或顺序不符"
        assert sum(len(keys) for keys in expected.values()) == 24, "两个页共 24 行必须全覆盖"
        # 「立即试听」仍在 SettingRow 里（历史事故：没包进行里就不会被域收集搬运）。
        assert _page(dialog, "语音").isAncestorOf(_row(dialog, "voice_chime_preview"))
        assert "待分类（开发期）" not in [
            label.text() for label in dialog.findChildren(QLabel)]
    finally:
        dialog.close()


# --------------------------------------------------- 桌面胶囊：压平仍是定稿口径（不动）
def test_desktop_island_keeps_its_single_flattened_card(tmp_path, monkeypatch):
    """「桌面胶囊（灵动岛）」的压平是定稿口径（见装配处注释），本刀不拆——只有探测
    间隔（高级）一项另立。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert _top_level_titles(_content(dialog, "桌面组件")) == [
            "桌面胶囊（灵动岛）", "网络延迟检测（高级）"]
        card = _section(dialog, "桌面组件", "桌面胶囊（灵动岛）")
        names = {row.objectName() for row in card.rows}
        assert {"settingRow_dynamic_island_enabled", "settingRow_island_network",
                "settingRow_island_cpu"} <= names, "岛行不分家，整表在同一张卡里"
        assert "settingRow_network_probe_interval" not in names
    finally:
        dialog.close()
