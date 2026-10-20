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
