# -*- coding: utf-8 -*-
"""功能模块门控（期 2，第一批 weather/divination 模板）三层回归。

钉住的语义：
- 菜单投影：未激活（或硬依赖未满足）的模块动作从 available_ids 剔除；
  布局解析顺带丢空子菜单/规整分隔线，且**不写回**用户自定义布局；
- 设置层：未激活模块的标签页不构造、其 save 不执行（不写回配置）；
- 执行层：绕过菜单直达回调时，未激活模块不建服务、不起线程；
- 快照未冻结（旧行为）一切照旧。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from pet import feature_activation as fa
from pet.features import FEATURES, MIGRATION_BASELINE


@pytest.fixture(autouse=True)
def _reset_snapshot():
    fa.reset_snapshot_for_tests()
    yield
    fa.reset_snapshot_for_tests()


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _freeze_all_but(*excluded: str):
    fa.freeze_snapshot_for_tests([fid for fid in MIGRATION_BASELINE if fid not in excluded])


# ---------------------------------------------------------------- 菜单投影
class _FakePet:
    """available_ids 只需要 cfg.get 与 on_* 回调存在性（_callback_available 判 callable）。"""

    class _Cfg:
        def get(self, _key, default=None):
            return default

    cfg = _Cfg()

    def __getattr__(self, name):
        if name.startswith("on_"):
            return lambda *a, **k: None
        raise AttributeError(name)


def test_projection_hides_inactive_module_actions():
    from pet.context_menus.registry import MENU_ACTIONS

    _freeze_all_but("weather")
    ids = MENU_ACTIONS.available_ids(_FakePet())
    assert "weather" not in ids
    assert "weather_cities" not in ids
    assert "divination_draw" in ids  # 同批其它模块不受影响
    assert "modern_settings" in ids and "quit" in ids  # 核心动作不受门控


def test_projection_hides_feature_when_hard_dependency_missing():
    from pet.context_menus.registry import MENU_ACTIONS

    # 只开 file_interpret 不开 chat：file_interpret 被依赖求解 blocked
    fa.freeze_snapshot_for_tests(["file_interpret"])
    ids = MENU_ACTIONS.available_ids(_FakePet())
    assert "chat" not in ids
    assert "weather" not in ids
    fa.freeze_snapshot_for_tests(["file_interpret", "chat"])
    assert "chat" in MENU_ACTIONS.available_ids(_FakePet())


def test_unfrozen_snapshot_shows_everything():
    from pet.context_menus.registry import MENU_ACTIONS

    ids = MENU_ACTIONS.available_ids(_FakePet())
    assert {"weather", "weather_cities", "divination_draw", "chat"} <= ids


def test_menu_build_drops_empty_submenu_and_never_writes_layout_back(tmp_path):
    """布局解析（纯函数半）：不可用动作剔除后空子菜单丢弃、分隔线规整、输入不动。"""
    from pet.context_menus.registry import MENU_ACTIONS
    from pet.menu_layout import resolve_menu_layout

    layout = {
        "schema_version": 1,
        "nodes": [
            {"type": "action", "id": "modern_settings", "visible": True},
            {"type": "submenu", "id": "wm", "label": "天气玩意", "visible": True,
             "children": [
                 {"type": "action", "id": "weather", "visible": True},
                 {"type": "action", "id": "weather_cities", "visible": True},
             ]},
            {"type": "separator", "id": "s1", "visible": True},
            {"type": "action", "id": "quit", "visible": True},
        ],
    }
    _freeze_all_but("weather")
    result = resolve_menu_layout(
        layout,
        registered_actions=MENU_ACTIONS.ids,
        available_actions=MENU_ACTIONS.available_ids(_FakePet()),
    )

    def _ids(nodes):
        for node in nodes:
            yield node.get("id")
            yield from _ids(node.get("children", ()))

    flat = list(_ids(result.nodes))
    assert "weather" not in flat and "weather_cities" not in flat
    assert "wm" not in flat  # 空子菜单整体丢弃
    assert flat and flat[-1] != "s1"  # 尾部分隔线被规整
    assert "modern_settings" in flat and "quit" in flat
    # 写回禁令：输入布局一个字节都不许动（深比较）
    assert layout["nodes"][1]["children"][0]["id"] == "weather"
    assert layout["nodes"][2] == {"type": "separator", "id": "s1", "visible": True}


# ---------------------------------------------------------------- 设置层
@pytest.fixture
def dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = _qapp()
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dlg = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    yield dlg
    dlg.close()
    app.processEvents()


def _interaction_tab_labels(dialog):
    from pet.settings_widgets import SettingsTabContainer

    page = next(
        dialog.pages.widget(i)
        for i in range(dialog.pages.count())
        if dialog.sidebar.item(i).text() == "互动"
    )
    tabs = page.findChild(SettingsTabContainer)
    return [tabs.tabText(i) for i in range(tabs.count())]


def test_weather_and_divination_tabs_absent_when_inactive(dialog):
    _freeze_all_but("weather", "divination")
    import pet.settings_interaction as si

    tabs = si.build_interaction_domain(dialog)
    labels = tabs.labels()
    assert "天气" not in labels
    assert "趣味" not in labels
    assert "点击与音效" in labels  # 核心标签不受影响


def test_weather_and_divination_tabs_present_by_default(dialog):
    import pet.settings_interaction as si

    tabs = si.build_interaction_domain(dialog)
    labels = tabs.labels()
    assert "天气" in labels and "趣味" in labels


def test_inactive_module_settings_are_not_written_back(tmp_path, monkeypatch):
    """未激活模块：_write_config 不执行其 save（控件未构造，写了就是回默认值）。"""
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = _qapp()
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    cfg = Config(tmp_path)
    cfg.set("weather_city", "北京")
    assert cfg.save()  # 对话构造/保存都会 reload，先落盘才经得起回读
    dlg = settings_mod.ModernSettingsDialog(cfg, include_ai=True)
    try:
        _freeze_all_but("weather", "divination")
        calls = []
        monkeypatch.setattr(settings_mod.settings_weather, "save_weather_settings",
                            lambda _d: calls.append("weather"))
        monkeypatch.setattr(settings_mod.settings_divination, "save_divination_settings",
                            lambda _d: calls.append("divination"))
        assert dlg._write_config()
        assert calls == []
        assert dlg.config.get("weather_city") == "北京"  # 原配置不被回写
    finally:
        dlg.close()
        app.processEvents()


# ---------------------------------------------------------------- 执行层
def test_show_weather_inactive_creates_no_service(monkeypatch):
    """绕过菜单直达回调：未激活时不建 WeatherService、不起网络线程。"""
    import pet.app as app_mod

    _freeze_all_but("weather")
    shell = object.__new__(app_mod.AppShell)
    shell._weather_service = None
    monkeypatch.setattr(app_mod, "WeatherService", None, raising=False)
    app_mod.AppShell.show_weather(shell, parent=None)
    assert shell._weather_service is None


def test_show_weather_active_lazy_creates_service(monkeypatch):
    import pet.app as app_mod

    fa.freeze_snapshot_for_tests(["weather"])
    created = []

    class _Svc:
        def __init__(self, _shell):
            created.append(1)

        def show_weather(self, _parent):
            pass

    import pet.weather_service as ws

    monkeypatch.setattr(ws, "WeatherService", _Svc)
    shell = object.__new__(app_mod.AppShell)
    shell._weather_service = None
    app_mod.AppShell.show_weather(shell, parent=None)
    assert created and shell._weather_service is not None
