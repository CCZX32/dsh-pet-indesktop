# -*- coding: utf-8 -*-
"""功能模块门控（期 2：weather/divination 模板 + divination/todo/festival 执行层）三层回归。

钉住的语义：
- 菜单投影：未激活（或硬依赖未满足）的模块动作从 available_ids 剔除；
  布局解析顺带丢空子菜单/规整分隔线，且**不写回**用户自定义布局；
- 设置层：未激活模块的标签页不构造、其 save 不执行（不写回配置）；
- 执行层：绕过菜单直达回调时，未激活模块不建服务、不起线程。三模块各自的
  「要不要有服务对象」判据（`_todo_wanted` / `_festival_wanted` / 抽签同步）都把
  模块闸并在行为开关之上，菜单落点（`open_todo_panel` / `trigger_festival_now` /
  `trigger_divination_draw`）另有一道早退；已建服务走各自 stop/shutdown 收口；
  三个 speak 键也不许在模块停用后继续把共用报时通道拉起来；
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


# ------------------------------------- 执行层：divination / todo / festival（第二批）
class _Cfg:
    """只读配置替身：门控判据只经 ``get`` 读扁平键（与 pet.config.Config 同口径）。"""

    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def _shell(**attrs):
    """不构造真壳：只放被测方法要读的字段（``test_show_weather_*`` 同手法）。"""
    import pet.app as app_mod

    shell = object.__new__(app_mod.AppShell)
    for key, value in attrs.items():
        setattr(shell, key, value)
    return app_mod, shell


def test_divination_sync_inactive_creates_no_service(monkeypatch):
    """未激活：即使 ``divination_enabled`` 开着也不建服务（不装跨天定时器、不预合成）。"""
    import pet.divination_service as ds_mod

    created = []

    class _Svc:
        def __init__(self, _app):
            created.append("new")

        def apply_config(self):
            created.append("apply_config")

    monkeypatch.setattr(ds_mod, "DivinationService", _Svc)
    _freeze_all_but("divination")
    app_mod, shell = _shell(config=_Cfg(divination_enabled=True), divination_service=None)
    app_mod.AppShell._sync_divination_service(shell)
    assert created == []
    assert shell.divination_service is None


def test_divination_sync_inactive_stops_service_with_generation_guard():
    """已建的服务必须走 ``shutdown()``（停跨天定时器 + 代次作废在飞闭包），不是丢对象。"""
    events = []

    class _Svc:
        def shutdown(self):
            events.append("shutdown")

    _freeze_all_but("divination")
    app_mod, shell = _shell(
        config=_Cfg(divination_enabled=True), divination_service=_Svc())
    app_mod.AppShell._sync_divination_service(shell)
    assert events == ["shutdown"]
    assert shell.divination_service is None


def test_divination_draw_inactive_returns_before_lazy_create(monkeypatch):
    """菜单落点兜底：本方法会懒创建服务 + apply_config，闸必须在其之前。"""
    import pet.divination_service as ds_mod

    created = []
    bubbles = []

    class _Svc:
        def __init__(self, _app):
            created.append("new")

    class _Win:
        def show_bubble(self, *_args, **_kwargs):
            bubbles.append("bubble")

    monkeypatch.setattr(ds_mod, "DivinationService", _Svc)
    _freeze_all_but("divination")
    app_mod, shell = _shell(
        config=_Cfg(divination_enabled=True), divination_service=None, win=_Win())
    app_mod.AppShell.trigger_divination_draw(shell)
    assert created == []
    assert shell.divination_service is None
    # 也不冒「去设置里打开」的提示：那是行为开关层的文案，模块层拒绝时无落点可指。
    assert bubbles == []


def test_divination_draw_active_lazy_creates_service(monkeypatch):
    import pet.divination_service as ds_mod

    calls = []

    class _Svc:
        def __init__(self, _app):
            calls.append("new")

        def apply_config(self):
            calls.append("apply_config")

        def draw_now(self):
            calls.append("draw_now")
            return {"quote": {}, "newly": False}

    monkeypatch.setattr(ds_mod, "DivinationService", _Svc)
    fa.freeze_snapshot_for_tests(["divination"])
    app_mod, shell = _shell(config=_Cfg(divination_enabled=True), divination_service=None)
    app_mod.AppShell.trigger_divination_draw(shell)
    assert calls.count("new") == 1
    assert "draw_now" in calls
    assert isinstance(shell.divination_service, _Svc)


def test_todo_sync_inactive_creates_no_service(monkeypatch):
    import pet.app as app_mod

    created = []

    class _Svc:
        def __init__(self, _app):
            created.append("new")

    monkeypatch.setattr(app_mod, "TodoReminderService", _Svc)
    _freeze_all_but("todo")
    app_mod, shell = _shell(
        config=_Cfg(todo_reminder_enabled=True), todo_service=None, todo_panel=None)
    app_mod.AppShell._sync_todo_service(shell)
    assert created == []
    assert shell.todo_service is None


def test_todo_sync_inactive_stops_service_and_frees_it():
    events = []

    class _Svc:
        def stop(self):
            events.append("stop")

    _freeze_all_but("todo")
    app_mod, shell = _shell(
        config=_Cfg(todo_reminder_enabled=True), todo_service=_Svc(), todo_panel=None)
    app_mod.AppShell._sync_todo_service(shell)
    assert events == ["stop"]
    assert shell.todo_service is None


def test_open_todo_panel_inactive_refuses_before_lazy_create(monkeypatch):
    """面板打开即懒创建服务（「总开关关着也要服务对象」）：模块闸必须在它之前。"""
    import pet.app as app_mod

    created = []

    class _Svc:
        def __init__(self, _app):
            created.append("new")

    monkeypatch.setattr(app_mod, "TodoReminderService", _Svc)
    _freeze_all_but("todo")
    app_mod, shell = _shell(config=_Cfg(), todo_service=None, todo_panel=None)
    app_mod.AppShell.open_todo_panel(shell)
    assert created == []
    assert shell.todo_service is None
    assert shell.todo_panel is None


def test_todo_sync_active_lazy_creates_and_starts_service(monkeypatch):
    import pet.app as app_mod

    events = []

    class _Svc:
        _timer = None

        def __init__(self, _app):
            events.append("new")

        def start(self):
            events.append("start")

        def apply_config(self):
            events.append("apply_config")

    monkeypatch.setattr(app_mod, "TodoReminderService", _Svc)
    fa.freeze_snapshot_for_tests(["todo"])
    app_mod, shell = _shell(
        config=_Cfg(todo_reminder_enabled=True), todo_service=None, todo_panel=None)
    app_mod.AppShell._sync_todo_service(shell)
    assert events == ["new", "start"]
    assert isinstance(shell.todo_service, _Svc)


def _install_festival_fake(monkeypatch, events, *, running=False):
    """把 ``FestivalReminderService`` 换成记录器（模块内惰性 import，故打模块属性）。"""
    import pet.festival_service as fs_mod

    class _Svc:
        def __init__(self, _app):
            events.append("new")

        def is_running(self):
            return running

        def start(self):
            events.append("start")

        def apply_config(self):
            events.append("apply_config")

        def stop(self):
            events.append("stop")

        def remind_now(self):
            events.append("remind_now")

    monkeypatch.setattr(fs_mod, "FestivalReminderService", _Svc)
    return _Svc


def test_festival_sync_inactive_creates_no_service(monkeypatch):
    """未激活：总开关开着也不建服务——它连带整套节日文案表（实测 2.95MB 堆）。"""
    events = []
    _install_festival_fake(monkeypatch, events)
    _freeze_all_but("festival")
    app_mod, shell = _shell(
        config=_Cfg(festival_reminder_enabled=True), festival_service=None)
    shell._sync_chime_service = lambda: None
    assert app_mod.AppShell._festival_wanted(shell) is False
    app_mod.AppShell._sync_festival_service(shell)
    assert events == []
    assert shell.festival_service is None


def test_festival_sync_inactive_stops_service(monkeypatch):
    events = []
    fake_cls = _install_festival_fake(monkeypatch, events)
    _freeze_all_but("festival")
    app_mod, shell = _shell(
        config=_Cfg(festival_reminder_enabled=True), festival_service=fake_cls(None))
    shell._sync_chime_service = lambda: None
    app_mod.AppShell._sync_festival_service(shell)
    assert events == ["new", "stop"]
    assert shell.festival_service is None


def test_trigger_festival_now_inactive_blocks_the_bypass(monkeypatch):
    """本入口明确**绕过提醒总开关**（试听语义），模块闸必须单独挡在这里。"""
    events = []
    _install_festival_fake(monkeypatch, events)
    _freeze_all_but("festival")
    app_mod, shell = _shell(
        config=_Cfg(festival_reminder_enabled=False), festival_service=None)
    app_mod.AppShell.trigger_festival_now(shell)
    assert events == []
    assert shell.festival_service is None


def test_trigger_festival_now_active_lazy_creates_service(monkeypatch):
    events = []
    _install_festival_fake(monkeypatch, events)
    fa.freeze_snapshot_for_tests(["festival"])
    app_mod, shell = _shell(
        config=_Cfg(festival_reminder_enabled=False), festival_service=None)
    app_mod.AppShell.trigger_festival_now(shell)
    assert events == ["new", "remind_now"]


def test_inactive_modules_do_not_keep_the_shared_chime_channel_alive():
    """三个 speak 键都挂在共用报时通道上：模块停用后不许再凭它们把通道拉起来。"""
    app_mod, shell = _shell(config=_Cfg(
        festival_reminder_enabled=True,
        festival_reminder_speak=True,
        todo_reminder_enabled=True,
        todo_reminder_speak=True,
        divination_enabled=True,
        divination_speak=True,
    ))
    _freeze_all_but("festival", "todo", "divination")
    assert app_mod.AppShell._festival_speak_wanted(shell) is False
    assert app_mod.AppShell._todo_speak_wanted(shell) is False
    assert app_mod.AppShell._divination_speak_wanted(shell) is False

    fa.freeze_snapshot_for_tests(["festival", "todo", "divination"])
    assert app_mod.AppShell._festival_speak_wanted(shell) is True
    assert app_mod.AppShell._todo_speak_wanted(shell) is True
    assert app_mod.AppShell._divination_speak_wanted(shell) is True


# ---------------------------------------------------------------- 期 2b：todo/festival 设置层 + 设置进程
def _build_dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = _qapp()
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dlg = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    return app, dlg


def test_todo_group_unmounted_when_inactive(tmp_path, monkeypatch):
    _freeze_all_but("todo")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        from pet.modern_settings_dialog import SettingRow

        row = dlg.findChild(SettingRow, "settingRow_todo_reminder_enabled")
        assert row is not None  # 控件保留（重新激活原样回来）
        pages = [dlg.pages.widget(i) for i in range(dlg.pages.count())]
        assert not any(page.isAncestorOf(row) for page in pages)  # 但不挂在任何域页
        from PySide6.QtWidgets import QLabel

        labels = [lb.text() for lb in dlg.findChildren(QLabel)]
        assert "待分类（开发期）" not in labels
        # 不写回
        writes = []
        orig_set = dlg.config.set
        monkeypatch.setattr(dlg.config, "set",
                            lambda k, v: (writes.append(k), orig_set(k, v))[1])
        assert dlg._write_config()
        assert not [k for k in writes if k.startswith("todo_reminder")]
    finally:
        dlg.close()
        app.processEvents()


def test_todo_group_mounted_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        from pet.modern_settings_dialog import SettingRow

        row = dlg.findChild(SettingRow, "settingRow_todo_reminder_enabled")
        pages = [dlg.pages.widget(i) for i in range(dlg.pages.count())]
        assert any(page.isAncestorOf(row) for page in pages)
    finally:
        dlg.close()
        app.processEvents()


def test_festival_page_not_constructed_when_inactive(tmp_path, monkeypatch):
    _freeze_all_but("festival")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert dlg.festival_page is None
        assert dlg._write_config()  # 不碰不存在的页，保存照常
    finally:
        dlg.close()
        app.processEvents()


def test_festival_page_constructed_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert dlg.festival_page is not None
    finally:
        dlg.close()
        app.processEvents()


def test_freeze_for_settings_process_reads_global_config(tmp_path):
    """设置进程：按主 config.json 的待生效集合冻结（slot 实例配置也读主文件）。"""
    import json

    from pet.config import Config

    main_cfg = Config(tmp_path)
    assert fa.write_enabled(main_cfg, ["weather", "chat"])
    # 主实例设置进程
    fa.freeze_for_settings_process(main_cfg)
    assert fa.is_active("weather") is True
    assert fa.is_active("todo") is False
    # slot 实例设置进程（全局键真值在主文件）
    fa.reset_snapshot_for_tests()
    slot_cfg = Config(tmp_path, instance_id="slot-3")
    fa.freeze_for_settings_process(slot_cfg)
    assert fa.is_active("weather") is True
    assert fa.is_active("todo") is False
    # 未判定的安装：基线（全激活）
    fa.reset_snapshot_for_tests()
    raw = json.loads(main_cfg.path.read_text(encoding="utf-8"))
    raw.pop("feature_activation")
    main_cfg.path.write_text(json.dumps(raw), encoding="utf-8")
    fa.freeze_for_settings_process(main_cfg)
    assert all(fa.is_active(fid) for fid in FEATURES)


# ---------------------------------------------------------------- 期 3a：voice 模块
def _voice_shell(config):
    """裸 AppShell（不构造）：方法解析走类，属性只有 config。"""
    import pet.app as app_mod

    shell = object.__new__(app_mod.AppShell)
    shell.config = config
    return shell


def test_chime_wanted_off_when_voice_inactive(tmp_path):
    import pet.app as app_mod
    from pet.config import Config

    cfg = Config(tmp_path)
    cfg.set("voice_chime_enabled", True)
    shell = _voice_shell(cfg)
    fa.freeze_snapshot_for_tests([fid for fid in MIGRATION_BASELINE if fid != "voice"])
    assert app_mod.AppShell._chime_wanted(shell) is False
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    assert app_mod.AppShell._chime_wanted(shell) is True


def test_ensure_audio_channel_returns_none_when_voice_inactive(tmp_path):
    import pet.app as app_mod
    from pet.config import Config

    _freeze_all_but("voice")
    shell = _voice_shell(Config(tmp_path))
    assert app_mod.AppShell.ensure_audio_channel(shell) is None


def test_self_talk_speak_wanted_off_when_voice_inactive(tmp_path, monkeypatch):
    import pet.app as app_mod
    from pet.config import Config

    class _Cfg:
        def get(self, key, default=None):
            return True  # 两键都开（仅本测试的鸭子视图）

    shell = _voice_shell(Config(tmp_path))
    monkeypatch.setattr(app_mod.AppShell, "_self_talk_voice_configs",
                        lambda _self: [_Cfg()])
    _freeze_all_but("voice")
    assert app_mod.AppShell._self_talk_speak_wanted(shell) is False
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    assert app_mod.AppShell._self_talk_speak_wanted(shell) is True


def test_precache_not_started_when_voice_inactive(tmp_path, monkeypatch):
    import pet.app as app_mod
    from pet.config import Config
    from pet import self_talk_voice

    monkeypatch.setattr(self_talk_voice, "enabled", lambda _cfg: True)
    started = []
    monkeypatch.setattr(self_talk_voice, "start_precache",
                        lambda *a, **k: started.append(1) or True)
    shell = _voice_shell(Config(tmp_path))
    _freeze_all_but("voice")
    assert app_mod.AppShell.precache_self_talk_voice(shell, "test") is False
    assert started == []


def test_voice_settings_pages_absent_when_inactive(tmp_path, monkeypatch):
    _freeze_all_but("voice", "festival")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert dlg.voice_chime_page is None
        assert dlg.festival_page is None
        # 语音域整域隐藏
        labels = [dlg.sidebar.item(i).text() for i in range(dlg.sidebar.count())]
        assert "语音" not in labels
        # 朗读两行不出现，核心行在
        from pet.modern_settings_dialog import SettingRow

        assert dlg.findChild(SettingRow, "settingRow_click_self_talk") is not None
        pages = [dlg.pages.widget(i) for i in range(dlg.pages.count())]
        for key in ("click_self_talk_speak", "click_self_talk_precache", "chat_reply_voice_enabled"):
            row = dlg.findChild(SettingRow, f"settingRow_{key}")
            if row is not None:
                assert not any(page.isAncestorOf(row) for page in pages), key
        # 保存不写回这两键
        writes = []
        orig_set = dlg.config.set
        monkeypatch.setattr(dlg.config, "set",
                            lambda k, v: (writes.append(k), orig_set(k, v))[1])
        assert dlg._write_config()
        assert "self_talk_speak_enabled" not in writes
        assert "self_talk_voice_precache_enabled" not in writes
    finally:
        dlg.close()
        app.processEvents()


def test_voice_domain_present_when_only_festival_off(tmp_path, monkeypatch):
    """语音开 + 节日关：语音域在，且只有语音报时组。"""
    _freeze_all_but("festival")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        labels = [dlg.sidebar.item(i).text() for i in range(dlg.sidebar.count())]
        assert "语音" in labels
        assert dlg.voice_chime_page is not None
        assert dlg.festival_page is None
    finally:
        dlg.close()
        app.processEvents()


# ---------------------------------------------------------------- 期 3b：music 模块
_MUSIC_ACTIONS = (
    "music_pause",
    "music_next",
    "music_prev",
    "music_quit",
    "music_lyric_align",
    "music_open_netease",
    "music_open_qqmusic",
    "music_open_kugou",
    "music_open_soda",
)


class _MusicPet:
    """菜单投影用的最小宿主：歌词开关开着，九条音乐动作因此都进入可用集。"""

    class _Cfg:
        def get(self, key, default=None):
            if key == "music_lyric_enabled":
                return True
            return default

    cfg = _Cfg()

    def __getattr__(self, name):
        if name.startswith("on_"):
            return lambda *a, **k: None
        raise AttributeError(name)


def _cfg_obj(**values):
    """只实现 ``get`` 的配置替身（执行层门控不碰配置写回）。"""

    class _Cfg:
        def get(self, key, default=None):
            return values.get(key, default)

    return _Cfg()


def _default_template():
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).resolve().parent.parent / "pet/menu_templates/modern-default-v1.json")
        .read_text(encoding="utf-8")
    )


def test_music_menu_action_ids_match_registry_and_template():
    """features.py 的动作清单 == 注册表里的音乐动作 == 默认模板的叶子。

    菜单投影按 ``feature_for_action`` 反查模块，三者一旦漂移就会出现「模块停了
    但某条动作还在菜单里」——这条用例就是那份数据的对账（本次核对结果：对得上）。
    """
    from pet.context_menus.registry import MENU_ACTIONS
    from pet.features import feature_for_action

    assert set(FEATURES["music"].menu_action_ids) == set(_MUSIC_ACTIONS)
    for action_id in _MUSIC_ACTIONS:
        assert action_id in MENU_ACTIONS.ids, action_id
        assert feature_for_action(action_id) == "music", action_id
    music_nodes = [n for n in _default_template()["nodes"] if n.get("id") == "music"]
    assert music_nodes, "默认布局里的「音乐」子菜单找不到"
    leaves = {c["id"] for c in music_nodes[0]["children"] if c.get("type") == "action"}
    assert leaves == set(_MUSIC_ACTIONS)


def test_projection_hides_music_menu_when_inactive():
    from pet.context_menus.registry import MENU_ACTIONS

    pet = _MusicPet()
    assert set(_MUSIC_ACTIONS) <= MENU_ACTIONS.available_ids(pet)  # 未冻结：全在
    _freeze_all_but("music")
    ids = MENU_ACTIONS.available_ids(pet)
    assert not (set(_MUSIC_ACTIONS) & ids)
    assert "modern_settings" in ids and "quit" in ids  # 核心动作不受影响


def test_default_layout_drops_music_submenu_when_inactive():
    """布局解析：九条动作被投影剔除后「音乐」子菜单整体消失（不写回布局）。"""
    from pet.context_menus.registry import MENU_ACTIONS
    from pet.menu_layout import resolve_menu_layout

    template = _default_template()
    _freeze_all_but("music")
    result = resolve_menu_layout(
        template,
        registered_actions=MENU_ACTIONS.ids,
        available_actions=MENU_ACTIONS.available_ids(_MusicPet()),
    )

    def _ids(nodes):
        for node in nodes:
            yield node.get("id")
            yield from _ids(node.get("children", ()))

    flat = list(_ids(result.nodes))
    assert "music" not in flat
    assert not (set(_MUSIC_ACTIONS) & set(flat))
    assert "modern_settings" in flat
    # 写回禁令：传进去的布局原样（模板文件本身也不被改）
    assert any(n.get("id") == "music" for n in template["nodes"])


def test_music_sing_polling_not_started_when_inactive():
    """唱歌轮询（legacy 与 overlay 共用这一面）：模块未激活不起表、退出唱歌态。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget

    from pet import window_alerts

    _qapp()

    class _Host(QWidget):
        _music_sing_enabled = True
        _music_sing_active = True
        _music_sing_silent_since = 1.0
        cfg = _cfg_obj()

        def __init__(self):
            super().__init__()
            self._music_sing_timer = QTimer(self)
            self._music_sing_timer.setInterval(1000)

        def isVisible(self):
            return True

        def _check_music_sing(self):
            pass

    host = _Host()
    _freeze_all_but("music")
    window_alerts.start_music_sing_polling(host)
    assert host._music_sing_timer.isActive() is False
    window_alerts.check_music_sing(host)
    assert host._music_sing_active is False  # 停用即退出唱歌态

    alive = _Host()
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)  # 未冻结/全激活：照旧
    window_alerts.start_music_sing_polling(alive)
    assert alive._music_sing_timer.isActive() is True
    alive._music_sing_timer.stop()


