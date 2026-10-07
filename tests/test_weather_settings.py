# -*- coding: utf-8 -*-
"""天气设置（互动域 · 天气标签）：行归属、默认值口径、列表归一化与保存回写。

门禁口径（docs/SETTINGS-CHANGE-GATES.md）：每个持久设置都要有归属域、默认值、
保存语义与恢复路径。天气三键的归属是「互动」域的页内标签「天气」（与「点击与
音效 / 自言自语」同级任务），行由 ``pet/settings_weather.py`` 构建，侧栏 10 个
域不变（那是外部契约）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import weather as W  # noqa: E402

app = QApplication.instance() or QApplication([])

WEATHER_KEYS = ("weather_enabled", "weather_city", "weather_city_list")


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dlg = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    yield dlg
    dlg.close()
    app.processEvents()


def _row(dialog, key: str):
    from pet.modern_settings_dialog import SettingRow

    row = dialog.findChild(SettingRow, f"settingRow_{key}")
    assert row is not None, f"缺少设置行 {key}"
    return row


def _weather_tab(dialog):
    from pet.settings_widgets import SettingsTabContainer

    index = next(i for i in range(dialog.sidebar.count())
                 if dialog.sidebar.item(i).text() == "互动")
    page = dialog.pages.widget(index)
    tabs = page.findChild(SettingsTabContainer, "settingsTaskTabs")
    assert tabs is not None, "互动域没有页内标签容器"
    return tabs


# ---------------------------------------------------------------- 归属与默认值
def test_weather_rows_live_in_their_own_interaction_tab(dialog):
    tabs = _weather_tab(dialog)
    assert "weather" in tabs.keys()
    assert tabs.labels()[tabs.keys().index("weather")] == "天气"
    for key in WEATHER_KEYS:
        assert tabs.key_for_descendant(_row(dialog, key)) == "weather"


def test_default_values_are_the_documented_ones(dialog):
    """默认口径：功能开（点一下才联网，不打扰）、城市为空（不替用户猜城市）。"""
    assert dialog.config.get("weather_enabled") is True
    assert dialog.config.get("weather_city") == ""
    assert dialog.config.get("weather_city_list") == []
    assert dialog.weather_enabled_check.isChecked() is True
    assert dialog.weather_city_edit.text() == ""
    assert dialog.weather_city_list_edit.toPlainText().strip() == ""


def test_controls_round_trip_from_config(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("weather_city", "鹿城")
    config.set("weather_city_list", ["北京", "鹿城"])
    dlg = settings_mod.ModernSettingsDialog(config, include_ai=True)
    try:
        assert dlg.weather_city_edit.text() == "鹿城"
        assert dlg.weather_city_list_edit.toPlainText().splitlines() == ["北京", "鹿城"]
    finally:
        dlg.close()
        app.processEvents()


# ---------------------------------------------------------------- 保存
def test_save_writes_the_three_keys_and_normalizes_the_list(dialog):
    dialog.weather_enabled_check.setChecked(False)
    dialog.weather_city_edit.setText("鹿城区")
    dialog.weather_city_list_edit.setPlainText("北京\n 鹿城 \n北京\n\n上海")

    assert dialog._write_config() is True
    assert dialog.config.get("weather_enabled") is False
    # 手填带后缀 → 归一化；列表去空行、去重、保序
    assert dialog.config.get("weather_city_list") == ["北京", "鹿城", "上海"]


def test_save_caps_the_city_list_and_keeps_the_current_city_listed(dialog):
    names = [f"城市{i}" for i in range(W.MAX_CITIES + 4)]
    dialog.weather_city_list_edit.setPlainText("\n".join(names))
    dialog.weather_city_edit.setText("城市3")
    assert dialog._write_config() is True
    listed = dialog.config.get("weather_city_list")
    assert len(listed) == W.MAX_CITIES
    assert listed[:2] == ["城市0", "城市1"], "超上限时按书写顺序截断"
    assert "城市3" in listed, "当前城市必须落在列表里，否则菜单里勾不到它"

    # 列表满员且当前城市不在其中：保持用户所写，只保留"当前城市"这个指针
    # （挤掉用户写的某个城市比"指针不在列表里"更糟：那是静默丢数据）
    dialog.weather_city_edit.setText("北京")
    assert dialog._write_config() is True
    assert dialog.config.get("weather_city") == "北京"
    assert dialog.config.get("weather_city_list") == listed


def test_save_with_an_empty_current_city_clears_it(dialog):
    dialog.weather_city_edit.setText("   ")
    assert dialog._write_config() is True
    assert dialog.config.get("weather_city") == ""


def test_saving_an_empty_list_does_not_resurrect_the_current_city(dialog):
    """列表清空 + 当前城市清空 = 回到"还没选城市"的状态（菜单显示空提示）。"""
    dialog.weather_city_edit.setText("")
    dialog.weather_city_list_edit.setPlainText("")
    assert dialog._write_config() is True
    assert dialog.config.get("weather_city_list") == []
    assert dialog.config.get("weather_city") == ""


def test_search_finds_the_weather_rows_and_switches_to_the_tab(dialog):
    tabs = _weather_tab(dialog)
    tabs.setCurrentKey("click")
    dialog.search_edit.setText("天气")
    for _ in range(3):
        app.processEvents()
    assert dialog.sidebar.currentItem().text() == "互动"
    assert tabs.currentKey() == "weather"
    assert _row(dialog, "weather_enabled").isVisibleTo(tabs) is True


# ---------------------------------------------------------------- 子宠页作用域
def _main_and_sub_dialogs(tmp_path, monkeypatch):
    """主宠页 + 子宠页（``instance_id=slot-1``）两个设置对话框。"""
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    master = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    child = settings_mod.ModernSettingsDialog(
        Config(base=tmp_path, instance_id="slot-1"), include_ai=True)
    return master, child


def test_weather_controls_are_main_pet_only(tmp_path, monkeypatch):
    """子宠页：天气三键是进程级（不在 PER_SLOT_SETTING_KEYS，运行时读主配置）→ 置灰。

    子宠页保存写 ``config-slot-N.json``，而这些键的消费方一律读主配置，改了等于
    没改；故如实置灰 + tooltip，主宠页不受影响。
    """
    master, child = _main_and_sub_dialogs(tmp_path, monkeypatch)
    try:
        for control in (master.weather_enabled_check, master.weather_city_edit,
                        master.weather_city_list_edit):
            assert control.isEnabled() is True
        for control in (child.weather_enabled_check, child.weather_city_edit,
                        child.weather_city_list_edit):
            assert control.isEnabled() is False
            assert control.toolTip() == "仅主桌宠可设置"
    finally:
        for dlg in (master, child):
            dlg.close()
            dlg.deleteLater()
        app.processEvents()
