# -*- coding: utf-8 -*-
"""AI 对话酒馆化：场景卡 + 扮演格式引导 + 括号动作段渲染。

钉住四件事：
- 三个配置键是**每宠键**（真值在 slot 档案，默认关）；
- 引导段逐字照 spec、只在 roleplay_enabled + 已注入 persona 时追加；
- 场景卡空 = 只有引导段，非空才追加场景卡（cast 多行原样透传）；
- modern 聊天窗把全角/半角/跨行括号动作段渲染成斜体弱色，落盘原文不变。
"""
from __future__ import annotations

import json

import pytest

from pet.chat.models import ChatMessage, ChatSettings
from pet.chat.prompt import PromptBuilder

# spec v2「扮演引导」定稿文案（逐字，不得改写语义）。v2 的重点是场景发散：
# 环境细节 + 在场其他人主动参与 + 每轮都要有推进，而不是两个人轮流对台词。
ROLEPLAY_GUIDE = (
    "你在和用户进行场景扮演。目标不是「你一句我一句地对台词」，而是让这个场景活着往前走。\n"
    "① 一轮回复里通常同时有三样东西（写成自然段落，不必分条）：你的台词（带动作或神态）、"
    "一个能被感知的环境细节（声音、光线、气味、气氛、时间在流逝），以及在场其他人的动静。"
    "环境不必每轮写满，但别让场景塌成白底上的两个人说话。\n"
    "② 在场的人有自己的目的和小动作：会插话、会看眼色、会起哄、会打断，也可能带来新信息"
    "或小麻烦。多人场景可以一人一句短促交替，不必每句话都由你来说。\n"
    "③ 每轮至少让场景往前走一小步——有人换了位置、有人说了句意外的话、有新东西被注意到、"
    "气氛变了。不要用「嗯」「是吗」这类空转把球直接踢回给用户。\n"
    "④ 场景转换、新人物入场、或隔了较长时间：用一段旁白交代新场景和在场的每个人"
    "（一个外貌特征加一个说话/习惯特征），照着场景卡写，场景卡没有就自己编但前后保持一致。"
    "名字一旦定下就不要改，没名字的路人给个临时称呼（「穿灰西装的男人」）。\n"
    "⑤ 可以主动发散：引入合理的环境元素或新角色（路过的旁人、突然的声响、电话、天气变化、"
    "外面的动静），只要与场景卡不冲突、并给用户留出接话的空间。\n"
    "⑥ 节奏：一次回复两三句到一小段为宜，别写成整章小说，也别把所有线索一次抖完。\n"
    "⑦ 绝不替用户做决定，不写用户的动作、台词和心理——用户的（动作）是剧情的一部分，"
    "接着演，不重复不点评。\n"
    "⑧ 场景卡是硬设定：与场景卡冲突时以场景卡为准。"
)


def _system(**kwargs) -> str:
    """走真实 PromptBuilder.build_messages，取 system 段。"""
    kwargs.setdefault("role_prompt", "你是测试角色。")
    messages = PromptBuilder().build_messages(
        ChatSettings(),
        "test-character",
        [],
        "你好",
        now=None,
        **kwargs,
    )
    return messages[0]["content"]


def _write_config(tmp_path, payload: dict) -> None:
    from pet import config as config_mod

    cfg_dir = tmp_path / config_mod.APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, **payload}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- prompt 注入
def test_guide_is_injected_only_when_enabled():
    off = _system(roleplay_enabled=False)
    assert ROLEPLAY_GUIDE not in off

    on = _system(roleplay_enabled=True)
    assert ROLEPLAY_GUIDE in on


def test_guide_uses_the_exact_spec_wording():
    system = _system(roleplay_enabled=True)
    assert ROLEPLAY_GUIDE in system
    # 五条编号一个不少、顺序不变（逐字文案已在上面的常量里固定）。
    positions = [system.index(marker) for marker in ("①", "②", "③", "④", "⑤")]
    assert positions == sorted(positions)