def test_check_music_sing_skips_audio_probe_when_inactive(monkeypatch):
    """停用后不再每秒调 pycaw COM（也不拉 SMTC 探针线程）。"""
    from pet import music_detect, window_alerts

    _qapp()
    calls = []
    monkeypatch.setattr(music_detect, "is_music_playing",
                        lambda: calls.append(1) or True)

    class _Host:
        _music_sing_enabled = True
        _music_sing_active = False
        _music_sing_silent_since = None
        _dragging = False
        _instrumental_playing = False
        cfg = _cfg_obj()

        def isVisible(self):
            return True

        def _is_one_shot_playing(self):
            return False

        def _switch(self, _name):
            raise AssertionError("停用后不许切唱歌动画")

    _freeze_all_but("music")
    window_alerts.check_music_sing(_Host())
    assert calls == []


def test_overlay_music_sing_timer_not_started_when_inactive():
    """overlay 拓扑：构造期不直接起表（它绕过了 start_music_sing_polling）。"""
    from PySide6.QtWidgets import QWidget

    from pet.overlay_shell import OverlayShell

    _qapp()

    class _Host(QWidget):
        def _check_music_sing(self):
            pass

        def isVisible(self):
            return True

    def _build(**cfg):
        host = _Host()
        host._config = _cfg_obj(**cfg)
        OverlayShell._init_music_sing(host)
        return host

    _freeze_all_but("music")
    off = _build(music_sing_enabled=True)
    assert off._music_sing_timer.isActive() is False
    OverlayShell.sync_music_sing(off)  # 保存后的同步也不许起表
    assert off._music_sing_timer.isActive() is False

    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)  # 未冻结/全激活：照旧
    on = _build(music_sing_enabled=True)
    assert on._music_sing_timer.isActive() is True
    on._music_sing_timer.stop()


