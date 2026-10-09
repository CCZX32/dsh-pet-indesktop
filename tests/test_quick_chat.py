# -*- coding: utf-8 -*-
"""QuickChatBubble 气泡外形 + 角色同步（B07）回归。"""
from __future__ import annotations

import os
import threading
import time

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


# ---------------------------------------------------------------- 切角色作废在途请求
class _BlockingProvider:
    """可控网络替身（只替换网络边界）：请求进来卡住，测试放行后才产出一条回答。"""

    def __init__(self, reply: str = "旧角色的回答") -> None:
        self.reply = reply
        self.started = threading.Event()
        self.release = threading.Event()

    def stream(self, messages, config, cancel):
        self.started.set()
        while not self.release.wait(timeout=0.02):
            if cancel.is_set():
                return
        if cancel.is_set():
            return
        yield self.reply


def _pump_until(predicate, *, timeout: float = 10.0) -> bool:
    """宽预算轮询 + 事件泵（worker→主线程的信号是队列投递，必须跑事件循环）。"""
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def _send_blocking_question(bubble, question: str = "你在吗"):
    """真 ChatService/QThread + 真会话存储：发一条问题并卡在请求中。"""
    provider = _BlockingProvider()
    bubble.service.provider = provider
    bubble.input.setText(question)
    bubble._send()
    assert provider.started.wait(timeout=10), "前提：请求已进入 provider"
    assert bubble._active_request_id is not None, "前提：请求在途"
    return provider


def test_switch_character_drops_inflight_answer(tmp_path):
    """切角色必须作废在途请求：旧角色的回答不许落进新角色的会话也不许上屏。

    旧行为：``switch_character`` 只换身份 + 重取会话，不清 ``_active_request_id``；
    旧角色那次请求的完成信号在切换之后到达时 ID 仍然匹配，回答被 append 进**新**
    角色的 session 并显示在新角色的气泡里。对照完整聊天窗
    （``chat/widgets.py::switch_character`` 清 request ID + 停旧请求）同款闸门。
    """
    app = QApplication.instance() or QApplication([])
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        provider = _send_blocking_question(bubble)

        bubble.switch_character("nova")
        assert bubble._active_request_id is None, "切角色即作废在途请求（ID 闸归零）"
        assert bubble.hint_label.text() == "", "旧请求不会再回来，思考中提示必须撤掉"

        provider.release.set()
        assert _pump_until(lambda: not bubble.service.busy), "旧 worker 未收尾"
        # 迟到信号（完成/增量/错误）全部被 ID 闸丢弃：既不落库也不上屏
        assert bubble.output.text() == "", "旧角色的回答不许显示在新角色的气泡里"
        assert not [m for m in bubble.session.messages if m.role == "assistant"], \
            "旧角色的回答不许写进新角色的会话"
        assert bubble.session.character_id == "nova"
    finally:
        bubble.close()
        app.processEvents()


def test_switch_character_without_inflight_request_only_swaps_session(tmp_path):
    """非回归：空闲切角色行为不变（只换身份 + 重取会话，不触碰在途状态字段）。"""
    app = QApplication.instance() or QApplication([])
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        assert bubble._active_request_id is None
        bubble.switch_character("nova")
        assert bubble.character_id == "nova"
        assert bubble.session.character_id == "nova"
        assert bubble._active_request_id is None
    finally:
        bubble.close()
        app.processEvents()