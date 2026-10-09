# -*- coding: utf-8 -*-
"""QuickChatBubble 气泡外形 + 角色同步（B07）回归。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.quick_chat import _surface_radius
from pet.speech_bubble import BUBBLE_STYLE_PRESETS


def test_breath_bubble_preset_gets_rounded_fallback_radius():
    """breath_bubble 是 speech_bubble 专属有机形（preset 里 radius=0）：
    quick_chat 不支持该形状，直接按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置两套观感。必须给大圆角近似回退。"""
    preset = BUBBLE_STYLE_PRESETS["breath_bubble"]
    assert preset.get("shape") == "breath_bubble"
    assert _surface_radius(preset) > 0


def test_regular_preset_uses_own_radius():
    """普通预设用自己的 radius（回退不得影响既有外观）。"""
    preset = BUBBLE_STYLE_PRESETS["classic_top"]
    assert _surface_radius(preset) == float(preset.get("radius", 14))


# ---------------------------------------------------------------- 角色同步（B07）
def test_switch_character_moves_session_and_prompt_to_new_character(tmp_path):
    """B07：切角色后气泡必须按新角色取会话、按新角色构造 prompt。

    气泡的角色是构造期一次性快照（``character_id`` + 会话 + 系统提示全按它取），
    主宠切角色不同步就等于聊天面永远停在旧角色。
    """
    app = QApplication.instance() or QApplication([])
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        assert bubble.character_id == "shenshen"
        bubble.switch_character("nova")
        assert bubble.character_id == "nova"
        # 会话按新角色取（旧角色的会话不再沿用）
        assert bubble.session.character_id == "nova"
        assert bubble.session.system_prompt == bubble.prompt_builder.effective_system_prompt(
            bubble.settings, "nova")
        # prompt 链路跟着新角色走
        messages = bubble.prompt_builder.build_messages(
            bubble.settings, bubble.character_id, [], "在吗")
        assert messages[0]["content"] == bubble.session.system_prompt
    finally:
        bubble.close()
        app.processEvents()


def test_switch_character_ignores_empty_and_same_character(tmp_path):
    """空身份/同角色不动作（会话不被无谓重建，避免丢掉当前会话）。"""
    app = QApplication.instance() or QApplication([])
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        session = bubble.session
        bubble.switch_character("")
        assert bubble.character_id == "shenshen" and bubble.session is session
        bubble.switch_character("shenshen")
        assert bubble.session is session
    finally:
        bubble.close()
        app.processEvents()