def test_guide_is_skipped_when_no_persona_was_injected():
    """roleplay_enabled 但 persona 段为空：按 spec「已注入 persona 时」不追加。"""
    messages = PromptBuilder().build_messages(
        ChatSettings(default_system_prompt=""),
        "test-character",
        [],
        "你好",
        roleplay_enabled=True,
        roleplay_scene="雨夜便利店",
        roleplay_cast="店员阿澈：总在擦杯子",
    )
    system = messages[0]["content"]
    assert ROLEPLAY_GUIDE not in system
    assert "雨夜便利店" not in system


def test_guide_is_appended_after_persona():
    persona = "你是测试角色。"
    system = _system(role_prompt=persona, roleplay_enabled=True)
    assert system.index(persona) < system.index(ROLEPLAY_GUIDE)


def test_empty_scene_card_keeps_only_the_guide():
    system = _system(roleplay_enabled=True, roleplay_scene="", roleplay_cast="")
    assert ROLEPLAY_GUIDE in system
    assert "【场景卡】" not in system


def test_scene_card_is_injected_when_non_empty():
    scene = "雨夜的便利店，灯管忽明忽暗。"
    system = _system(
        roleplay_enabled=True,
        roleplay_scene=scene,
        roleplay_cast="店员阿澈：总在擦同一个杯子，说话前先叹口气。",
    )
    assert ROLEPLAY_GUIDE in system
    assert "【场景卡】" in system
    assert scene in system
    assert "店员阿澈：总在擦同一个杯子，说话前先叹口气。" in system


def test_only_scene_or_only_cast_also_forms_a_scene_card():
    only_scene = _system(roleplay_enabled=True, roleplay_scene="天台，风很大。", roleplay_cast="")
    assert "【场景卡】" in only_scene and "天台，风很大。" in only_scene

    only_cast = _system(
        roleplay_enabled=True,
        roleplay_scene="",
        roleplay_cast="阿澈：叹气\n小满：转笔",
    )
    assert "【场景卡】" in only_cast
    assert "阿澈：叹气\n小满：转笔" in only_cast


def test_multiline_cast_is_passed_through_verbatim():
    cast = "阿澈：总在擦同一个杯子，说话前先叹口气。\n小满：爱转笔，一紧张就把笔帽咬在嘴里。\n老周：看谁都先眯眼。"
    system = _system(roleplay_enabled=True, roleplay_cast=cast)
    assert cast in system


def test_scene_and_cast_are_only_sent_when_enabled():
    scene = "雨夜的便利店。"
    cast = "阿澈：擦杯子"
    for kwargs in (
        {"roleplay_scene": scene, "roleplay_cast": cast},
        {"roleplay_enabled": False, "roleplay_scene": scene, "roleplay_cast": cast},
    ):
        system = _system(**kwargs)
        assert scene not in system
        assert cast not in system


# ---------------------------------------------------------------- 配置键纪律
def test_roleplay_defaults_are_off_and_empty(tmp_path):
    from pet.config import Config

    cfg = Config(base=tmp_path)
    assert cfg.data["roleplay_enabled"] is False
    assert cfg.data["roleplay_scene"] == ""
    assert cfg.data["roleplay_cast"] == ""


def test_roleplay_keys_are_per_pet(tmp_path):
    """三个键必须在每宠键集里（读错层 = 前科回归）。"""
    from pet import pet_profiles
    from pet.config import Config

    assert {"roleplay_enabled", "roleplay_scene", "roleplay_cast"} <= set(
        pet_profiles.PER_PET_KEYS
    )
    defaults = Config(base=tmp_path).data
    assert {"roleplay_enabled", "roleplay_scene", "roleplay_cast"} <= set(defaults)


