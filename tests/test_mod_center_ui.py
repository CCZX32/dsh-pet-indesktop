# -*- coding: utf-8 -*-
"""MOD 中心界面的行为验收。

蓝本 = DLC 分支的 ``tests/test_mod_center_ui.py``。
那版直接用桩后端（一个只兑现 ``entries``/``perform``/``import_source`` + 四个信号的
普通 ``QObject``）——本模块沿用这个桩：控件对后端的契约就是这条鸭子类型协议，
桩能兑现它就说明控件没有偷偷依赖控制器的私货。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLineEdit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet.mod_management import ModEntry, ModOutcome

app = QApplication.instance() or QApplication([])


class Backend(QObject):
    changed = Signal()
    busy_changed = Signal(bool)
    result = Signal(str, object)
    batch_finished = Signal(object)
    busy = False

    def __init__(self):
        super().__init__()
        self.calls = []
        self.rows = [ModEntry("third.chat", "功能扩展", "离线例子", "1.0.0", "<b>纯文本</b>", False, Path("feature")),
                     ModEntry("character.demo", "角色资源", "角色例子", "1.0.0", "说明", False, Path("character")),
                     ModEntry("resource:bundled:shenshen", "角色资源", "深深", "1.0.0", "", True, Path("builtin"), source="bundled")]

    def entries(self):
        return self.rows

    def perform(self, action, keys):
        self.calls.append((action, keys))

    def import_source(self, path, expected=None):
        self.calls.append(("import", path, expected))


def test_list_filters_clear_selection_and_builtin_cannot_be_deleted():
    from pet.mod_center_ui import ModCenterWidget
    backend = Backend()
    widget = ModCenterWidget(backend)
    widget.show()
    widget.select_all.setChecked(True)
    assert len(widget.selection.selected) == 3
    widget.filters["角色资源"].click()
    assert not widget.selection.selected
    assert len(widget.rows) == 2
    builtin = widget.rows["角色资源:resource:bundled:shenshen"]
    assert not builtin.delete_action.isEnabled()
    widget.search.setText("离线")
    assert not widget.rows
    widget.close()


def test_filter_buttons_follow_the_kinds_the_backend_serves():
    """后端只服务一种 MOD 时不留一个永远空的分类按钮。"""
    from pet.mod_center_ui import ModCenterWidget
    widget = ModCenterWidget(Backend(), kinds=("角色资源",))
    assert set(widget.filters) == {"全部", "角色资源"}
    widget.close()


def test_enable_is_immediate_and_refresh_keeps_unrelated_draft():
    from pet.mod_center_ui import ModCenterWidget
    backend = Backend()
    widget = ModCenterWidget(backend)
    unrelated = QLineEdit("未保存草稿")
    row = widget.rows["功能扩展:third.chat"]
    row.toggle.click()
    assert backend.calls == [("enable", ["功能扩展:third.chat"])]
    backend.result.emit("功能扩展:third.chat", ModOutcome(True, "已启用"))
    backend.changed.emit()
    assert unrelated.text() == "未保存草稿"
    assert widget.rows["功能扩展:third.chat"].message.text() == "已启用"
    widget.close()


def test_resource_row_uses_use_action_and_feature_row_opens_settings():
    from pet.mod_center_ui import ModCenterWidget
    backend = Backend()
    widget = ModCenterWidget(backend)
    resource = widget.rows["角色资源:character.demo"]
    assert resource.settings.text() == "使用"
    resource.settings.click()
    assert ("use", ["角色资源:character.demo"]) in backend.calls
    requested = []
    widget.settings_requested.connect(requested.append)
    feature = widget.rows["功能扩展:third.chat"]
    assert feature.settings.text() == "设置"
    feature.settings.click()
    assert requested == ["third.chat"]
    widget.close()


@pytest.mark.parametrize("width", [440, 820])
def test_long_plain_description_never_forces_horizontal_scroll(width):
    from pet.mod_center_ui import ModCenterWidget
    widget = ModCenterWidget(Backend())
    widget.resize(width, 850)
    widget.show()
    app.processEvents()
    assert widget.minimumSizeHint().width() <= 440
    row = widget.rows["功能扩展:third.chat"]
    assert row.description.text() == "<b>纯文本</b>"
    assert row.description.textFormat().name == "PlainText"
    widget.close()


def test_unchanged_catalog_refresh_preserves_row_widgets_and_selection():
    from pet.mod_center_ui import ModCenterWidget
    backend = Backend()
    widget = ModCenterWidget(backend)
    row = widget.rows["功能扩展:third.chat"]
    row.check.setChecked(True)
    backend.changed.emit()
    assert widget.rows["功能扩展:third.chat"] is row
    assert row.check.isChecked()
    widget.close()


def test_single_operation_result_survives_busy_refresh():
    from pet.mod_center_ui import ModCenterWidget
    backend = Backend()
    widget = ModCenterWidget(backend)
    backend.busy = True
    backend.busy_changed.emit(True)
    result = ModOutcome(False, "请退出后重试")
    backend.result.emit("功能扩展:third.chat", result)
    backend.changed.emit()
    backend.busy = False
    backend.busy_changed.emit(False)
    backend.changed.emit()
    backend.batch_finished.emit((("功能扩展:third.chat", result),))
    assert widget.summary.text() == result.message
    widget.close()


def test_backend_without_switch_capability_greys_out_the_use_button():
    """后端说换不了装（没有桌宠窗口）时按钮置灰并说明原因，而不是点了才失败。"""
    from pet.mod_center_ui import ModCenterWidget

    class NoWindowBackend(Backend):
        can_use = False
        use_hint = "请从桌宠右键菜单换装。"

    widget = ModCenterWidget(NoWindowBackend())
    row = widget.rows["角色资源:character.demo"]
    assert not row.settings.isEnabled()
    assert row.settings.toolTip() == "请从桌宠右键菜单换装。"
    widget.close()


def test_long_identifier_gets_display_only_break_opportunities():
    """超长标识符不会撑出横向滚动条：断行点只影响呈现，提示与读屏里仍是原文。"""
    from pet.mod_center_ui import ModRow, ModCenterWidget

    token = "resource:verylongidentifiertoken0123456789abcdef"

    class LongBackend(Backend):
        def __init__(self):
            super().__init__()
            self.rows = [ModEntry("demo", "角色资源", "长说明", "1.0.0", token, False, Path("x"))]

    widget = ModCenterWidget(LongBackend())
    row = widget.findChild(ModRow)
    assert "\u200b" in row.description.text()
    assert row.description.text().replace("\u200b", "") == token
    assert row.description.toolTip() == token
    assert row.description.accessibleDescription() == token
    widget.close()
