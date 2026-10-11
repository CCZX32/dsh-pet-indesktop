# -*- coding: utf-8 -*-
"""设置页文案「黑话」lint（设计稿 §四 C3 的机制化落地）。

判据（设计稿 §四）：标题/hint 里出现 ①全大写缩写（≥2 字母）②IP 地址 ③黑名单词表，
该行必须满足以下之一，否则 fail：

1. 它落在 advanced 折叠组或可折叠框内——同一任务里的低频参数，术语在这层是允许的；
2. 它在上面的域级/行级白名单里——每条都写明「为什么对用户是合法说法」。

为什么要有这条 lint：文案审查是人对人、会漏会疲劳；lint 是机制——新增设置的人写文案时
就被 CI 拦下，「foobar 黑话」这类问题在源头不再发生（GATES 准入记录里
``disclosure_level: primary|advanced`` 的自动化执行）。

**白名单不是垃圾桶**：加词必须改测试、留评审痕迹，且下面有一条防腐烂用例盯着
「白名单里的每个条目都还真的存在且真的命中」。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.modern_settings_dialog as settings_mod
from pet.config import Config
from pet.modern_settings_dialog import SettingRow, SettingsSection
from pet.settings_widgets import CollapsibleGroup

app = QApplication.instance() or QApplication([])

#: 全大写缩写（≥2 字母）。
_ABBREV = re.compile(r"[A-Z]{2,}")
#: IPv4 字面量（探测目标这类实现细节不许出现在主视线里）。
_IPV4 = re.compile(r"\d+\.\d+\.\d+\.\d+")
#: 黑名单词表：协议名 / 内部模块名 / 物理引擎术语 / 与 lint 同一族的旧黑话。
_BLACKLIST = ("SMTC", "UDP", "DNS", "甩出死区", "零初速", "网卡字节计数器", "foo_mediacontrol")

#: 域级豁免：本域目标用户必然懂这些词（设计稿 §四 C3 第二出口）。
_DOMAIN_WHITELIST: dict[str, frozenset[str]] = {
    # AI 域的用户就是在配 API——「API Key / API 地址」是他要处理的对象本身。
    "AI 与对话": frozenset({"API", "AI", "JSON", "SSL"}),
}

#: 行级豁免：行 key（去掉 ``settingRow_`` 前缀）→ 允许出现在该行文案里的 token。
_ROW_WHITELIST: dict[str, frozenset[str]] = {
    # 文件识别域：解释「交给谁」的产品级说法，不是内部代号。
    "file_interpret_enabled": frozenset({"AI"}),
    # 时间格式占位符：用户要照着它输入，属于输入语法而不是黑话。
    "voice_chime_custom_times": frozenset({"HH", "MM"}),
    "festival_reminder_times": frozenset({"HH", "MM"}),
    # 「无需 API Key」是在告诉用户不用配密钥（同一域的通用说法）。
    "voice_chime_voice": frozenset({"API"}),
    # 内置西文诗句库的作品名（圣经译本缩写），属作品署名。
    "festival_custom_quotes_west": frozenset({"KJV"}),
    # 免费视觉模型名：用户要按这个名字去服务商侧配置，删掉就无法照做。
    "proactive_free": frozenset({"GLM"}),
    # 自定义台词模板是 JSON：用户要复制/粘贴的就是它。
    "dialogue_mode": frozenset({"JSON"}),
    "dialogue_template_actions": frozenset({"AI", "JSON"}),
    # 流量/内存单位。
    "island_network": frozenset({"KB"}),
    "dynamic_island_icon_value": frozenset({"MB"}),
    # 岛指标段名：CPU/GPU 是用户日常词汇（段就叫这个名），不是实现黑话；
    # 内存行的 hint 如实说「与 CPU 共用同一条采样线程」。
    "island_cpu": frozenset({"CPU"}),
    "island_mem": frozenset({"CPU"}),
    "island_gpu": frozenset({"GPU"}),
    # 游戏帧率段：FPS 就是这一段在用户侧的名字（同 CPU / GPU 的口径），也是用户搜索
    # 这一行时打的词；hint 里的「Present FPS」正是在点明读数口径，不能改写掉。
    "island_fps": frozenset({"FPS"}),
    # 「AI 回复到达」是对话功能在用户侧的通用说法。
    "dynamic_island_hidden_chat": frozenset({"AI"}),
    "dynamic_island_event_effects": frozenset({"AI"}),
    # 菜单字体设置：「UI 字体」＝界面字体。
    "menu_font": frozenset({"UI"}),
    "menu_font_size": frozenset({"UI"}),
    # 菜单实际显示「公网 IP / IP 属地」，只说菜单里能看到的内容；KB 是取一次的量级。
    "network_info_menu": frozenset({"IP", "KB"}),
    # 推荐用户去装的第三方插件名（定稿明文保留，要能照着搜）。
    "foobar_lyrics": frozenset({"foo_mediacontrol"}),
    # 键盘按键名：用户要按的就是它。
    "shift_drag": frozenset({"SHIFT"}),
    # 直播软件名（用户自己的工具）。
    "stream_capture": frozenset({"OBS"}),
}


def _dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return settings_mod.ModernSettingsDialog(Config(base=tmp_path), include_ai=True)


def _tokens(text: str) -> frozenset[str]:
    """命中判据：缩写 ∪ IP 字面量 ∪ 黑名单词。"""
    found = set(_ABBREV.findall(text)) | set(_IPV4.findall(text))
    found |= {word for word in _BLACKLIST if word in text}
    return frozenset(found)


def _in_disclosure(row: SettingRow) -> bool:
    """行是否落在高级折叠组 / 可折叠框内（C3 的第一出口）。"""
    parent = row.parentWidget()
    while parent is not None:
        if isinstance(parent, CollapsibleGroup):
            return True
        if isinstance(parent, SettingsSection) and parent.advanced:
            return True
        parent = parent.parentWidget()
    return False


def _domain_of(dialog, row: SettingRow) -> str:
    for index in range(dialog.pages.count()):
        if dialog.pages.widget(index).isAncestorOf(row):
            return dialog.sidebar.item(index).text()
    return ""


def test_no_jargon_outside_advanced_groups(tmp_path, monkeypatch):
    """主视线（非高级组、非折叠框）里不许出现黑话；白名单例外逐条登记在上面。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        rows = dialog.findChildren(SettingRow)
        assert len(rows) > 150, "设置行没扫到（域装配可能变了），本用例会假绿"
        offenders = []
        for row in rows:
            key = row.objectName()[len("settingRow_"):]
            hits = _tokens(f"{row.label.text()}\n{row.hint_label.text()}")
            if not hits:
                continue
            allowed = _ROW_WHITELIST.get(key, frozenset())
            allowed |= _DOMAIN_WHITELIST.get(_domain_of(dialog, row), frozenset())
            if hits - allowed and not _in_disclosure(row):
                offenders.append(f"{key}: {sorted(hits - allowed)} | {row.label.text()}")
        assert not offenders, (
            "主视线里的设置行出现黑话（要么改文案，要么挪进高级折叠，"
            "要么在 _ROW_WHITELIST 里写明豁免理由）：\n" + "\n".join(offenders)
        )
    finally:
        dialog.close()