def test_roleplay_values_are_normalized_on_load(tmp_path):
    from pet.config import Config

    _write_config(
        tmp_path,
        {
            "roleplay_enabled": "true",
            "roleplay_scene": "  " + "场" * 600 + "  ",
            "roleplay_cast": "人" * 700,
        },
    )
    cfg = Config(base=tmp_path)
    assert cfg.data["roleplay_enabled"] is True
    assert cfg.data["roleplay_scene"] == "场" * 500
    assert cfg.data["roleplay_cast"] == "人" * 600

    _write_config(
        tmp_path / "dirty",
        {
            "roleplay_enabled": "false",
            "roleplay_scene": 42,
            "roleplay_cast": ["not", "text"],
        },
    )
    dirty = Config(base=tmp_path / "dirty")
    assert dirty.data["roleplay_enabled"] is False
    assert dirty.data["roleplay_scene"] == ""
    assert dirty.data["roleplay_cast"] == ""


def test_roleplay_keys_live_in_each_slot_profile(tmp_path):
    """不同角色/槽位各存各的场景卡，互不覆盖。"""
    from pet import pet_profiles
    from pet.config import Config

    cfg_dir = Config(base=tmp_path).dir
    first = pet_profiles.write_profile_settings(
        cfg_dir,
        1,
        {
            "roleplay_enabled": True,
            "roleplay_scene": "一号角色的雨夜便利店。",
            "roleplay_cast": "阿澈：擦杯子",
        },
    )
    second = pet_profiles.write_profile_settings(
        cfg_dir,
        2,
        {
            "roleplay_enabled": True,
            "roleplay_scene": "二号角色的天台。",
            "roleplay_cast": "小满：转笔",
        },
    )
    assert first.ok and second.ok

    one = Config(base=tmp_path, instance_id="slot-1")
    two = Config(base=tmp_path, instance_id="slot-2")
    assert one.get("roleplay_enabled") is True
    assert one.get("roleplay_scene") == "一号角色的雨夜便利店。"
    assert one.get("roleplay_cast") == "阿澈：擦杯子"
    assert two.get("roleplay_scene") == "二号角色的天台。"
    assert two.get("roleplay_cast") == "小满：转笔"


# ---------------------------------------------------------------- 显示层
def _fragments(html: str):
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    doc = QTextDocument()
    doc.setHtml(html)
    found = []
    block = doc.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                color = fmt.foreground().color()
                found.append((fragment.text(), fmt.fontItalic(), color.alpha()))
            iterator += 1
        block = block.next()
    return found


def _action_fragments(html: str):
    return [item for item in _fragments(html) if item[1]]


@pytest.mark.parametrize(
    "text,action_text",
    [
        ("（她抬眼看你）台词", "（她抬眼看你）"),
        ("(she looks up) line", "(she looks up)"),
    ],
)
def test_parenthesized_action_is_italic_and_weak(text, action_text):
    from pet.chat.markdown_view import markdown_to_html

    html = markdown_to_html(text)
    actions = _action_fragments(html)
    assert actions, html
    assert any(action_text in fragment_text for fragment_text, _italic, _alpha in actions)
    assert all(alpha < 255 for _text, _italic, alpha in actions)
    dialogue = [item for item in _fragments(html) if not item[1]]
    assert any("台词" in item[0] or "line" in item[0] for item in dialogue)


def test_multiline_action_is_rendered_as_one_italic_weak_segment():
    from pet.chat.markdown_view import markdown_to_html

    html = markdown_to_html("第一句\n（动作一\n动作二）\n第二句")
    actions = _action_fragments(html)
    assert actions
    action_text = "".join(text for text, _italic, _alpha in actions)
    assert "动作一" in action_text and "动作二" in action_text
    assert all(alpha < 255 for _text, _italic, alpha in actions)
    # 台词部分不被动作样式连坐。
    dialogue = "".join(text for text, italic, _alpha in _fragments(html) if not italic)
    assert "第一句" in dialogue and "第二句" in dialogue


def test_code_fence_parentheses_are_not_treated_as_actions():
    from pet.chat.markdown_view import markdown_to_html

    html = markdown_to_html("```\nfunc(x)\n```")
    assert not _action_fragments(html)


