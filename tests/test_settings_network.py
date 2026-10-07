# -*- coding: utf-8 -*-
"""设置页「网络信息」三键的行/依赖/保存契约（issue #172）。

断言走真实 ``ModernSettingsDialog``（设置窗口这个公开 seam），不碰私有调用顺序：
默认值呈现、依赖显隐（岛关 → 信息槽关 → 网络槽）、保存回写、脏值不炸设置页。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.modern_settings_dialog as settings_mod
from pet import net_monitor
from pet.config import Config

app = QApplication.instance() or QApplication([])


def _dialog(tmp_path, monkeypatch, **network):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    cfg = Config(base=tmp_path)
    for key, value in network.items():
        cfg.set(key, value)
    dialog = settings_mod.ModernSettingsDialog(cfg, include_ai=True)
    return dialog, cfg


def _row(dialog, key):
    row = dialog.findChild(settings_mod.SettingRow, f"settingRow_{key}")
    assert row is not None, f"缺少设置行 {key}"
    return row


def test_network_rows_exist_with_documented_copy(tmp_path, monkeypatch):
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        toggle = _row(dialog, "island_network")
        interval = _row(dialog, "network_probe_interval")
        menu = _row(dialog, "network_info_menu")
        text = toggle.hint_label.text() + interval.hint_label.text()
        assert "0.16 KB" in text, "必须写明单次探测的流量成本"
        assert "MB/天" in text, "必须写明按间隔折算的日流量"
        assert "223.5.5.5" in text, "必须写明探测目标（境内，不默认打国外）"
        assert "223.5.5.5" in interval.hint_label.text()
        assert "1 KB" in menu.hint_label.text() and "不轮询" in menu.hint_label.text()
    finally:
        dialog.close()


def test_network_rows_defaults_match_config(tmp_path, monkeypatch):
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        assert dialog.island_network_check.isChecked() is False
        assert dialog.network_info_menu_check.isChecked() is True
        assert dialog.network_probe_interval_spin.value() == 1.0
        assert dialog.network_probe_interval_spin.minimum() == 0.5
        assert dialog.network_probe_interval_spin.maximum() == 60.0
    finally:
        dialog.close()


def test_dependency_visibility_chains_island_info_network(tmp_path, monkeypatch):
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        island_on = dialog.island_enabled_check
        info_on = dialog.island_info_check
        net = dialog.island_network_check
        island_on.setChecked(True)
        info_on.setChecked(True)
        assert not _row(dialog, "island_network").isHidden()
        assert _row(dialog, "network_probe_interval").isHidden(), "网络槽关着：间隔行隐藏"

        net.setChecked(True)
        assert not _row(dialog, "network_probe_interval").isHidden()
        # 网络槽接管信息槽内容：内容选择行隐掉（不留"改了没反应"的控件）
        assert _row(dialog, "dynamic_island_info_mode").isHidden()
        assert _row(dialog, "dynamic_island_custom_text").isHidden()

        net.setChecked(False)
        assert _row(dialog, "dynamic_island_info_mode").isHidden() is False
        assert _row(dialog, "network_probe_interval").isHidden()

        info_on.setChecked(False)
        assert _row(dialog, "island_network").isHidden()
        info_on.setChecked(True)
        assert not _row(dialog, "island_network").isHidden()

        island_on.setChecked(False)
        assert _row(dialog, "island_network").isHidden()
    finally:
        dialog.close()


def test_interval_hint_tracks_the_chosen_value(tmp_path, monkeypatch):
    """日流量数字跟着真实间隔走：1 秒的数字必须大于 30 秒的数字。"""
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        row = _row(dialog, "network_probe_interval")

        def per_day():
            text = row.hint_label.text()
            return float(text.split("约 ")[1].split(" MB/天")[0])

        dialog.network_probe_interval_spin.setValue(1.0)
        fast = per_day()
        dialog.network_probe_interval_spin.setValue(30.0)
        slow = per_day()
        assert fast > slow > 0
    finally:
        dialog.close()


def test_interval_spin_is_not_clipped_at_larger_fonts(tmp_path, monkeypatch):
    """最长值 "60.0 秒" 在默认字体下就占满基类的 92px 固定宽度（零余量），
    放大字体必裁——本项解除固定宽度并按字体度量给足最小宽度。"""
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        spin = dialog.network_probe_interval_spin
        spin.setValue(spin.maximum())
        spin.show()
        app.processEvents()
        line = spin.lineEdit()
        assert line.width() >= line.fontMetrics().horizontalAdvance(line.text()), "默认字体下就裁了"
        assert spin.maximumWidth() > 1000, "宽度不得被基类的 92px 固定值钉死"

        for scale in (1.5, 2.0):
            font = spin.font()
            font.setPointSizeF(max(1.0, font.pointSizeF()) * scale)
            spin.setFont(font)
            line.setFont(font)
            app.processEvents()
            needed = line.fontMetrics().horizontalAdvance(line.text())
            assert spin.sizeHint().width() >= needed + 24, (scale, spin.sizeHint().width(), needed)
    finally:
        dialog.close()


def test_save_writes_three_keys_and_reloads(tmp_path, monkeypatch):
    dialog, cfg = _dialog(tmp_path, monkeypatch)
    try:
        dialog.island_network_check.setChecked(True)
        dialog.network_probe_interval_spin.setValue(3.5)
        dialog.network_info_menu_check.setChecked(False)
        dialog._write_config()
    finally:
        dialog.close()

    assert cfg.get("island_network_enabled") is True
    assert cfg.get("network_probe_interval_seconds") == 3.5
    assert cfg.get("network_info_menu_enabled") is False
    restored = Config(base=tmp_path)
    assert restored.get("island_network_enabled") is True
    assert restored.get("network_probe_interval_seconds") == 3.5
    assert restored.get("network_info_menu_enabled") is False


def test_dirty_interval_does_not_break_settings_page(tmp_path, monkeypatch):
    """手改 config.json 塞进越界间隔：设置页仍能构建，控件落在合法区间内。"""
    dialog, _cfg = _dialog(
        tmp_path, monkeypatch,
        network_probe_interval_seconds=net_monitor.MAX_INTERVAL_SECONDS * 100,
    )
    try:
        assert dialog.network_probe_interval_spin.value() == net_monitor.MAX_INTERVAL_SECONDS
    finally:
        dialog.close()


def test_network_rows_are_searchable(tmp_path, monkeypatch):
    """行进了设置搜索索引（objectName 约定），否则用户搜不到。"""
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        names = {row.objectName() for row in dialog._search_rows}
        assert "settingRow_island_network" in names
        assert "settingRow_network_probe_interval" in names
        assert "settingRow_network_info_menu" in names
    finally:
        dialog.close()


# ---------------------------------------------------------------- 子宠页作用域
def test_network_controls_are_main_pet_only(tmp_path, monkeypatch):
    """子宠页：网络三键是进程级（不在 PER_SLOT_SETTING_KEYS，运行时读主配置）→ 置灰。

    子宠页保存写 ``config-slot-N.json``，而采样器/岛/右键菜单一律读主配置，改了
    等于没改；故如实置灰 + tooltip，主宠页不受影响。
    """
    master, _cfg = _dialog(tmp_path, monkeypatch)
    child = settings_mod.ModernSettingsDialog(
        Config(base=tmp_path, instance_id="slot-1"), include_ai=True)
    try:
        for control in (master.island_network_check, master.network_probe_interval_spin,
                        master.network_info_menu_check):
            assert control.isEnabled() is True
        for control in (child.island_network_check,
                        child.network_probe_interval_spin,
                        child.network_info_menu_check):
            assert control.isEnabled() is False
            assert control.toolTip() == "仅主桌宠可设置"
    finally:
        for dlg in (master, child):
            dlg.close()
            dlg.deleteLater()
        app.processEvents()
