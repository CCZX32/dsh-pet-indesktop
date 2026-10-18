# -*- coding: utf-8 -*-
"""设置页「互动 · 快捷键」：三个动作的**系统级**热键录入。

三个动作与右键菜单同名同实现（不复制行为，只换触发方式）：

- AI 对话 → ``PetInstance.open_chat``
- 看看屏幕 → ``OverlayShell.look_at_screen``
- 截图提问 → ``OverlayShell.on_screen_capture``

三条纪律：

1. **默认全空**：不绑任何键，行为与加这个功能之前逐位相同（``docs/SETTINGS-CHANGE-GATES.md``
   的"有安全默认"）。
2. **必须有修饰键**：单个字母/数字的全局热键会抢走系统级打字输入，录入时就拒掉
   （判据在 ``pet/hotkey_spec.py``，不是在这里自定义）。
3. **被占用要说**：Windows 的全局热键表是独占的，注册失败（通常是被别的程序占了）
   会写日志并让主进程侧的那一项不生效；这里不假装成功。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QKeySequenceEdit, QPushButton, QWidget

from . import hotkey_spec
from .hotkeys import ACTIONS, ACTION_LABELS
from .settings_widgets import SettingRow

#: 动作 → 给用户的一句说明（行 hint）
_ACTION_HINTS = {
    "open_chat": "在任意程序前台时按这个组合键，直接打开 AI 对话窗口。",
    "look_screen": "按一下就让它看一眼当前屏幕并说说看到了什么。",
    "screen_capture": "按一下进入截图提问（框选区域后发给模型）。",
}

#: Qt 修饰位 → Win32 修饰位
_QT_MODS = (
    (Qt.KeyboardModifier.ControlModifier, hotkey_spec.MOD_CONTROL),
    (Qt.KeyboardModifier.AltModifier, hotkey_spec.MOD_ALT),
    (Qt.KeyboardModifier.ShiftModifier, hotkey_spec.MOD_SHIFT),
    (Qt.KeyboardModifier.MetaModifier, hotkey_spec.MOD_WIN),
)

#: Qt 键 → 虚拟键码（只收白名单里的，其余一律"不支持"）
_QT_KEYS = {
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Print: 0x2C,
    Qt.Key.Key_Pause: 0x13,
}


def chord_to_text(sequence) -> str:
    """``QKeySequence`` → 规范字符串；不支持/无修饰键 → ``""``（= 未设置）。

    只取第一个和弦（录入控件已限制 ``setMaximumSequenceLength(1)``）：Windows 的
    ``RegisterHotKey`` 没有"序列"概念，多和弦的尾部会被静默丢掉——不如一开始就不收。
    """
    if sequence is None or sequence.isEmpty():
        return ""
    combination = sequence[0]
    mods = 0
    for qt_mod, win_mod in _QT_MODS:
        if combination.keyboardModifiers() & qt_mod:
            mods |= win_mod
    if not mods:
        return ""
    key = int(combination.key())
    vk = _QT_KEYS.get(key)
    if vk is None:
        if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
            vk = key  # Qt 的 A..Z 就等于 ASCII 大写
        elif int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
            vk = key
        elif int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F24):
            vk = 0x70 + (key - int(Qt.Key.Key_F1))
    if vk is None:
        return ""
    return hotkey_spec.canonical(mods, vk) or ""


def create_hotkey_controls(dialog) -> None:
    """幂等建立三个录入控件（初值取配置；空 = 未设置）。"""
    if getattr(dialog, "_hotkey_edits", None):
        return
    dialog._hotkey_edits = {}
    dialog._hotkey_values = {}
    for action in ACTIONS:
        edit = QKeySequenceEdit(dialog)
        edit.setObjectName(f"hotkeyEdit_{action}")
        edit.setMaximumSequenceLength(1)
        edit.setClearButtonEnabled(True)
        stored = hotkey_spec.normalize(dialog.config.get(ACTIONS[action]))
        dialog._hotkey_values[action] = stored
        if stored:
            edit.setKeySequence(QKeySequence(stored))
        dialog._hotkey_edits[action] = edit


def _row_control(dialog, action: str) -> QWidget:
    """一行里的控件：录入框 + 「清除」。"""
    holder = QWidget(dialog)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    edit = dialog._hotkey_edits[action]
    layout.addWidget(edit)

    clear = QPushButton("清除", holder)
    clear.setObjectName(f"hotkeyClear_{action}")
    clear.setToolTip("取消这个动作的快捷键（不绑也能从右键菜单触发）")
    layout.addWidget(clear)

    def _remember(_sequence=None) -> None:
        text = chord_to_text(edit.keySequence())
        if not text and not edit.keySequence().isEmpty():
            # 收到一个不支持的组合（例如只按了 P、或 F13 之外的怪键）：清空并提示，
            # 绝不留一个"看着绑上了、其实永远不触发"的值。
            edit.setKeySequence(QKeySequence())
            edit.setToolTip("需要至少一个修饰键（Ctrl/Alt/Shift/Win）+ 一个常见按键")
        else:
            edit.setToolTip("")
        dialog._hotkey_values[action] = text

    def _clear() -> None:
        edit.setKeySequence(QKeySequence())
        dialog._hotkey_values[action] = ""

    edit.keySequenceChanged.connect(_remember)
    clear.clicked.connect(_clear)
    return holder


def build_hotkey_rows(dialog) -> list[SettingRow]:
    """「互动 · 快捷键」一节的行装配（三项）。"""
    create_hotkey_controls(dialog)
    rows = []
    for action in ACTIONS:
        row = SettingRow(ACTIONS[action], ACTION_LABELS[action], _ACTION_HINTS[action],
                         _row_control(dialog, action))
        # 热键是进程级（全局键），与"影响所有桌宠"的其他全局项同一口径标注
        row.set_scope_note("影响所有桌宠")
        rows.append(row)
    return rows


def save_hotkey_settings(dialog) -> None:
    """写回三个配置键（空串 = 不绑）。真正注册由主进程侧的热键服务负责。"""
    values = getattr(dialog, "_hotkey_values", None) or {}
    for action, key in ACTIONS.items():
        text = hotkey_spec.normalize(values.get(action, ""))
        if text != hotkey_spec.normalize(dialog.config.get(key)):
            dialog.config.set(key, text)