def test_rendering_never_mutates_the_original_text(tmp_path):
    """纯展示层：渲染不写回原文，会话落盘也逐字保持。"""
    from pet.chat.markdown_view import markdown_to_html
    from pet.chat.session_store import SessionStore

    raw = "（动作）台词\n（第二段动作）"
    before = str(raw)
    html = markdown_to_html(raw)
    assert raw == before
    assert "font-style:italic" in html
    assert raw not in html  # HTML 里是带样式标签的版本，不是原文

    store = SessionStore(tmp_path)
    session = store.create("test-character", "p", "system")
    session.messages.append(ChatMessage("assistant", raw))
    assert store.save(session)
    assert store.flush()
    loaded = store.load(session.session_id, "test-character")
    assert loaded is not None
    assert loaded.messages[0].content == raw


# ---------------------------------------------------------------- 设置 UI
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _settings_dialog(tmp_path, monkeypatch, slot: int):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return settings_mod.ModernSettingsDialog(
        Config(base=tmp_path, instance_id=f"slot-{slot}"),
        include_ai=True,
        standalone=True,
    )


def test_settings_group_is_mounted_with_its_guide(tmp_path, monkeypatch, qapp):
    from pet.modern_settings_dialog import SettingRow
    from pet.settings_page_guide import SECTION_GUIDE

    dialog = _settings_dialog(tmp_path, monkeypatch, 1)
    try:
        pages = [dialog.pages.widget(i) for i in range(dialog.pages.count())]
        for key in ("roleplay_enabled", "roleplay_scene"):
            row = dialog.findChild(SettingRow, f"settingRow_{key}")
            assert row is not None, key
            assert any(page.isAncestorOf(row) for page in pages), key
        assert dialog.ai_page.roleplay_scene_btn.text() == "场景卡…"
        assert "场景扮演" in SECTION_GUIDE
        assert "人设" in SECTION_GUIDE["场景扮演"]
        assert "场景卡" in SECTION_GUIDE["场景扮演"]
        assert "留空则只开启扮演格式，不约束设定" in dialog.findChild(
            SettingRow, "settingRow_roleplay_scene"
        ).hint_label.text()
    finally:
        dialog.close()
        qapp.processEvents()


def test_scene_dialog_enforces_limits_and_has_example_placeholders(qapp):
    from pet.chat.ai_settings_page import RoleplaySceneDialog

    dialog = RoleplaySceneDialog("", "")
    try:
        assert dialog.scene_edit.placeholderText()
        assert dialog.cast_edit.placeholderText()
        dialog.scene_edit.setPlainText("场" * 600)
        dialog.cast_edit.setPlainText("人" * 700)
        scene, cast = dialog.values()
        assert len(scene) == 500
        assert len(cast) == 600
    finally:
        dialog.deleteLater()


def test_settings_save_routes_roleplay_keys_to_each_slot(tmp_path, monkeypatch, qapp):
    """走公开设置窗 seam：两只宠各存各的场景卡，主配置里不留每宠真值。"""
    from pet.config import Config

    for slot, scene in ((1, "一号角色的场景。"), (2, "二号角色的场景。")):
        dialog = _settings_dialog(tmp_path, monkeypatch, slot)
        try:
            dialog.ai_page.roleplay_enabled.setChecked(True)
            dialog.ai_page._roleplay_scene = scene
            dialog.ai_page._roleplay_cast = f"角色{slot}：一句描述"
            assert dialog._write_config() is True
        finally:
            dialog.close()
            qapp.processEvents()

    one = Config(base=tmp_path, instance_id="slot-1")
    two = Config(base=tmp_path, instance_id="slot-2")
    assert one.get("roleplay_scene") == "一号角色的场景。"
    assert two.get("roleplay_scene") == "二号角色的场景。"
    assert one.get("roleplay_cast") == "角色1：一句描述"
    assert two.get("roleplay_cast") == "角色2：一句描述"

    main = json.loads(Config(base=tmp_path).path.read_text(encoding="utf-8"))
    assert "roleplay_scene" not in main
    assert "roleplay_cast" not in main
    assert "roleplay_enabled" not in main
