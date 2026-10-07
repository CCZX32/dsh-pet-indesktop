# -*- coding: utf-8 -*-
"""「恢复默认设置」聚焦测试（issue #220）。

语义契约（整体重置，不做按分页重置）：
1. 除保留集外的全部键回到出厂默认（口径 = 全新安装的 ``Config.data``）；
2. 保留集 = chat 域密钥类字段（``api_key``/``vision_api_key`` 及其 keyring 引用），
   因为 API Key 是用户最难重配的一项，且 keyring 不可用时明文只存在内存里。
   **自定义 provider 也一样**：条目按重置口径只剩「名字 + 凭据」骨架，凭据必须
   在任何情况下仍可读出（否则确认文案的「保留 AI 对话密钥」就是空话）；
3. 落盘走既有 ``save()`` 原子写路径（``atomic_replace_with_retry``，#194 教训）；
4. 用户取消 / 落盘失败 = 零副作用（内存与磁盘都不变）；
5. 重置后关窗不得把旧控件值整表写回（设置窗关闭时会保存全部控件，控件持有的是
   重置前的旧值，不闸住就把刚写的默认值覆盖回去）；
6. 重置级运行态对齐：位置（rx/ry=None）要立即回默认落位，否则本次退出
   ``save_position()`` 会把重置前的旧位置写回磁盘、重置被静默抵消；系统登录项
   单独按新值收敛。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtWidgets import QApplication, QDialog

from pet import config as config_mod
from pet import overlay_settings_command as cmd_mod
from pet import settings_reset_defaults
from pet import window_placement
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _no_real_autostart_writes(monkeypatch):
    """本文件一律不碰真实系统登录项：autostart 通道默认打桩成"没开"。

    重置链路会按新值收敛 OS 登录项（``sync_system_autostart``）——测试机上真的开了
    开机自启时，跑一次用例就会把它关掉。需要断言该行为的用例在用例体内自行覆盖
    （test_reset_syncs_system_autostart_login_item 等已如此）。
    """
    from pet import autostart as autostart_mod

    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart_mod, "set_enabled", lambda _on: True)


def _fresh_config(base: Path) -> Config:
    """一份全新安装口径的 Config（目录里没有任何配置文件）。"""
    return Config(base=base)


def _settings_only(data: dict, fresh: dict) -> dict:
    """只留"设置面"的深拷贝（摘掉保留集，供"其余全等于默认"的比较）。

    - 默认集里的 provider：只摘掉凭据字段；
    - 非默认 provider 的条目整个摘掉——重置后它是"只装凭据的容器"（内存里刚重置
      完只有名字+凭据，重新加载后由 ``_merge_chat_data`` 按默认模板补齐骨架），
      容器自身的形状与内容另有专项测试（rebuilds_credential_only_entry）。
    """
    data = copy.deepcopy(data)
    providers = data.get("chat", {}).get("providers")
    default_ids = set((fresh.get("chat") or {}).get("providers") or {})
    if isinstance(providers, dict):
        for provider_id in list(providers):
            if provider_id not in default_ids:
                providers.pop(provider_id)
                continue
            provider = providers[provider_id]
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
    assert _settings_only(cfg.data, fresh.data) != _settings_only(fresh.data, fresh.data), "前置条件：脏配置必须偏离默认值"

    assert cfg.reset_to_defaults() is True

    assert _settings_only(cfg.data, fresh.data) == _settings_only(fresh.data, fresh.data)
    provider = cfg.data["chat"]["providers"]["openai-main"]
    assert provider["api_key"] == "sk-live-secret", "明文 Key 必须原样保留"
    assert provider["vision_api_key"] == "sk-live-vision"
    assert provider["api_key_ref"] == "provider/legacy-main", "keyring 引用必须原样保留"
    assert provider["vision_api_key_ref"] == "provider/legacy-main/vision"


def test_reset_keeps_custom_provider_credentials_when_keyring_unavailable(
        tmp_path: Path, monkeypatch):
    """B1：keyring 不可用时，自定义 provider 的明文密钥必须活过重置。

    旧行为只回填"默认集里仍存在的 provider"（openai-main），自定义 provider 的
    条目被重置掉 → 内存明文密钥永久丢失，而确认文案承诺「保留 AI 对话密钥」。
    断言落在**生产读密钥口径**上（``Config.resolve_api_key`` = keyring 优先、
    取不到回落明文），而不是只看配置里的字段。
    """
    from pet.chat.models import SecretStore

    monkeypatch.setattr(SecretStore, "get", lambda self, ref: "")  # keyring 不可用

    cfg = _dirty_config(tmp_path / "appdata")
    assert cfg.reset_to_defaults() is True

    settings = cfg.chat_settings()
    relay = settings.providers["relay"]
    assert cfg.resolve_api_key(relay) == "sk-relay", "自定义服务商的密钥必须仍可读出"


def test_reset_rebuilds_credential_only_entry_for_custom_providers(tmp_path: Path):
    """自定义 provider 只留「名字 + 凭据」骨架；其余字段按重置口径回默认模板。"""
    cfg = _dirty_config(tmp_path / "appdata")
    assert cfg.reset_to_defaults() is True

    entry = cfg.data["chat"]["providers"]["relay"]
    assert set(entry) <= {"name", *config_mod.CHAT_SECRET_FIELDS}
    assert "base_url" not in entry and "model" not in entry, "中转站地址/模型不得被当凭据保留"
    assert entry["api_key"] == "sk-relay"

    reloaded = Config(base=tmp_path / "appdata")  # 加载路径按默认模板补齐骨架
    relay = reloaded.data["chat"]["providers"]["relay"]
    assert relay["base_url"] == "https://api.deepseek.com"
    assert relay["model"] == "deepseek-v4-flash"
    assert relay["api_key_ref"] == "provider/relay", "凭据引用必须留下（钥匙串里的 key 靠它取回）"
    # 重置后活跃 provider 仍是默认那一个：被保留的凭据容器不会被自动选中。
    assert reloaded.data["chat"]["active_provider"] == "openai-main"


def test_reset_does_not_touch_keyring_and_drops_non_credential_fields(tmp_path: Path, monkeypatch):
    """保留集之外什么都不保：自定义服务商的地址/模型/提示词回默认（钥匙串条目不删除）。

    重置只写配置文件，**从不**调用 SecretStore：自定义服务商的 keyring 条目原样
    留在系统钥匙串里（删掉才是数据丢失）。
    """
    from pet.chat.models import SecretStore

    def boom(*_args, **_kwargs):  # pragma: no cover - 只在被调用时触发
        raise AssertionError("重置设置不得触碰系统钥匙串")

    monkeypatch.setattr(SecretStore, "set", boom)

    cfg = _dirty_config(tmp_path / "appdata")
    assert cfg.reset_to_defaults() is True

    providers = cfg.data["chat"]["providers"]
    assert providers["relay"]["api_key"] == "sk-relay"          # 只有凭据活着
    assert providers["relay"]["name"] == "中转"                  # 骨架名（便于认出是哪个服务商）
    assert cfg.data["chat"]["active_provider"] == "openai-main"
    assert cfg.data["chat"]["default_system_prompt"] != "自定义提示词"


def test_reset_result_survives_reload(tmp_path: Path):
    """重置结果必须在重新加载后依然成立（主进程 watcher 走的就是这条路径）。"""
    cfg = _dirty_config(tmp_path / "appdata")
    fresh = _fresh_config(tmp_path / "fresh")
    assert cfg.reset_to_defaults() is True

    reloaded = Config(base=tmp_path / "appdata")

    assert _settings_only(reloaded.data, fresh.data) == _settings_only(fresh.data, fresh.data)
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
    assert _settings_only(reloaded.data, fresh.data) == _settings_only(fresh.data, fresh.data), (
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
        assert "只装密钥的条目" in text, "自定义服务商的凭据容器语义要写准"
        assert "立即回默认落位" in text, "位置立即生效必须写明"
        assert "开机自启按默认关闭" in text, "系统登录项会被改，必须写明"
        assert "重启后生效" in text, "重启生效的键必须与控制事实现状一致"
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


# ---------------------------------------------------------------- 4. 重置级运行态对齐
# 重置只落盘 + 走普通刷新是不够的：位置（rx/ry=None）不重定位，用户看不到任何变化，
# 而本次进程正常退出时 save_position() 会把运行态几何写回磁盘——重置前的旧位置
# 因此被"合法地"写回去，重置被静默抵消。下面固定「重置级对齐」这条链。

class _Host:
    """设置窗最小替身：只提供重置链路需要的鸭子面（config / parent / 关窗）。"""

    def __init__(self, config, parent=None):
        self.config = config
        self._parent = parent
        self.closed = 0

    def parentWidget(self):
        return self._parent

    def _close_after_external_write(self):
        self.closed += 1


class _StubScreen:
    def __init__(self, name, geometry):
        self._name = name
        self._geometry = geometry

    def name(self):
        return self._name

    def availableGeometry(self):
        return self._geometry

    def devicePixelRatio(self):
        return 1.0


class _StubPet:
    """window_placement 的轻量宿主桩（与 tests/test_window_position.py 同型）。

    真实的 ``save_position`` / ``go_default_corner`` 实现照跑——两者都显式支持
    轻量桩（``move()`` 回退分支），所以这里量到的是真实落位与真实写盘。
    """

    cfg = None
    facing = "left"
    scale = 1.0
    _w = 220
    _h = 260
    _capture_headroom = 0

    def __init__(self, cfg, screen, pos):
        self.cfg = cfg
        self._screen = screen
        self._pos = QPointF(*pos)
        self._awaiting_saved_screen = None
        self._saved = 0

    def _screen_available(self, screen_name=None):
        return self._screen

    def move(self, x, y):
        self._pos = QPointF(float(x), float(y))

    def x(self):
        return int(self._pos.x())

    def y(self):
        return int(self._pos.y())

    def _cancel_move(self):
        pass

    def _stop_physics(self):
        pass

    def _save_position(self):
        self._saved += 1
        return window_placement.save_position(self)

    def go_default_corner(self):
        # 与 PetWindow 同型：公开转发到 window_placement（真实落位 + 真实落盘）
        return window_placement.go_default_corner(self)


def _stub_instance(cfg, screen, pos):
    class _Instance:
        def __init__(self):
            self.win = _StubPet(cfg, screen, pos)
    return _Instance()


def _stub_shell(instance):
    from pet.app import AppShell

    shell = AppShell.__new__(AppShell)
    shell.instance = instance
    shell._instances = [instance]
    shell.config = instance.win.cfg
    return shell


def test_reload_adopts_reset_position_nulls(tmp_path: Path):
    """rx/ry/screen_name 的显式 null 必须被采纳，否则运行期永远留着重置前的位置。

    这三个键的消费者（window_placement.restore_position / overlay 落位）本来就把
    None 当"没有位置记忆"，所以它们进 _NULL_ACCEPTING_KEYS 是同一个口径的延伸。
    """
    cfg = _dirty_config(tmp_path / "appdata")
    cfg.data.update({"rx": 0.42, "ry": 0.42, "screen_name": "primary"})
    assert cfg.save() is True
    assert cfg.reset_to_defaults() is True
    assert cfg.get("rx") is None and cfg.get("screen_name") is None

    # 运行期已有的值（模拟主进程内存里的旧位置）被重置后的磁盘数据覆盖
    cfg.data["rx"], cfg.data["ry"], cfg.data["screen_name"] = 0.42, 0.42, "primary"
    cfg.reload()

    assert cfg.get("rx") is None, "显式 null 未被采纳：运行期会一直留着旧位置"
    assert cfg.get("ry") is None
    assert cfg.get("screen_name") is None


def test_reset_asks_parent_window_to_align_runtime(tmp_path: Path, monkeypatch):
    """进程内设置页：重置后直接调窗口上已接线的回调（不走指令通道），并同步系统项。"""
    from pet import autostart as autostart_mod

    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: True)
    calls: list[str] = []
    parent = type("_Win", (), {})()
    parent.on_settings_reset = lambda: calls.append("window")
    os_calls: list[bool] = []
    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: True)
    monkeypatch.setattr(autostart_mod, "set_enabled", lambda on: (os_calls.append(bool(on)), True)[1])
    cfg = _dirty_config(tmp_path / "appdata")
    host = _Host(cfg, parent)

    assert settings_reset_defaults.on_reset_clicked(host) is True

    assert calls == ["window"], "有桌宠窗口时必须直接请求它对齐运行态"
    assert os_calls == [False], "重置链路必须把系统登录项一起收敛"
    assert not cmd_mod.command_path(cfg.dir).exists(), "进程内不必写指令文件"


def test_reset_writes_alignment_command_without_parent_window(tmp_path: Path, monkeypatch):
    """独立设置进程：没有窗口可依附 → 写 D12 指令，由主进程消费后对齐。"""
    monkeypatch.setattr(settings_reset_defaults, "confirm_reset", lambda _parent: True)
    cfg = Config(tmp_path / "appdata", instance_id="slot-2")
    host = _Host(cfg)

    assert settings_reset_defaults.on_reset_clicked(host) is True

    command = cmd_mod.read_command(cfg.dir)
    assert command is not None, "独立设置进程必须写下运行态对齐指令"
    assert command["command"] == cmd_mod.CMD_APPLY_SETTINGS_RESET
    assert command["target"] == 2, "只对齐这一份配置对应的那只桌宠"


def test_apply_settings_reset_repositions_window_without_position_memory(tmp_path: Path):
    """AppShell 侧：重置级对齐把这一只送回默认落位（不依赖配置里的 rx/ry 读数）。"""
    screen = _StubScreen("primary", QRect(0, 0, 1920, 1040))
    cfg = _dirty_config(tmp_path / "appdata")
    cfg.data.update({"rx": 0.42, "ry": 0.42, "screen_name": "primary"})
    assert cfg.save() is True
    instance = _stub_instance(cfg, screen, (int(0.42 * 1920) - 110, int(0.42 * 1040) - 130))
    shell = _stub_shell(instance)
    before = (instance.win.x(), instance.win.y())

    assert cfg.reset_to_defaults() is True
    shell.apply_settings_reset(instance)

    assert (instance.win.x(), instance.win.y()) != before, "重置后桌宠必须回默认落位"
    assert cfg.get("rx") is not None, "对齐顺带落盘：位置记忆就是刚落的默认落位"


def test_exit_position_save_after_reset_keeps_default_placement(tmp_path: Path):
    """required 回归：重置后退出进程，盘上位置不得是重置前的旧值。

    退出收口就是 ``win.save_position()``（app.py:2240 / app.py:3159）→
    ``window_placement.save_position`` 写**运行态几何**。所以只要重置级对齐把运行态
    摆到默认落位，磁盘拿到的就是新位置而不是旧位置（旧行为下这里会写回 0.42）。
    """
    screen = _StubScreen("primary", QRect(0, 0, 1920, 1040))
    cfg = _dirty_config(tmp_path / "appdata")
    cfg.data.update({"rx": 0.42, "ry": 0.42, "screen_name": "primary"})
    assert cfg.save() is True
    instance = _stub_instance(cfg, screen, (int(0.42 * 1920) - 110, int(0.42 * 1040) - 130))
    shell = _stub_shell(instance)

    assert cfg.reset_to_defaults() is True
    shell.apply_settings_reset(instance)      # ← 重置级对齐（生产路径）
    window_placement.save_position(instance.win)   # ← 退出收口（生产路径）

    reloaded = Config(base=tmp_path / "appdata")
    assert reloaded.get("rx") != pytest.approx(0.42), "退出时把重置前的旧位置写回了磁盘"
    assert reloaded.get("ry") != pytest.approx(0.42)
    assert reloaded.get("rx") == pytest.approx(instance.win.cfg.get("rx")), "盘上应与运行态一致"
    assert reloaded.get("rx") > 0.9, f"默认落位应贴右下角，实际 rx={reloaded.get('rx')}"


def test_settings_reset_command_is_consumed_and_aligns_legacy_window(
        tmp_path: Path, monkeypatch):
    """D12 指令 → AppShell 消费 → 只对齐指令点名的那一只。"""
    cfg = _dirty_config(tmp_path / "appdata")
    main = _stub_instance(cfg, _StubScreen("primary", QRect(0, 0, 1920, 1040)), (100, 100))
    aligned: list = []

    shell = _stub_shell(main)
    shell.apply_settings_reset = lambda instance=None: aligned.append(instance)
    assert cmd_mod.write_command(cfg.dir, cmd_mod.CMD_APPLY_SETTINGS_RESET) is True

    shell._consume_settings_command()

    assert aligned == [main]
    assert not cmd_mod.command_path(cfg.dir).exists(), "消费即删"


def test_reset_syncs_system_autostart_login_item(tmp_path: Path, monkeypatch):
    """系统登录项按重置后的值收敛（默认关）；已是目标值时不重复写注册表。"""
    from pet import autostart as autostart_mod

    calls: list[bool] = []
    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: True)
    monkeypatch.setattr(
        autostart_mod, "set_enabled",
        lambda on: (calls.append(bool(on)), True)[1])

    host = _Host(_dirty_config(tmp_path / "appdata"))
    settings_reset_defaults.sync_system_autostart(host)
    assert calls == [False], "重置把 autostart_wanted 清成 False → 系统登录项必须关掉"

    calls.clear()
    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)
    settings_reset_defaults.sync_system_autostart(host)
    assert calls == [], "系统侧已是目标值 → 不重复写"


def test_reset_leaves_system_autostart_alone_for_child_pet(tmp_path: Path, monkeypatch):
    """子宠设置页不碰系统登录项（该控件在子宠页本就禁用，与既有 gating 同口径）。"""
    from pet import autostart as autostart_mod

    calls: list[bool] = []
    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: True)
    monkeypatch.setattr(
        autostart_mod, "set_enabled",
        lambda on: (calls.append(bool(on)), True)[1])

    cfg = Config(tmp_path / "appdata", instance_id="slot-1")
    settings_reset_defaults.sync_system_autostart(_Host(cfg))

    assert calls == []


def test_settings_reset_command_aligns_overlay_sprite(tmp_path: Path):
    """overlay 侧：指令消费后主 sprite 按默认落位重摆（rx/ry=None 的落位语义）。"""
    from tests.test_overlay_spawn import _make_persistent_shell

    shell, _ = _make_persistent_shell(tmp_path)
    try:
        shell.sprite.set_pos(QPointF(50, 60))
        moved = QPointF(shell.sprite.pos)
        assert cmd_mod.write_command(
            shell._config.dir, cmd_mod.CMD_APPLY_SETTINGS_RESET) is True

        shell._consume_settings_command()

        assert QPointF(shell.sprite.pos) != moved, "重置后主宠必须回默认落位"
        assert not cmd_mod.command_path(shell._config.dir).exists()
    finally:
        shell._teardown_settings_command_watch()
        shell._delete_runtime_marker()
        if getattr(shell, "tray", None) is not None:
            shell.tray.hide()