def test_lyric_controller_not_installed_when_inactive(monkeypatch):
    """两条链（legacy mixin / overlay 壳）都不构造歌词控制器。"""
    from PySide6.QtWidgets import QWidget

    from pet import music_lyric_controller as mlc_mod
    from pet.overlay_shell import OverlayShell
    from pet.window_optional_services import WindowFeatureGateMixin

    _qapp()
    created = []

    class _FakeController:
        def __init__(self, win):
            created.append(win)

        def shutdown(self):
            return None

    monkeypatch.setattr(mlc_mod, "MusicLyricController", _FakeController)

    class _Host(QWidget):
        _music_lyric = None
        cfg = _cfg_obj(music_lyric_enabled=True)

    _freeze_all_but("music")
    assert WindowFeatureGateMixin.install_music_lyric(_Host()) is None
    assert OverlayShell.install_music_lyric(_Host()) is None
    assert created == []

    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)  # 未冻结/全激活：照旧装配
    assert WindowFeatureGateMixin.install_music_lyric(_Host()) is not None
    assert created


def test_lyric_controller_shutdown_and_dropped_when_inactive():
    """模块停用时已建的控制器走既有 shutdown 收口并置 None。"""
    from PySide6.QtWidgets import QWidget

    from pet.overlay_shell import OverlayShell
    from pet.window_optional_services import WindowFeatureGateMixin

    _qapp()

    class _FakeController:
        def __init__(self):
            self.shutdowns = 0

        def shutdown(self):
            self.shutdowns += 1

    class _MixinHost(QWidget, WindowFeatureGateMixin):
        def __init__(self):
            super().__init__()
            self._music_lyric = _FakeController()
            self.cfg = _cfg_obj(music_lyric_enabled=True)

    class _OverlayHost(QWidget):
        # overlay 壳的收口方法只读 ``_music_lyric``，可借其未绑定函数
        shutdown_music_lyric = OverlayShell.shutdown_music_lyric

        def __init__(self):
            super().__init__()
            self._music_lyric = _FakeController()
            self.cfg = _cfg_obj(music_lyric_enabled=True)

    _freeze_all_but("music")
    pairs = (
        (WindowFeatureGateMixin.sync_music_lyric, _MixinHost),
        (OverlayShell.sync_music_lyric, _OverlayHost),
    )
    for sync, host_cls in pairs:
        host = host_cls()
        controller = host._music_lyric
        sync(host)
        assert controller.shutdowns == 1
        assert host._music_lyric is None


