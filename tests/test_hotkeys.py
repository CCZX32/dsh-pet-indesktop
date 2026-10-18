# -*- coding: utf-8 -*-
"""全局快捷键：文本口径（``hotkey_spec``）与服务（``hotkeys``）的回归。

**不碰真实系统**：``user32`` 是注入的替身（内部维护"已占用组合"表），原生消息
由手工构造的 ``MSG`` 喂进 ``nativeEventFilter``，所以这些用例在 CI 的三个平台上
都能跑（非 Windows 走 ``supported=False`` 那条路）。
"""
from __future__ import annotations

import ctypes
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import hotkey_spec as spec
from pet import hotkeys
from pet.hotkeys import GlobalHotkeyService


# ---------------------------------------------------------------- 文本口径
@pytest.mark.parametrize("text,expected", [
    ("Ctrl+Alt+P", (spec.MOD_CONTROL | spec.MOD_ALT, 0x50)),
    ("ctrl+shift+f9", (spec.MOD_CONTROL | spec.MOD_SHIFT, 0x78)),
    ("Alt+Space", (spec.MOD_ALT, 0x20)),
    ("Win+F1", (spec.MOD_WIN, 0x70)),
    (" Meta + num5 ", (spec.MOD_WIN, 0x65)),
])
def test_parse_accepts_common_combinations(text, expected):
    assert spec.parse(text) == expected


@pytest.mark.parametrize("text", [
    "P",            # 没有修饰键：会抢走整个系统的普通打字
    "Ctrl",         # 只有修饰键
    "Ctrl+P+Q",     # 两个普通键
    "Ctrl+",        # 残缺
    "Ctrl+Alt+😂",   # 白名单外
    "",
    None,
])
def test_parse_rejects_unsafe_or_incomplete(text):
    assert spec.parse(text) is None


def test_normalize_fixes_order_case_and_garbage():
    assert spec.normalize("alt+ctrl+p") == "Ctrl+Alt+P"
    assert spec.normalize("SHIFT+WIN+F24") == "Shift+Win+F24"
    assert spec.normalize("garbage") == ""
    assert spec.display("") == "未设置"
    # 反向：注册位（含 MOD_NOREPEAT）能解回规范写法
    assert spec.from_win32(spec.MOD_CONTROL | spec.MOD_NOREPEAT, 0x50) == "Ctrl+P"


# ---------------------------------------------------------------- 服务
class _FakeUser32:
    """``RegisterHotKey`` 替身：可指定"已被占用"的组合。"""

    def __init__(self, occupied=()):
        self.occupied = {(int(m), int(v)) for m, v in occupied}
        self.registered: dict[int, tuple[int, int]] = {}
        self.unregistered: list[int] = []
        self._next = 1

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):  # noqa: N802
        if (int(modifiers) & ~spec.MOD_NOREPEAT, int(vk)) in self.occupied:
            return 0
        self.registered[int(hotkey_id)] = (int(modifiers), int(vk))
        return 1

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.unregistered.append(int(hotkey_id))
        return 1 if self.registered.pop(int(hotkey_id), None) else 0


def test_apply_registers_bindings_and_reports_failures():
    user32 = _FakeUser32(occupied={(spec.MOD_CONTROL | spec.MOD_ALT, 0x50)})
    service = GlobalHotkeyService(app=None, user32=user32, install_native_filter=False,
                                 supported=True)
    failures = service.apply(
        {"open_chat": "Ctrl+Alt+P", "look_screen": "Ctrl+Alt+L", "screen_capture": ""},
        {"open_chat": lambda: None, "look_screen": lambda: None})

    assert [item[0] for item in failures] == ["open_chat"], "被占用必须如实报出来"
    assert "可能已被其他程序占用" in failures[0][2]
    assert set(service.active_bindings()) == {"look_screen"}, "只有真的注册上的才算生效"
    assert len(user32.registered) == 1


def test_apply_is_a_full_reset_and_clear_unregisters_everything():
    user32 = _FakeUser32()
    service = GlobalHotkeyService(app=None, user32=user32, install_native_filter=False,
                                 supported=True)
    service.apply({"open_chat": "Ctrl+Alt+P"}, {})
    first_ids = set(user32.registered)

    service.apply({"look_screen": "Ctrl+Alt+L"}, {})

    assert first_ids and not (first_ids & set(user32.registered)), "改键后旧键不能还活着"
    assert set(user32.unregistered) >= first_ids

    service.clear()
    assert user32.registered == {}
    assert service.active_bindings() == {}


