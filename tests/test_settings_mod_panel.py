# -*- coding: utf-8 -*-
"""D2 片 2：owner 设置面板容器（``pet/settings_mod_panel.py``）。

拆出来的理由与 ``settings_proactive_worker`` 同款：``modern_settings_dialog.py`` 的
行数预算没有余量，面板容器与对话框框体无关。容器只做三件事——把作者的小部件挂进
一个 Core 拥有的壳、把草稿四件套（``dirty`` / ``draft`` / ``confirm_save`` /
``discard_changes``）原样转发、把「保存」按钮与冲突/失败文案落在自己的状态行上。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QWidget

from pet.feature_state_io import StateError
from pet.plugins.lifecycle import FeatureHostLifecycle
from pet.settings_mod_panel import OwnerSettingsPanel, prepare_revocation, resolve_revocation

app = QApplication.instance() or QApplication([])
OWNER = "demo.hello-local"


class _Editor(QWidget):
    """作者侧设置组件的规约形状（``mod_api.v1.SettingsComponent`` 的最小实现）。"""

    def __init__(self, *, fail_save=False, conflict=False, parent=None):
        super().__init__(parent)
        self.message = QLineEdit(self)
        self.saved = "你好"
        self.message.setText(self.saved)
        self.fail_save = fail_save
        self.conflict = conflict
        self.calls = []
        self.disposed = 0

    def dirty(self):
        return self.message.text() != self.saved

    def draft(self):
        return {"message": self.message.text()}

    def confirm_save(self):
        self.calls.append("save")
        if self.conflict:
            raise StateError("configuration_changed")
        if self.fail_save:
            return False
        self.saved = self.message.text()
        return True

    def discard_changes(self):
        self.calls.append("discard")
        self.message.setText(self.saved)
        return True

    def dispose(self):
        self.disposed += 1
        self.deleteLater()


def _panel(editor=None, *, lifecycle=None, title="离线打招呼"):
    editor = editor if editor is not None else _Editor()
    return editor, OwnerSettingsPanel(OWNER, editor, title=title, lifecycle=lifecycle)


# ----------------------------------------------------------------- 转发

def test_the_container_embeds_the_author_widget_and_owns_a_save_button():
    editor, panel = _panel()
    assert panel.owner == OWNER
    assert panel.dirty() is False
    assert panel.save_button.text()
    assert editor.isAncestorOf(panel.save_button) or panel.isAncestorOf(editor)


def test_dirty_and_draft_are_forwarded_verbatim():
    editor, panel = _panel()
    editor.message.setText("改过的内容")
    assert panel.dirty() is True
    assert panel.draft() == {"message": "改过的内容"}


def test_confirm_save_and_discard_are_forwarded_verbatim():
    editor, panel = _panel()
    editor.message.setText("改过的内容")
    assert panel.confirm_save() is True
    assert panel.dirty() is False
    editor.message.setText("再来一次")
    assert panel.discard_changes() is True
    assert editor.calls == ["save", "discard"]


def test_a_save_conflict_is_reported_with_a_step_the_user_can_follow():
    editor, panel = _panel(_Editor(conflict=True))
    editor.message.setText("改过的内容")
    assert panel.confirm_save() is False
    text = panel.status.text()
    assert text and "放弃" in text  # 说清下一步怎么做，不只是"失败了"
    assert panel.dirty() is True  # 草稿没被丢掉


def test_a_plain_false_save_is_reported_and_keeps_the_draft():
    editor, panel = _panel(_Editor(fail_save=True))
    editor.message.setText("改过的内容")
    assert panel.confirm_save() is False
    assert panel.status.text()
    assert panel.dirty() is True


def test_dispose_is_idempotent_and_forwards_to_the_author_component():
    editor, panel = _panel()
    panel.dispose()
    panel.dispose()
    assert editor.disposed == 1


# ------------------------------------------------- 没有草稿协议时的如实降级

class _Plain(QWidget):
    """只给界面、不给草稿协议的作者组件：如实当「没有可保存的设置」。"""

    def __init__(self, parent=None):
        super().__init__(parent)


def test_a_component_without_the_draft_protocol_reports_honestly():
    plain = _Plain()
    panel = OwnerSettingsPanel(OWNER, plain, title="离线打招呼")
    assert panel.dirty() is False
    assert panel.draft() == {}
    assert panel.confirm_save() is False
    assert "可保存的设置" in panel.status.text()
    assert panel.discard_changes() is False


def test_a_component_wrapper_object_contributes_its_own_widget():
    """作者可以返回一个"组件"（持协议）+ ``.widget``（要挂的界面）。"""

    class Wrapper:
        def __init__(self):
            self.widget = QWidget()
            self.disposed = 0

        def dirty(self):
            return True

        def draft(self):
            return {"x": 1}

        def dispose(self):
            self.disposed += 1

    wrapper = Wrapper()
    panel = OwnerSettingsPanel(OWNER, wrapper, title="离线打招呼")
    assert panel.dirty() is True
    assert panel.embedded is wrapper.widget
    assert isinstance(panel.embedded, QWidget)
    panel.dispose()
    assert wrapper.disposed == 1


# ------------------------------------------------------------ 草稿快照

def test_push_drafts_feeds_the_transaction_side_snapshot():
    gate = FeatureHostLifecycle()
    editor, panel = _panel(lifecycle=gate, title="离线打招呼")
    panel.push_drafts()
    assert gate.drafts(OWNER) == ()  # 干净的面板不产生草稿
    editor.message.setText("改过的内容")
    panel.push_drafts()
    assert gate.drafts(OWNER) == ("离线打招呼",)
    panel.discard_changes()
    panel.push_drafts()
    assert gate.drafts(OWNER) == ()


def test_dispose_clears_the_draft_snapshot():
    gate = FeatureHostLifecycle()
    editor, panel = _panel(lifecycle=gate)
    editor.message.setText("改过的内容")
    panel.push_drafts()
    assert gate.drafts(OWNER)
    panel.dispose()
    assert gate.drafts(OWNER) == ()  # 面板没了就不能再卡住事务层


# ------------------------------------------- 撤回前的三键询问（与事务层同源）

def test_resolve_revocation_cancels_without_touching_the_draft():
    editor, panel = _panel()
    editor.message.setText("改过的内容")
    assert resolve_revocation(panel, "cancel") is False
    assert editor.calls == []
    assert panel.dirty() is True


def test_resolve_revocation_saves_or_discards():
    editor, panel = _panel()
    editor.message.setText("改过的内容")
    assert resolve_revocation(panel, "save") is True
    assert editor.calls == ["save"]
    editor.message.setText("又一次")
    assert resolve_revocation(panel, "discard") is True
    assert editor.calls == ["save", "discard"]


def test_resolve_revocation_stops_when_the_chosen_action_fails():
    """保存失败（配置已在别处变化）不能当成"已解决"继续动这个包。"""
    editor, panel = _panel(_Editor(conflict=True))
    editor.message.setText("改过的内容")
    assert resolve_revocation(panel, "save") is False
    assert panel.dirty() is True


def test_prepare_revocation_is_a_no_op_for_a_clean_panel(monkeypatch):
    editor, panel = _panel()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("干净的面板不许弹窗"))
    assert prepare_revocation(panel) is True


def test_prepare_revocation_asks_three_ways_and_honours_cancel(monkeypatch):
    editor, panel = _panel()
    editor.message.setText("改过的内容")
    seen = {}

    def fake_question(_parent, title, text, buttons, default):
        seen["title"] = title
        seen["text"] = text
        seen["buttons"] = buttons
        seen["default"] = default
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    assert prepare_revocation(panel) is False
    assert editor.calls == []
    for button in (QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Discard,
                   QMessageBox.StandardButton.Cancel):
        assert seen["buttons"] & button
    assert seen["default"] == QMessageBox.StandardButton.Cancel
    assert seen["text"] and seen["title"]
    assert "MOD" not in f"{seen['title']}{seen['text']}"  # 设置页文案 lint 口径（黑话）