def test_music_player_warm_not_scheduled_when_inactive(monkeypatch):
    """启动期的播放器路径浅扫（app.py 的延迟预热）不登记。"""
    import pet.app as app_mod

    scheduled = []

    class _Timer:
        @staticmethod
        def singleShot(ms, fn):
            scheduled.append((ms, fn))

    monkeypatch.setattr(app_mod, "QTimer", _Timer)
    _freeze_all_but("music")
    app_mod._schedule_music_player_warm()
    assert scheduled == []
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    app_mod._schedule_music_player_warm()
    assert scheduled and scheduled[0][1] is app_mod._warm_music_player_paths


def test_music_menu_callbacks_early_return_when_inactive(monkeypatch):
    """绕过菜单直达回调：不装控制器、不起线程、不读路径缓存。"""
    from PySide6.QtWidgets import QMenu

    from pet import music_players
    from pet.context_menus import shared as shared_mod

    _qapp()
    threads = []

    class _Thread:
        def __init__(self, target=None, name=None, daemon=None):
            threads.append(name)

        def start(self):
            raise AssertionError("模块停用后不许起后台线程")

    class _ThreadingShim:
        Thread = _Thread
        Event = shared_mod.threading.Event

    monkeypatch.setattr(shared_mod, "threading", _ThreadingShim)
    warmed = []
    monkeypatch.setattr(music_players, "warm_cache_async",
                        lambda *a, **k: warmed.append(a) or False)
    monkeypatch.setattr(music_players, "cached_player",
                        lambda *a, **k: (music_players.CACHED_COLD, ""))

    class _FakeController:
        def __init__(self):
            self.aligned = []

        def skip_track(self, _direction):
            raise AssertionError("模块停用后不许调后台媒体控制")

        def resync_to_line(self, step):
            self.aligned.append(step)
            return True

        def music_mode_active(self):
            return True

        def set_music_mode_enabled(self, _on):
            raise AssertionError("模块停用后不许改音乐模式")

    class _Pet:
        cfg = _cfg_obj(music_lyric_enabled=True)

        def __init__(self):
            self._music_lyric = _FakeController()
            self.installs = 0

        def install_music_lyric(self):
            self.installs += 1
            raise AssertionError("模块停用后不许懒装控制器")

    pet = _Pet()
    _freeze_all_but("music")
    shared_mod._launch_player_and_play("netease", pet)
    shared_mod.set_music_mode(pet, True)
    assert shared_mod._align_lyric(pet, "next") is False
    assert shared_mod._skip_track(pet, "next") is False
    assert pet._music_lyric.aligned == []
    assert pet.installs == 0
    ran = []
    shared_mod._run_music_off_main(lambda: ran.append(1))
    assert ran == []
    menu = QMenu()
    try:
        assert shared_mod._music_player_builder("netease")(menu, pet) is None
    finally:
        menu.deleteLater()
    assert threads == []  # 一条后台线程都没起
    assert warmed == []  # 也没起目录浅扫


