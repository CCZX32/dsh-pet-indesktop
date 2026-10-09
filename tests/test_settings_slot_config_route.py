# -*- coding: utf-8 -*-
"""子宠设置页的配置读写路由（架构级死开关修复）。

问题：overlay 拓扑下右键子宠 → 桌宠设置拉起的是**独立设置进程**
（``--instance slot-N`` → ``Config(instance_id="slot-N")`` → 读写
``config-slot-N.json``），而运行期只有 ``PER_SLOT_SETTING_KEYS`` 里的键逐宠取源
（``overlay_shell._SpriteConfig.get``），其余键一律读主配置。于是子宠页上「语音
报时 / 节日 / 待办 / 灵动岛 / 菜单外观 / 窗口级 7 键 …」保存成功、回显正确、
运行期零效果——窗口级 7 行还写着「（对所有桌宠生效）」，实际对所有桌宠都不生效。

本文件钉住修法的四件事（走真实 ``ModernSettingsDialog`` 这个公开 seam，不碰私有
调用顺序）：

1. 保存路由：非 per-slot 键落进**主** ``config.json``，per-slot 键落 slot 文件；
2. 初值路由：子宠页非 per-slot 行显示主配置的真实值（不再是 slot 文件里的无效快照）；
3. 恢复默认：子宠页只重置 slot 文件，主配置一个键都不碰；
4. 并发纪律：主配置在设置窗打开后被外部改写 → 保存不盖回该键（reload-merge）。

分流只在 overlay 拓扑下的 slot 身份生效：legacy 单窗（含捕获模式）里那只桌宠读的
就是自己那份 ``config-slot-N.json`` 的**全部**键，分流反而会让它的设置失效。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pet import overlay_spawn_state as spawn_state
from pet import settings_slot_config
from pet.catalog import DEFAULT_SCALE
from pet.config import Config


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _dialog(config, *, include_ai: bool = False, standalone: bool = False):
    from pet.modern_settings_dialog import ModernSettingsDialog

    return ModernSettingsDialog(config, include_ai=include_ai,
                                standalone=standalone)


def _read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _slot_path(config_dir, slot: int = 1) -> Path:
    return spawn_state.slot_config_path(config_dir, slot)


# ------------------------------------------------------------ 1. 保存路由
def test_child_save_routes_global_keys_to_main_config(tmp_path, app):
    """子宠页保存：非 per-slot 键落**主** config.json（slot 文件里不许出现新值）。

    这些键运行期只有主配置一个读源（``_SpriteConfig`` 对它们转发主配置），写进
    slot 文件就是"保存成功、回显正确、运行时不生效"的死开关。

    对话框按**独立设置进程**的真实形态构造（``parent=None`` + ``standalone=True``，
    即 ``pet/__main__._run_settings`` 那次构造），路由就在这条路径上。
    """
    main = Config(base=tmp_path)
    main.set("scale", 0.5)
    main.set("pet_opacity", 55)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")

    dialog = _dialog(cfg, standalone=True)
    try:
        assert dialog.pet_opacity_spin.value() == 55
        dialog.pet_opacity_spin.setValue(35)
        dialog.edge_probe_check.setChecked(True)
        dialog.voice_chime_page.enabled_check.setChecked(True)
        assert dialog._write_config() is True
    finally:
        dialog.deleteLater()

    on_disk = _read_json(main.path)
    assert on_disk["pet_opacity"] == 35, "窗口级键必须落主配置"
    assert on_disk["edge_probe_enabled"] is True, "拖拽探头必须落主配置"
    assert on_disk["voice_chime_enabled"] is True, "语音报时必须落主配置"
    assert on_disk["scale"] == 0.5, "per-slot 键不得改动主配置"

    slot_on_disk = _read_json(_slot_path(main.dir))
    assert slot_on_disk["pet_opacity"] != 35, "非 per-slot 键一个字节都不该进 slot 文件"
    assert slot_on_disk.get("edge_probe_enabled") is not True
    assert slot_on_disk.get("voice_chime_enabled") is not True


def test_child_save_keeps_per_slot_keys_in_the_slot_file(tmp_path, app):
    """子宠页保存：per-slot 键落这只宠自己的 slot 文件，主配置不变。"""
    main = Config(base=tmp_path)
    main.set("scale", 0.5)
    main.set("self_talk_enabled", False)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")

    dialog = _dialog(cfg)
    try:
        dialog.scale_combo.setCurrentIndex(dialog.scale_combo.findData(1.0))
        dialog.self_talk_check.setChecked(True)
        assert dialog._write_config() is True
    finally:
        dialog.deleteLater()

    slot_on_disk = _read_json(_slot_path(main.dir))
    assert slot_on_disk["scale"] == pytest.approx(1.0)
    assert slot_on_disk["self_talk_enabled"] is True
    assert slot_on_disk["user_customized"] is True, "用户在自己的设置页保存过 ⇒ 置位落种旗标"

    on_disk = _read_json(main.path)
    assert on_disk["scale"] == 0.5, "per-slot 键不得污染主配置"
    assert on_disk["self_talk_enabled"] is False


# ------------------------------------------------------------ 2. 初值路由
def test_child_page_initial_values_come_from_main_config(tmp_path, app):
    """非 per-slot 行的初值必须来自主配置（不再显示 slot 文件里的无效快照）。"""
    main = Config(base=tmp_path)
    main.set("pet_opacity", 80)
    main.set("scale", 0.5)
    main.set("voice_chime_enabled", True)
    assert main.save() is True
    # 先用主配置落种，再把 slot 文件改成**陈旧快照**（主配置改过、slot 文件没跟上，
    # 正是"上一次落种时的样子"）：子宠页以前读的就是这一份。
    Config(base=tmp_path, instance_id="slot-1")
    assert spawn_state.write_slot_setting(main.dir, 1, "pet_opacity", 40) is True
    assert spawn_state.write_slot_setting(main.dir, 1, "voice_chime_enabled", False) is True
    assert spawn_state.write_slot_setting(main.dir, 1, "scale", 0.85) is True
    cfg = Config(base=tmp_path, instance_id="slot-1")

    dialog = _dialog(cfg)
    try:
        assert dialog.pet_opacity_spin.value() == 80, "窗口级行必须显示主配置的真值"
        assert dialog.voice_chime_page.enabled_check.isChecked() is True, (
            "语音报时行必须显示主配置的真值（slot 文件里那份是陈旧副本）"
        )
        assert float(dialog.scale_combo.currentData()) == pytest.approx(0.85), (
            "per-slot 行仍按这只宠自己的 slot 文件取源"
        )
    finally:
        dialog.close()
        dialog.deleteLater()


# ------------------------------------------------------------ 3. 恢复默认收口
def test_child_reset_touches_slot_file_only(tmp_path, app, monkeypatch):
    """子宠页「恢复默认设置」：只重置 slot 文件，主配置一个键都不碰。

    未闸住时走到了 ``Config.reset_to_defaults`` 的整表语义，而路由后那份"整表"
    是**所有桌宠共用**的主配置——点一次就把主宠与其它子宠的设置一起抹掉。
    """
    from pet import settings_reset_defaults

    main = Config(base=tmp_path)
    main.set("pet_opacity", 66)
    main.set("voice_chime_enabled", True)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")
    assert spawn_state.write_slot_setting(
        main.dir, 1, "scale", 1.0, user_customized=True) is True
    assert spawn_state.write_slot_setting(main.dir, 1, "self_talk_enabled", True) is True
    before_main = _read_json(main.path)

    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: True)
    dialog = _dialog(cfg)
    try:
        assert settings_reset_defaults.on_reset_clicked(dialog) is True
    finally:
        dialog.deleteLater()

    assert _read_json(main.path) == before_main, "子宠页恢复默认不得动主配置"
    slot_on_disk = _read_json(_slot_path(main.dir))
    assert slot_on_disk["scale"] == pytest.approx(DEFAULT_SCALE), "per-slot 键归位"
    assert slot_on_disk["self_talk_enabled"] is False
    assert slot_on_disk["user_customized"] is False


# ------------------------------------------------------------ 4. 并发纪律
def test_routed_save_reloads_main_before_writing(tmp_path):
    """路由视图自己的落盘纪律：``reload`` → 重放 pending → ``save``。

    ``Config.save`` 是**整表**写：不先重读，设置窗打开期间主进程/托盘改过的键就
    被陈旧内存快照盖回去。这一条钉在路由视图上（不依赖调用方是否记得先 reload），
    ``_write_config`` 那条端到端路径见下一条。
    """
    main = Config(base=tmp_path)
    main.set("mem_min_size_mb", 50.0)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")
    routed = settings_slot_config.route_settings_config(cfg)
    assert routed is not cfg

    routed.set("pet_opacity", 30)
    external = Config(base=tmp_path)
    external.set("mem_min_size_mb", 123.0)
    assert external.save() is True

    assert routed.save() is True
    on_disk = _read_json(main.path)
    assert on_disk["pet_opacity"] == 30, "本次要改的键要落盘"
    assert on_disk["mem_min_size_mb"] == 123.0, "外部并发改动被陈旧内存快照盖回去了"


def test_child_save_does_not_roll_back_external_main_change(tmp_path, app):
    """设置窗开着时主配置被外部改写 → 子宠页保存（整表写主配置）不得盖回该键。"""
    main = Config(base=tmp_path)
    main.set("mem_min_size_mb", 50.0)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")

    dialog = _dialog(cfg)
    try:
        external = Config(base=tmp_path)
        external.set("mem_min_size_mb", 123.0)
        assert external.save() is True

        dialog.pet_opacity_spin.setValue(30)
        assert dialog._write_config() is True
    finally:
        dialog.deleteLater()

    on_disk = _read_json(main.path)
    assert on_disk["pet_opacity"] == 30, "本次要改的键要落盘"
    assert on_disk["mem_min_size_mb"] == 123.0, "外部并发改动被陈旧内存快照盖回去了"


# ------------------------------------------------------------ 5. 置灰摘除（路由接通后真生效）
def test_harness_controls_are_editable_on_the_child_page(tmp_path, app):
    """子宠页：「随桌宠启动 dsh 服务」与其目标下拉可编辑，保存落主配置。

    两个键是进程级的（拉起的是这台机器上的 dsh 服务），子宠页曾经按
    「仅主桌宠可设置」置灰——理由与其余 6 组同源（写了 slot 文件、运行期读主配置）。
    路由接通后写主配置、真生效，故摘掉置灰。
    """
    main = Config(base=tmp_path)
    assert main.save() is True
    cfg = Config(base=tmp_path, instance_id="slot-1")

    dialog = _dialog(cfg)
    try:
        assert dialog.harness_autostart_check.isEnabled() is True
        assert dialog.harness_launch_target_select.isEnabled() is True
        assert dialog.harness_autostart_check.toolTip() != "仅主桌宠可设置"

        dialog.harness_autostart_check.setChecked(True)
        dialog.harness_launch_target_select.setCurrentData("service")
        assert dialog.harness_launch_target_select.currentData() == "service"
        assert dialog._write_config() is True
    finally:
        dialog.deleteLater()

    on_disk = _read_json(main.path)
    assert on_disk["harness_autostart"] is True, "子宠页改的键必须真正生效"
    assert on_disk["harness_launch_target"] == "service"


# ------------------------------------------------------------ 6. 分流范围（只对 overlay 的 slot 身份）
def test_main_pet_config_is_not_routed(tmp_path):
    """主宠设置进程（无 --instance）：原样返回，行为逐位不变。"""
    main = Config(base=tmp_path)
    assert settings_slot_config.route_settings_config(main) is main


def test_legacy_topology_slot_config_is_not_routed(tmp_path, monkeypatch):
    """legacy 单窗：那只宠读的就是自己那份 slot 文件的全部键，不许分流。"""
    from pet import overlay_settings_command as cmd_mod

    monkeypatch.setenv(cmd_mod.ENV_TOPOLOGY, "legacy")
    cfg = Config(base=tmp_path, instance_id="slot-1")
    assert settings_slot_config.route_settings_config(cfg) is cfg


def test_non_slot_instance_is_not_routed(tmp_path):
    """非 slot-N 的实例身份（测试/诊断用法）：没有可写的 slot 文件，不分流。"""
    cfg = Config(base=tmp_path, instance_id="probe-a")
    assert settings_slot_config.route_settings_config(cfg) is cfg


def test_routed_keys_cover_the_runtime_per_slot_read_surface(tmp_path):
    """分流键集必须覆盖运行期的逐宠取源面，且键集全仓单一来源。

    ``_SpriteConfig.get`` 的 per-slot 读点有两处：``PER_SLOT_SETTING_KEYS`` 分支，
    以及紧随其后 ``collision_enabled`` 的专属分支（``read_slot_collision_enabled``
    读这只宠的 slot 文件）。两处的键都必须分流到 slot 文件，否则子宠页改它等于没改
    （写进主配置既改不动这只宠，又会顺手改掉别的宠的继承值）。
    """
    from pet import overlay_shell, overlay_spawn_state as spawn_state_mod

    assert overlay_shell.PER_SLOT_SETTING_KEYS is spawn_state_mod.PER_SLOT_SETTING_KEYS, (
        "PER_SLOT_SETTING_KEYS 必须全仓单一来源（设置在轻模块、壳侧引用）"
    )
    assert overlay_shell.PER_SLOT_SETTING_KEYS <= settings_slot_config.SLOT_ROUTED_KEYS
    assert "collision_enabled" in settings_slot_config.SLOT_ROUTED_KEYS
    assert "user_customized" in settings_slot_config.SLOT_LOCAL_KEYS
    for main_only in ("pet_opacity", "voice_chime_enabled", "edge_probe_enabled",
                      "dynamic_island", "context_menu_appearance"):
        assert main_only not in settings_slot_config.SLOT_ROUTED_KEYS