def test_unsupported_platform_registers_nothing():
    user32 = _FakeUser32()
    service = GlobalHotkeyService(app=None, user32=user32, install_native_filter=False,
                                 supported=False)
    assert service.apply({"open_chat": "Ctrl+Alt+P"}, {}) == []
    assert user32.registered == {}, "非 Windows 不许装模作样注册"
    assert service.install() is False


def _feed_hotkey(service, hotkey_id):
    msg = hotkeys._MSG()
    msg.message = hotkeys.WM_HOTKEY
    msg.wParam = int(hotkey_id)
    return service.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))


def test_wm_hotkey_dispatches_the_bound_action():
    qapp = QApplication.instance() or QApplication([])
    user32 = _FakeUser32()
    service = GlobalHotkeyService(app=qapp, user32=user32, install_native_filter=False,
                                 supported=True)
    fired: list[str] = []
    service.apply({"open_chat": "Ctrl+Alt+P"},
                  {"open_chat": lambda: fired.append("open_chat")})

    hotkey_id = next(iter(user32.registered))
    handled, _result = _feed_hotkey(service, hotkey_id)
    assert handled is True, "认领这条原生消息"
    assert fired == [], "重活必须回事件循环，不在原生消息里直接跑"

    qapp.processEvents()
    assert fired == ["open_chat"]


def test_wm_hotkey_for_unknown_id_is_ignored():
    qapp = QApplication.instance() or QApplication([])
    service = GlobalHotkeyService(app=qapp, user32=_FakeUser32(),
                                 install_native_filter=False, supported=True)
    service.apply({"open_chat": "Ctrl+Alt+P"}, {"open_chat": lambda: None})
    handled, _ = _feed_hotkey(service, 0x6EFE)
    assert handled is False, "别人的热键 id 不许吞"


# ---------------------------------------------------------------- 设置页接线
def test_chord_to_text_requires_a_modifier_and_known_key():
    """录入控件只收「修饰键 + 白名单按键」，其余返回空串（= 不绑）。"""
    from PySide6.QtGui import QKeySequence

    from pet import settings_hotkeys

    assert settings_hotkeys.chord_to_text(QKeySequence("Ctrl+Alt+P")) == "Ctrl+Alt+P"
    assert settings_hotkeys.chord_to_text(QKeySequence("Alt+F9")) == "Alt+F9"
    assert settings_hotkeys.chord_to_text(QKeySequence("P")) == "", "无修饰键会抢走打字"
    assert settings_hotkeys.chord_to_text(QKeySequence()) == ""


def test_hotkey_rows_exist_and_save_round_trips(tmp_path, monkeypatch):
    """「互动 · 快捷键」三行确实在页里，保存能把录入值写进配置。"""
    from PySide6.QtWidgets import QApplication

    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet import hotkey_spec as spec

    qapp = QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    dialog = ModernSettingsDialog(config, include_ai=False)
    try:
        for action in hotkeys.ACTIONS:
            assert dialog.findChild(object, f"hotkeyEdit_{action}") is not None
            assert dialog.findChild(object, f"hotkeyClear_{action}") is not None

        dialog._hotkey_values = {"open_chat": "Ctrl+Alt+P",
                                 "look_screen": "", "screen_capture": ""}
        from pet import settings_hotkeys

        settings_hotkeys.save_hotkey_settings(dialog)
        # 设置页用的是 SlotRoutedConfig（全局键最终落主 config.json）
        assert dialog.config.get("hotkey_open_chat") == "Ctrl+Alt+P"
        assert dialog.config.get("hotkey_look_screen") == ""
        dialog.config.save()
        assert Config(base=tmp_path).get("hotkey_open_chat") == "Ctrl+Alt+P", "要真落盘"

        dialog._hotkey_values = {"open_chat": "nonsense"}
        settings_hotkeys.save_hotkey_settings(dialog)
        assert dialog.config.get("hotkey_open_chat") == "", "脏值不许写进配置"
    finally:
        dialog.deleteLater()
        qapp.processEvents()