def test_music_player_detect_no_scan_when_inactive():
    """设置页「自动检测」：停用后不清缓存、不起扫描、不起轮询表。"""
    from pet import settings_music

    calls = []

    class _Dialog:
        pass

    _freeze_all_but("music")
    settings_music.start_detect(
        _Dialog(),
        warm=lambda *a, **k: calls.append(("warm", a)),
        clear=lambda: calls.append(("clear",)),
    )
    assert calls == []


def _row_mounted(dlg, key: str) -> bool:
    from pet.modern_settings_dialog import SettingRow

    row = dlg.findChild(SettingRow, f"settingRow_{key}")
    if row is None:
        return False
    pages = [dlg.pages.widget(i) for i in range(dlg.pages.count())]
    return any(page.isAncestorOf(row) for page in pages)


def _domain_page_labels(dlg) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [
        label.text()
        for index in range(dlg.pages.count())
        for label in dlg.pages.widget(index).findChildren(QLabel)
    ]


def test_music_settings_groups_unmounted_when_inactive(tmp_path, monkeypatch):
    """「音乐关联」整组与「播放器路径…（高级）」不挂出，核心组照旧。"""
    _freeze_all_but("music")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        for key in ("music_sing", "music_lyric", "music_lyric_lead",
                    "foobar_title_format", "music_player_netease", "music_player_detect"):
            assert not _row_mounted(dlg, key), key
        labels = _domain_page_labels(dlg)
        assert "音乐关联" not in labels
        assert "待分类（开发期）" not in labels  # 照常 claim，不掉「待分类」
        # 「显示与音乐」标签仍在（「显示」组属核心，音乐只是页内两组）
        sidebar = [dlg.sidebar.item(i).text() for i in range(dlg.sidebar.count())]
        assert "桌宠" in sidebar
        assert _row_mounted(dlg, "pet_opacity")
    finally:
        dlg.close()
        app.processEvents()