def test_whitelist_has_no_stale_entries(tmp_path, monkeypatch):
    """白名单不许腐烂：登记的行仍存在、登记的 token 仍真的命中。"""
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        rows = {row.objectName()[len("settingRow_"):]: row for row in dialog.findChildren(SettingRow)}
        stale = []
        for key, allowed in _ROW_WHITELIST.items():
            row = rows.get(key)
            if row is None:
                # 平台闸门（如 foobar / 直播捕获只在 Windows 建行）不算腐烂。
                continue
            hits = _tokens(f"{row.label.text()}\n{row.hint_label.text()}")
            unused = sorted(token for token in allowed if token not in hits)
            if unused:
                stale.append(f"{key}: {unused}")
        assert not stale, (
            "白名单条目已失效（文案改过或行删了，请同步收紧白名单）：\n" + "\n".join(stale)
        )
    finally:
        dialog.close()


#: 「逐宠」行文案不许出现的范围词：这些键一只一份（``PER_PET_KEYS``），
#: 承诺"所有桌宠"就是把每宠设置说成全局。
#:
#: 为什么要有这条机制：F06（2026-10-10 终审）抓到「播放速率」行写着
#: 「控制**所有**桌宠动画的播放速度」，而 ``playback_speed`` 从 B7b 起就是每宠键
#: （右键菜单的速率也只改被点的那一只）——修复报告当时称"已改"，交付字节里却没改。
#: 手工核一遍文案会漏、会疲劳；键集与文案的这层对应关系必须由机器盯着。
GLOBAL_SCOPE_WORDS = ("所有桌宠", "全部桌宠", "所有宠物")


def test_per_pet_rows_never_promise_a_global_scope(tmp_path, monkeypatch):
    """逐宠键的行文案不许说"所有桌宠"（范围真值 = ``PER_PET_KEYS``）。"""
    from pet import pet_profiles

    dialog = _dialog(tmp_path, monkeypatch)
    try:
        offenders = []
        scanned = 0
        for row in dialog.findChildren(SettingRow):
            key = row.objectName()[len("settingRow_"):]
            if key not in pet_profiles.PER_PET_KEYS:
                continue
            scanned += 1
            claimed = [word for word in GLOBAL_SCOPE_WORDS
                       if word in f"{row.label.text()}\n{row.hint_label.text()}"]
            if claimed:
                offenders.append(f"{key}: {claimed} | {row.hint_label.text()}")
        assert scanned >= 5, "逐宠行没扫到（键集或行名变了），本用例会假绿"
        assert not offenders, (
            "逐宠键的行文案承诺了全局范围（改成「这只桌宠」，或把键真的做成全局）：\n"
            + "\n".join(offenders)
        )
    finally:
        dialog.close()
