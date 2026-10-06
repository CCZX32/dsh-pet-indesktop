# -*- coding: utf-8 -*-
"""「恢复默认设置」聚焦测试（issue #220）。

语义契约（整体重置，不做按分页重置）：
1. 除保留集外的全部键回到出厂默认（口径 = 全新安装的 ``Config.data``）；
2. 保留集 = chat 域密钥类字段（``api_key``/``vision_api_key`` 及其 keyring 引用），
   因为 API Key 是用户最难重配的一项，且 keyring 不可用时明文只存在内存里；
3. 落盘走既有 ``save()`` 原子写路径（``atomic_replace_with_retry``，#194 教训）；
4. 用户取消 / 落盘失败 = 零副作用（内存与磁盘都不变）；
5. 重置后关窗不得把旧控件值整表写回（本文件最重要的一条回归——设置窗关闭时会
   保存全部控件，控件持有的是重置前的旧值，不闸住就把刚写的默认值覆盖回去）。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from pet import config as config_mod
from pet import settings_reset_defaults
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fresh_config(base: Path) -> Config:
    """一份全新安装口径的 Config（目录里没有任何配置文件）。"""
    return Config(base=base)


def _strip_secrets(data: dict) -> dict:
    """剔除 chat 域密钥类字段后的深拷贝（保留集不参与"等于默认值"比较）。"""
    data = copy.deepcopy(data)
    providers = data.get("chat", {}).get("providers")
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict):
                for field in config_mod.CHAT_SECRET_FIELDS:
                    provider.pop(field, None)
    return data


def _dirty_config(base: Path) -> Config:
    """把一份配置改成"被用户改坏"的样子（含自定义密钥与非默认值）。"""
    cfg = Config(base)
    cfg.data.update(
        {
            "playback_speed": 3.5,
            "pet_opacity": 40,
            "mouse_through": True,
            "lock_position": True,
            "self_talk_enabled": True,
            "self_talk_texts": ["自定义台词"],
            "click_sound_volume": 0.2,
            "collision_restitution": 0.1,
            "todo_reminder_lead_minutes": 30,
            "voice_chime_enabled": True,
            "character_aliases": {"default": "小名"},
            "context_menu_appearance": {"theme": "dark", "density": "compact"},
            "chat": {
                "enabled": False,
                "active_provider": "relay",
                "default_system_prompt": "自定义提示词",
                "history_message_limit": 5,
                "providers": {
                    "openai-main": {
                        "name": "DeepSeek",
                        "base_url": "https://api.deepseek.com",
                        "model": "deepseek-v4-flash",
                        # 明文 key（keyring 不可用时的兜底）与自定义钥匙串引用：
                        # 两者都是保留集，重置后必须原样还在。
                        "api_key": "sk-live-secret",
                        "api_key_ref": "provider/legacy-main",
                        "vision_api_key": "sk-live-vision",
                        "vision_api_key_ref": "provider/legacy-main/vision",
                    },
                    "relay": {
                        "name": "中转",
                        "base_url": "https://relay.example.com",
                        "model": "gpt-4o",
                        "api_key": "sk-relay",
                    },
                },
            },
        }
    )
    assert cfg.save() is True, "前置条件：脏配置必须能落盘"
    return cfg


def _spy_atomic_replace(monkeypatch) -> list[tuple[Path, Path]]:
    """记录 save() 的原子替换调用（探针，不是打桩：仍调真实实现）。"""
    calls: list[tuple[Path, Path]] = []
    real = config_mod.atomic_replace_with_retry

    def spy(temp, target, *args, **kwargs):
        calls.append((Path(temp), Path(target)))
        return real(temp, target, *args, **kwargs)

    monkeypatch.setattr(config_mod, "atomic_replace_with_retry", spy)
    return calls


# ---------------------------------------------------------------- 1. 重置语义

def test_reset_restores_every_non_secret_key_to_defaults(tmp_path: Path):
    """重置后：所有非保留键 == 全新安装默认值，保留键原样。"""
    cfg = _dirty_config(tmp_path / "appdata")
    fresh = _fresh_config(tmp_path / "fresh")
    assert _strip_secrets(cfg.data) != _strip_secrets(fresh.data), "前置条件：脏配置必须偏离默认值"

    assert cfg.reset_to_defaults() is True

    assert _strip_secrets(cfg.data) == _strip_secrets(fresh.data)
    provider = cfg.data["chat"]["providers"]["openai-main"]
    assert provider["api_key"] == "sk-live-secret", "明文 Key 必须原样保留"
    assert provider["vision_api_key"] == "sk-live-vision"
    assert provider["api_key_ref"] == "provider/legacy-main", "keyring 引用必须原样保留"
    assert provider["vision_api_key_ref"] == "provider/legacy-main/vision"


def test_reset_does_not_touch_keyring_and_drops_extra_providers(tmp_path: Path, monkeypatch):
    """保留集之外什么都不保：自定义服务商条目回到默认（其钥匙串条目不被删除）。

    重置只写配置文件，**从不**调用 SecretStore：自定义服务商的 keyring 条目原样
    留在系统钥匙串里（删掉才是数据丢失）。
    """
    from pet.chat.models import SecretStore

    def boom(*_args, **_kwargs):  # pragma: no cover - 只在被调用时触发
        raise AssertionError("重置设置不得触碰系统钥匙串")

    monkeypatch.setattr(SecretStore, "set", boom)

    cfg = _dirty_config(tmp_path / "appdata")
    assert cfg.reset_to_defaults() is True

    assert "relay" not in cfg.data["chat"]["providers"]
    assert cfg.data["chat"]["active_provider"] == "openai-main"
    assert cfg.data["chat"]["default_system_prompt"] != "自定义提示词"


def test_reset_result_survives_reload(tmp_path: Path):
    """重置结果必须在重新加载后依然成立（主进程 watcher 走的就是这条路径）。"""
    cfg = _dirty_config(tmp_path / "appdata")
    fresh = _fresh_config(tmp_path / "fresh")
    assert cfg.reset_to_defaults() is True

    reloaded = Config(base=tmp_path / "appdata")

    assert _strip_secrets(reloaded.data) == _strip_secrets(fresh.data)
    # 明文 Key 不落盘（_redacted_data 脱敏），但 keyring 引用必须落盘。
    assert reloaded.data["chat"]["providers"]["openai-main"]["api_key_ref"] == "provider/legacy-main"
    assert reloaded.data["chat"]["providers"]["openai-main"]["api_key"] == ""
    assert reloaded.data["pet_opacity"] == fresh.data["pet_opacity"]


# ---------------------------------------------------------------- 2. 落盘路径

def test_reset_writes_through_atomic_replace(tmp_path: Path, monkeypatch):
    """重置走 save() 同一条原子写路径，且临时文件被清干净。"""
    cfg = _dirty_config(tmp_path / "appdata")
    calls = _spy_atomic_replace(monkeypatch)
    calls.clear()

    assert cfg.reset_to_defaults() is True

    assert len(calls) == 1, "重置应当只落盘一次（批量改配置 + 一次性落盘）"
    temp, target = calls[0]
    assert target == cfg.path
    assert temp.name == f"{cfg.path.name}.{os.getpid()}.tmp"
    assert not temp.exists(), "临时文件必须被清掉（失败残留会污染配置目录）"
    on_disk = json.loads(cfg.path.read_text(encoding="utf-8"))
    assert on_disk["pet_opacity"] == 100


def test_reset_write_failure_rolls_back_memory(tmp_path: Path, monkeypatch):
    """落盘失败：返回 False、内存回滚、磁盘不变（不许出现"内存默认/磁盘旧值"）。"""
    cfg = _dirty_config(tmp_path / "appdata")
    before_memory = copy.deepcopy(cfg.data)
    before_disk = cfg.path.read_text(encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_mod, "atomic_replace_with_retry", fail)

    assert cfg.reset_to_defaults() is False

    assert cfg.data == before_memory
    assert cfg.path.read_text(encoding="utf-8") == before_disk


# ---------------------------------------------------------------- 3. 设置页接线

def test_reset_button_confirm_applies_defaults_and_skips_stale_writeback(
        qapp, tmp_path: Path, monkeypatch):
    """确认后：默认值落盘 + 关窗；关闭路径不得把旧控件值整表写回。"""
    cfg = _dirty_config(tmp_path / "appdata")
    fresh = _fresh_config(tmp_path / "fresh")
    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: True)

    dialog = ModernSettingsDialog(cfg, include_ai=False)
    assert getattr(dialog, "_saved_via_button", False) is False

    dialog.reset_defaults_btn.click()

    assert dialog.result() == QDialog.DialogCode.Accepted, "重置后应关窗（用户看到操作生效）"

    dialog.close()
    qapp.processEvents()

    reloaded = Config(base=tmp_path / "appdata")
    assert _strip_secrets(reloaded.data) == _strip_secrets(fresh.data), (
        "关窗路径把旧控件值写回去了：重置被静默回滚"
    )
    assert reloaded.data["chat"]["providers"]["openai-main"]["api_key_ref"] == "provider/legacy-main"
    assert getattr(dialog, "_saved_via_button", False) is True, "必须闸住关闭时的整表写回"


def test_reset_button_cancel_has_zero_side_effect(qapp, tmp_path: Path, monkeypatch):
    """取消确认：不写盘、内存不变、窗口不关（零副作用）。"""
    cfg = _dirty_config(tmp_path / "appdata")
    before_memory = copy.deepcopy(cfg.data)
    before_disk = cfg.path.read_text(encoding="utf-8")
    calls = _spy_atomic_replace(monkeypatch)
    calls.clear()
    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: False)

    dialog = ModernSettingsDialog(cfg, include_ai=False)
    try:
        dialog.reset_defaults_btn.click()

        assert calls == [], "取消不得落盘"
        assert cfg.data == before_memory
        assert cfg.path.read_text(encoding="utf-8") == before_disk
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert getattr(dialog, "_saved_via_button", False) is False
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_reset_button_reports_write_failure_instead_of_closing(
        qapp, tmp_path: Path, monkeypatch):
    """落盘失败：如实告警、不关窗、内存与磁盘都不变（不许假装重置成功）。"""
    from PySide6.QtWidgets import QMessageBox

    cfg = _dirty_config(tmp_path / "appdata")
    before_memory = copy.deepcopy(cfg.data)
    before_disk = cfg.path.read_text(encoding="utf-8")
    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: True)

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_mod, "atomic_replace_with_retry", fail)
    warnings: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    dialog = ModernSettingsDialog(cfg, include_ai=False)
    try:
        dialog.reset_defaults_btn.click()

        assert len(warnings) == 1, "落盘失败必须告警"
        assert dialog.result() != QDialog.DialogCode.Accepted, "未生效不得关窗"
        assert getattr(dialog, "_saved_via_button", False) is False
        assert cfg.data == before_memory
        assert cfg.path.read_text(encoding="utf-8") == before_disk
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_reset_confirm_box_copy_states_kept_items_and_irreversibility(qapp, tmp_path: Path):
    """二次确认文案：写清"重置全部"、保留项、不可撤销，且默认按钮是取消。"""
    box, confirm = settings_reset_defaults.build_reset_confirm_box(None)
    try:
        text = box.text() + "\n" + box.informativeText()
        assert "将重置全部设置为默认值" in text
        assert "不可撤销" in text
        assert "API Key" in text, "保留项必须逐项写明"
        assert "钥匙串" in text, "保留的 keyring 引用要说清楚"
        assert confirm.text() == "恢复默认设置"
        assert box.defaultButton() is not confirm, "破坏性操作的默认按钮不得是确认"
    finally:
        box.deleteLater()
        qapp.processEvents()


def test_reset_button_is_reachable_and_unclipped_at_minimum_window_size(qapp, tmp_path: Path):
    """最小窗口尺寸（720×500）下按钮可见、文案不裁切（SETTINGS-CHANGE-GATES §3）。"""
    cfg = Config(tmp_path / "appdata")
    dialog = ModernSettingsDialog(cfg, include_ai=False)
    try:
        dialog.resize(dialog.minimumSize())
        dialog.show()
        qapp.processEvents()

        button = dialog.reset_defaults_btn
        assert button.isVisible(), "侧栏底部的重置入口必须在最小尺寸下可达"
        assert button.text() == settings_reset_defaults.RESET_BUTTON_TEXT
        assert button.width() >= button.sizeHint().width(), "按钮被压到文案裁切"
        assert button.toolTip(), "破坏性操作必须有不裁切的说明（tooltip）"
        assert button.focusPolicy() != Qt.FocusPolicy.NoFocus, "键盘（Tab）必须够得着"
    finally:
        dialog.hide()
        dialog.deleteLater()
        qapp.processEvents()