def test_music_settings_groups_mounted_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        for key in ("music_sing", "music_lyric", "music_lyric_lead",
                    "foobar_title_format", "music_player_netease", "music_player_detect"):
            assert _row_mounted(dlg, key), key
        assert "音乐关联" in _domain_page_labels(dlg)
    finally:
        dlg.close()
        app.processEvents()


def test_music_settings_not_written_back_when_inactive(tmp_path, monkeypatch):
    """未挂出的两组：保存不写回（含播放器路径与两个歌词来源开关）。"""
    _freeze_all_but("music")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        writes = []
        orig_set = dlg.config.set
        monkeypatch.setattr(dlg.config, "set",
                            lambda k, v: (writes.append(k), orig_set(k, v))[1])
        assert dlg._write_config()
        assert not [k for k in writes if k.startswith(("music_", "foobar_"))]
    finally:
        dlg.close()
        app.processEvents()


# ---------------------------------------------------------------- 期 4a：chat 单源复合 + harness 解耦
def test_chat_module_off_disables_enable_chat(tmp_path):
    """AppShell 构造：enable_chat = 构建能力 ∧ chat 模块激活（单源复合）。"""
    import pet.app as app_mod
    from pet.config import Config

    app = _qapp()
    _freeze_all_but("chat")
    shell = app_mod.AppShell(app, Config(tmp_path), enable_chat=True, slot_id=0)
    assert shell.enable_chat is False
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    shell2 = app_mod.AppShell(app, Config(tmp_path), enable_chat=True, slot_id=0)
    assert shell2.enable_chat is True
    # 构建能力缺失（no-chat）仍然 False（不被模块激活救回）
    shell3 = app_mod.AppShell(app, Config(tmp_path), enable_chat=False, slot_id=0)
    assert shell3.enable_chat is False


def test_harness_action_available_without_chat_callback():
    """harness 解耦：chat 运行回调缺席（模块关）时仍可用；构建变体缺失才隐藏。"""
    from pet.context_menus.registry import MENU_ACTIONS

    class _NoChatPet(_FakePet):
        on_open_chat = None

    ids = MENU_ACTIONS.available_ids(_NoChatPet())
    assert "harness" in ids
    assert "chat" not in ids  # chat 自己的可用性仍跟回调走

    class _NoChatBuildPet(_NoChatPet):
        chat_build_capable = False  # no-chat 打包变体（既有语义：不出场）

    assert "harness" not in MENU_ACTIONS.available_ids(_NoChatBuildPet())


def test_harness_autostart_follows_system_tools_not_chat(tmp_path, monkeypatch):
    import pet.app as app_mod
    from pet.config import Config

    cfg = Config(tmp_path)
    cfg.set("harness_autostart", True)
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg
    monkeypatch.setattr(app_mod.AppShell, "_dsh_tracker_wanted", lambda _s: True)
    # chat 开、system_tools 关：不自启
    fa.freeze_snapshot_for_tests([fid for fid in MIGRATION_BASELINE if fid != "system_tools"])
    assert app_mod.AppShell._harness_autostart_wanted(shell) is False
    # 全开：自启
    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    assert app_mod.AppShell._harness_autostart_wanted(shell) is True


# ------------------------------- 期 4c：dynamic_island / agent_link / 工具模块
class _SignalStub:
    """岛替身的「信号」：既能被 connect，也能被当函数调用。"""

    def connect(self, *_a, **_k):
        return None

    def __call__(self, *_a, **_k):
        return None


class _IslandStub:
    """``DynamicIsland`` 替身：其余方法一律吞掉（信号属性给出 ``_SignalStub``）。"""

    _SIGNALS = frozenset({
        "clicked", "toggle_pet_requested", "open_chat_requested",
        "open_settings_requested", "chat_requested", "card_expanded",
    })

    def __init__(self, cfg):
        self.cfg = cfg
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name in self._SIGNALS:
            return _SignalStub()

        def _call(*_a, **_k):
            self.calls.append(name)

        return _call


class _RecordingIsland:
    """只记录方法名的岛替身（``_quiet_balance_refresh`` 的落点是 set_balance_info）。"""

    def __init__(self):
        self.calls: list[str] = []

    def __getattr__(self, name):
        def _call(*_a, **_k):
            self.calls.append(name)

        return _call


def _write_keys(dlg, monkeypatch) -> list[str]:
    """把 ``dlg.config.set`` 换成记录器：返回的列表在 ``_write_config`` 后即写回键集。"""
    keys: list[str] = []
    orig_set = dlg.config.set

    def _set(key, value):
        keys.append(key)
        return orig_set(key, value)

    monkeypatch.setattr(dlg.config, "set", _set)
    return keys


def _domain_tab_labels(dlg, domain_label: str) -> list[str]:
    from pet.settings_widgets import SettingsTabContainer

    page = next(
        dlg.pages.widget(i)
        for i in range(dlg.pages.count())
        if dlg.sidebar.item(i).text() == domain_label
    )
    tabs = page.findChild(SettingsTabContainer)
    return list(tabs.labels())


def _domain_labels(dlg, domain_label: str) -> list[str]:
    """某个域页内的全部 QLabel 文本（只看该域；功能域卡片里会出现模块名）。"""
    from PySide6.QtWidgets import QLabel

    page = next(
        dlg.pages.widget(i)
        for i in range(dlg.pages.count())
        if dlg.sidebar.item(i).text() == domain_label
    )
    return [label.text() for label in page.findChildren(QLabel)]


def _widget_mounted(dlg, widget) -> bool:
    pages = [dlg.pages.widget(i) for i in range(dlg.pages.count())]
    return any(page.isAncestorOf(widget) for page in pages)


def _sidebar_labels(dlg) -> list[str]:
    return [dlg.sidebar.item(i).text() for i in range(dlg.sidebar.count())]


def test_island_module_off_never_creates_the_island(tmp_path, monkeypatch):
    """执行层：岛开关开着、模块关着 → 岛**不创建**（不是建好再 hide）。

    「建好再 hide()」那条路径保留岛对象、四路采样槽与 FPS 订阅（``FpsHub``
    attach 只发生在 ``DynamicIsland`` 内部），所以停用必须落在构造之前。
    """
    import pet.app as app_mod
    import pet.dynamic_island as island_mod
    from pet.chat.service import ChatService
    from pet.config import Config

    monkeypatch.setattr(island_mod, "DynamicIsland", _IslandStub)
    monkeypatch.setattr(app_mod.AppShell, "_sync_island_collision", lambda _s, _cfg: None)
    # 全局聊天完成订阅是进程级表：测试里别把裸壳挂进去
    monkeypatch.setattr(ChatService, "register_global_finished",
                        classmethod(lambda _cls, _cb: None))
    cfg = Config(tmp_path)
    cfg.set("dynamic_island", {"enabled": True})
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg
    shell.island = None
    shell.island_collision = None
    shell._instances = []

    _freeze_all_but("dynamic_island")
    app_mod.AppShell._sync_dynamic_island(shell)
    assert shell.island is None

    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    app_mod.AppShell._sync_dynamic_island(shell)
    assert isinstance(shell.island, _IslandStub)  # 模块激活时照旧创建（不是"永远不造"）


def test_island_interactive_follows_the_module_gate(tmp_path):
    """``_island_interactive`` 是岛可用的单一口径：模块未激活恒 False。"""
    from PySide6.QtWidgets import QWidget

    import pet.app as app_mod
    from pet.config import Config

    app = _qapp()
    cfg = Config(tmp_path)
    cfg.set("dynamic_island", {"enabled": True})
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg
    island = QWidget()
    shell.island = island
    try:
        island.show()
        _freeze_all_but("dynamic_island")
        assert app_mod.AppShell._island_interactive(shell) is False
        fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
        assert app_mod.AppShell._island_interactive(shell) is True
    finally:
        island.close()
        island.deleteLater()
        app.processEvents()


def test_balance_refresh_timer_off_when_island_inactive(tmp_path):
    from PySide6.QtCore import QTimer

    import pet.app as app_mod
    from pet.config import Config

    cfg = Config(tmp_path)
    cfg.set("balance_refresh_minutes", 5)
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg
    shell._balance_timer = QTimer()
    try:
        _freeze_all_but("dynamic_island")
        app_mod.AppShell._apply_balance_timer(shell)
        assert shell._balance_timer.isActive() is False
        fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
        app_mod.AppShell._apply_balance_timer(shell)
        assert shell._balance_timer.isActive() is True
    finally:
        shell._balance_timer.stop()


def test_island_balance_entry_points_blocked_when_inactive(tmp_path):
    """两条绕过菜单的直达回调：模块未激活时在读配置/起线程之前返回。

    ``show_balance`` 漏拦会当场读 ``self.win``（裸壳没有该属性）；静默刷新漏拦
    会先读 ``chat_settings()`` 再走到 ``island.set_balance_info`` 与
    ``pet-balance-quiet`` 线程。
    """
    import pet.app as app_mod
    from pet.config import Config

    cfg = Config(tmp_path)
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg
    island = _RecordingIsland()
    shell.island = island
    _freeze_all_but("dynamic_island")
    app_mod.AppShell.show_balance(shell)
    app_mod.AppShell._quiet_balance_refresh(shell)
    assert island.calls == []
    assert getattr(shell, "_quiet_balance_busy", False) is False


def test_agent_link_module_off_stops_dsh_tracker_and_harness_autostart(tmp_path):
    """``_dsh_tracker_wanted`` 是 DSH 的单一口径：模块停用后连带 harness 不自启。"""
    import pet.app as app_mod
    from pet.config import Config

    cfg = Config(tmp_path)
    cfg.set("agent_link", {"dsh": True})
    cfg.set("harness_autostart", True)
    shell = object.__new__(app_mod.AppShell)
    shell.config = cfg

    _freeze_all_but("agent_link")
    assert app_mod.AppShell._dsh_tracker_wanted(shell) is False
    # system_tools 与 harness_autostart 都开着，但 dsh 联动不存在 → 不自启
    assert app_mod.AppShell._harness_autostart_wanted(shell) is False

    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    assert app_mod.AppShell._dsh_tracker_wanted(shell) is True
    assert app_mod.AppShell._harness_autostart_wanted(shell) is True


def test_shared_subsystems_skips_agent_link_construction_when_inactive(tmp_path):
    """构造前挡：模块停用时共享容器**不构造** agent_link 管理器。

    ``SharedAgentLinkManager.__init__`` 末尾就是 ``apply_config()``（起监视器
    线程 / DshMonitor），所以闸必须在构造处；None 是既有语义（单窗路径历史上
    就有"没有管理器"这一态），全部消费点按 None 降级。
    """
    import pet.app as app_mod
    from pet.config import Config

    app = _qapp()
    _freeze_all_but("agent_link")
    shell = app_mod.AppShell(app, Config(tmp_path), enable_chat=True, slot_id=0)
    assert shell._shared is not None
    assert shell._shared.agent_link is None
    assert shell._shared.proactive is not None  # proactive 那一半不受本模块影响

    fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
    shell2 = app_mod.AppShell(app, Config(tmp_path), enable_chat=True, slot_id=0)
    assert shell2._shared.agent_link is not None


def test_island_settings_domain_absent_when_inactive(tmp_path, monkeypatch):
    """设置层：桌面组件域整域消失（岛行 + 指标行都不挂出），其键不写回。"""
    _freeze_all_but("dynamic_island")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert "桌面组件" not in _sidebar_labels(dlg)
        for key in ("dynamic_island_enabled", "dynamic_island_info", "island_network",
                    "island_fps", "network_probe_interval", "game_fps_target_mode"):
            assert not _row_mounted(dlg, key), key
        assert "待分类（开发期）" not in _domain_page_labels(dlg)

        writes = _write_keys(dlg, monkeypatch)
        assert dlg._write_config()
        assert not [k for k in writes
                    if k.startswith(("dynamic_island", "island_", "network_probe",
                                     "game_fps"))]
        # 菜单域那一行不受岛门控（归属见 settings_network 模块 docstring），照常写回
        assert "network_info_menu_enabled" in writes
    finally:
        dlg.close()
        app.processEvents()


def test_island_settings_domain_present_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert "桌面组件" in _sidebar_labels(dlg)
        for key in ("dynamic_island_enabled", "island_network", "island_fps"):
            assert _row_mounted(dlg, key), key
    finally:
        dlg.close()
        app.processEvents()


def test_agent_link_box_unmounted_when_inactive(tmp_path, monkeypatch):
    """设置层：「Agent 联动」折叠框与「消费统计」组不挂出，其键不写回。"""
    _freeze_all_but("agent_link")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        for key in ("agent_sound_enabled", "agent_sound_start", "agent_sound_volume",
                    "agent_cost"):
            assert not _row_mounted(dlg, key), key
        labels = _domain_labels(dlg, "自动化与联动")
        assert "消费统计" not in labels
        assert not _widget_mounted(dlg, dlg.agent_link_box)  # 折叠框不挂出（控件保留）
        assert "待分类（开发期）" not in labels  # 照常 claim，不掉「待分类」

        writes = _write_keys(dlg, monkeypatch)
        assert dlg._write_config()
        assert "agent_link" not in writes
        assert not [k for k in writes if k.startswith(("agent_sound", "agent_cost"))]
    finally:
        dlg.close()
        app.processEvents()


def test_agent_link_box_mounted_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        for key in ("agent_sound_enabled", "agent_cost"):
            assert _row_mounted(dlg, key), key
        labels = _domain_labels(dlg, "自动化与联动")
        assert "消费统计" in labels
        assert _widget_mounted(dlg, dlg.agent_link_box)
    finally:
        dlg.close()
        app.processEvents()


def test_quick_launch_tab_unmounted_when_inactive(tmp_path, monkeypatch):
    """设置层：「菜单 → 快捷启动」标签与编辑器不挂出，quick_launch_apps 不写回。"""
    _freeze_all_but("quick_launch")
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        tabs = _domain_tab_labels(dlg, "菜单")
        assert "快捷启动" not in tabs
        assert "菜单编排" in tabs  # 同域核心标签照旧
        assert not _row_mounted(dlg, "quick_launch_apps")
        assert "待分类（开发期）" not in _domain_page_labels(dlg)

        writes = _write_keys(dlg, monkeypatch)
        assert dlg._write_config()
        assert "quick_launch_apps" not in writes
    finally:
        dlg.close()
        app.processEvents()


def test_quick_launch_tab_present_by_default(tmp_path, monkeypatch):
    app, dlg = _build_dialog(tmp_path, monkeypatch)
    try:
        assert "快捷启动" in _domain_tab_labels(dlg, "菜单")
        assert _row_mounted(dlg, "quick_launch_apps")
    finally:
        dlg.close()
        app.processEvents()


def test_memory_trim_blocked_when_system_tools_inactive(monkeypatch):
    """执行层：菜单投影之外的两条直达路（builder 直调 / 回调直调）都不起回收线程。"""
    from PySide6.QtWidgets import QMenu

    import pet.memory_trim as memory_trim_mod
    from pet.context_menus import shared as menu_shared

    app = _qapp()
    started: list = []
    monkeypatch.setattr(memory_trim_mod, "run_in_background",
                        lambda *_a, **_k: started.append(1))
    monkeypatch.setattr(memory_trim_mod, "is_supported", lambda: True)

    class _Pet:
        cfg = _Cfg(mem_min_size_mb=50.0, mem_skip_foreground=True)

    _freeze_all_but("system_tools")
    menu = QMenu()
    try:
        assert menu_shared.add_memory_trim(menu, _Pet()) is None
        menu_shared.trigger_memory_trim(_Pet())
        assert started == []

        fa.freeze_snapshot_for_tests(MIGRATION_BASELINE)
        assert menu_shared.add_memory_trim(menu, _Pet()) is not None
        menu_shared.trigger_memory_trim(_Pet())
        assert started == [1]
    finally:
        # 被替身的 worker 不会回发 _worker_done，手动摘掉本轮留下的桥
        menu_shared._MEMORY_TRIM_BRIDGES.clear()
        menu.deleteLater()
        app.processEvents()
