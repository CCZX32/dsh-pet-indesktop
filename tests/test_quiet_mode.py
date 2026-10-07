# -*- coding: utf-8 -*-
"""免打扰（issue #208）聚焦回归：纯状态机 + 抑制真值表 + 菜单 + 设置页。

分成三段，对应三种风险等级：

1. **纯逻辑**（无 Qt）：倒计时/档位/暂存队列/全屏等效——注入假钟，不 sleep、
   不赌真实时序。
2. **抑制真值表**（真实 PetWindow + 真实提醒队列）：免打扰 × 事件类型 × 全屏，
   含"穿透类一律不抑制"与"自言自语/联动气泡不受影响"。
3. **接线**（真实菜单树 / 设置对话框 / 进程级广播 / 真实事件循环）：菜单子菜单
   行为、设置页两行的落位与保存 round trip、``AppShell`` 全屏广播把等效免打扰
   打开、到期后轮询表汇报暂存提醒。
"""

from __future__ import annotations

import time

import pytest

from pet import config as config_mod
from pet import quiet_mode
from pet import window_alerts

pytest.importorskip("PySide6")


class FakeClock:
    """可推进的单调钟（不 sleep：CI 慢 runner 上也不会翻车）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@pytest.fixture(autouse=True)
def _clean_quiet_state():
    """进程级免打扰状态在用例之间必须干净（它是单例）。"""
    quiet_mode.reset_shared_quiet_state()
    yield
    quiet_mode.reset_shared_quiet_state()


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 1. 纯逻辑


@pytest.mark.parametrize(
    "manual,fullscreen,also_on_fullscreen,expected",
    [
        (False, False, True, False),    # 什么都没开
        (False, False, False, False),
        (True, False, True, True),      # 手动免打扰
        (True, False, False, True),     # 手动免打扰与全屏开关无关
        (False, True, True, True),      # 全屏等效（默认开）
        (False, True, False, False),    # 用户关掉全屏联动 → 全屏不抑制
        (True, True, False, True),      # 手动仍在，全屏开关管不着
        (True, True, True, True),
    ],
)
def test_suppression_truth_table(manual, fullscreen, also_on_fullscreen, expected):
    """免打扰 × 全屏 × 配置开关的抑制真值表（唯一判据 suppression_active）。"""
    clock = FakeClock()
    state = quiet_mode.QuietState(clock=clock)
    if manual:
        state.start(15)
    if fullscreen:
        state.set_fullscreen(True)

    assert state.suppression_active(also_on_fullscreen=also_on_fullscreen) is expected


def test_duration_choices_and_remaining_label():
    assert config_mod.QUIET_MINUTE_CHOICES == (15, 30, 60, 120)
    assert config_mod.normalize_quiet_minutes(30) == 30
    assert config_mod.normalize_quiet_minutes(90) == 60      # 非档位取最近档
    assert config_mod.normalize_quiet_minutes("abc") == config_mod.DEFAULT_QUIET_MINUTES
    assert config_mod.normalize_quiet_minutes(-5) == config_mod.DEFAULT_QUIET_MINUTES
    assert quiet_mode.quiet_duration_label(15) == "15 分钟"
    assert quiet_mode.quiet_duration_label(60) == "1 小时"
    assert quiet_mode.format_remaining(754) == "12:34"
    assert quiet_mode.format_remaining(3725) == "1:02:05"
    assert quiet_mode.format_remaining(-3) == "00:00"


def test_expiry_ends_quiet_and_returns_queued_once():
    """到点自动结束：暂存提醒结算一次，第二次结算不再报（幂等，防重复气泡）。"""
    clock = FakeClock()
    state = quiet_mode.QuietState(clock=clock)
    state.start(15)
    state.remember("一条普通提醒")

    assert state.check_end() is None, "仍在免打扰中：不结算"
    assert state.manual_active() is True
    assert state.remaining_label() != "00:00"

    clock.advance(15 * 60)
    assert state.manual_active() is False, "到点即自动结束"
    assert state.check_end() == ["一条普通提醒"]
    assert state.check_end() is None, "同一次结束不得汇报两遍"


def test_early_end_returns_queued_and_is_not_reported_twice():
    clock = FakeClock()
    state = quiet_mode.QuietState(clock=clock)
    state.start(60)
    state.remember("甲")
    state.remember("乙")

    assert state.end_now() == ["甲", "乙"]
    assert state.manual_active() is False
    assert state.check_end() is None, "提前结束已汇报过，轮询表不该再报一遍"


def test_reselecting_duration_restarts_instead_of_stacking():
    clock = FakeClock()
    state = quiet_mode.QuietState(clock=clock)
    state.start(15)
    clock.advance(10 * 60)
    state.start(60)

    assert state.started_minutes() == 60
    assert state.remaining_seconds() == pytest.approx(60 * 60)
    clock.advance(55 * 60)
    assert state.manual_active() is True, "重新计时不得叠成 75 分钟"


def test_queue_limit_drops_oldest():
    state = quiet_mode.QuietState(queue_limit=3)
    for index in range(5):
        state.remember(f"提醒{index}")

    assert state.pending_count() == 3
    assert state.drain() == ["提醒2", "提醒3", "提醒4"], "溢出丢最旧"
    assert state.pending_count() == 0


def test_queue_ignores_blank_text():
    state = quiet_mode.QuietState()
    state.remember("   ")
    state.remember("")
    assert state.pending_count() == 0


def test_fullscreen_exit_ends_quiet_and_reports():
    state = quiet_mode.QuietState(clock=FakeClock())
    state.set_fullscreen(True)
    state.remember("全屏期间的提醒")
    assert state.check_end() is None

    state.set_fullscreen(False)
    assert state.check_end() == ["全屏期间的提醒"]
    assert state.check_end() is None


def test_fullscreen_does_not_queue_when_flag_disabled():
    """``quiet_also_on_fullscreen`` 关掉时全屏不抑制，也就没有暂存与汇报。"""
    state = quiet_mode.QuietState()
    state.set_fullscreen(True)
    assert state.suppression_active(also_on_fullscreen=False) is False
    assert state.check_end(also_on_fullscreen=False) is None


# ---------------------------------------------------------------- 2. 抑制真值表


class RecordingBubble:
    """记录 show_text / dismiss 的假气泡（真实提醒队列需要它）。"""

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Bubble(QObject):
            hidden_signal = Signal()

            def __init__(inner) -> None:
                super().__init__()
                inner.shown: list[dict] = []
                inner.dismiss_calls = 0

            def show_text(inner, text, anchor, duration_ms, *, pet_scale=None,
                          subtitle="", sticky=False, buttons=None,
                          title_first=False, width_locked=False):
                inner.shown.append({
                    "text": str(text), "sticky": bool(sticky),
                    "duration_ms": int(duration_ms), "buttons": buttons,
                    "subtitle": str(subtitle or ""),
                })

            def show_image(inner, *_args, **_kwargs):
                return True

            def reposition(inner, _anchor):
                pass

            def hide(inner):
                pass

            def isVisible(inner):
                return True

            def dismiss(inner):
                inner.dismiss_calls += 1

        self._bubble = _Bubble()

    def __getattr__(self, name):
        return getattr(self._bubble, name)


@pytest.fixture
def win(qapp, tmp_path):
    from tests.pet_window_fakes import make_pet_window

    window = make_pet_window(tmp_path)
    window._speech_bubble = RecordingBubble()
    yield window
    window.close()
    qapp.processEvents()


def _queue(window):
    return list(getattr(window, "_alert_queue", []) or [])


def _shown_texts(window) -> list[str]:
    return [item["text"] for item in window._speech_bubble.shown]


@pytest.mark.parametrize(
    "alert_type,shown_during_quiet",
    [
        ("watchdog", False),        # 普通提醒：卡住 / 硬失败
        ("approval", True),         # 交互应答：压了会出事故
        ("question", True),
        ("interaction", True),
        ("lifecycle", True),
        ("task_complete", True),
        ("execution/failed", True),
        ("agent/request-error", True),
        ("balance", True),
    ],
)
def test_alert_truth_table_by_event_type(win, alert_type, shown_during_quiet):
    quiet_mode.shared_quiet_state().start(15)

    win.show_alert("一条提醒", duration_ms=6000, sticky=False, alert_type=alert_type)

    state = quiet_mode.shared_quiet_state()
    if shown_during_quiet:
        assert win._alert_current is not None, f"{alert_type} 必须穿透"
        assert state.pending_count() == 0
    else:
        assert win._alert_current is None, f"{alert_type} 应被免打扰拦下"
        assert state.pending_count() == 1


def test_interactive_alert_passes_through_with_buttons(win):
    """带按钮的审批（默认 sticky/优先级 0）必须连按钮一起穿透。"""
    quiet_mode.shared_quiet_state().start(15)

    win.show_alert("需要批准", buttons=[("同意", lambda: None), ("拒绝", lambda: None)],
                   sticky=True, alert_type="approval", alert_id="a1", priority=0)

    assert win._alert_current is not None
    assert win._speech_bubble.shown[-1]["buttons"] is not None


def test_fullscreen_equivalent_queues_ordinary_alert(win):
    """全屏等效免打扰（``quiet_also_on_fullscreen`` 默认开）同样暂存普通提醒。"""
    quiet_mode.shared_quiet_state().set_fullscreen(True)

    win.show_alert("硬失败", duration_ms=6000, sticky=False, alert_type="watchdog")

    assert win._alert_current is None
    assert quiet_mode.shared_quiet_state().pending_count() == 1


def test_fullscreen_equivalent_respects_disabled_flag(win):
    win.cfg.set("quiet_also_on_fullscreen", False)
    quiet_mode.shared_quiet_state().set_fullscreen(True)

    win.show_alert("卡住了", duration_ms=6000, sticky=False, alert_type="watchdog")

    assert win._alert_current is not None, "开关关掉后全屏不该抑制"
    assert quiet_mode.shared_quiet_state().pending_count() == 0


def test_quiet_drains_prequeued_ordinary_alerts(win):
    """免打扰开始**前**已入队的普通提醒：推进队列时转存，不在免打扰期间冒出来。"""
    win.show_alert("第一条", duration_ms=6000, sticky=False, alert_type="watchdog")
    win.show_alert("第二条", duration_ms=6000, sticky=False, alert_type="watchdog")
    assert len(_queue(win)) == 1

    quiet_mode.shared_quiet_state().start(15)
    win.hide_bubble()

    assert win._alert_current is None, "免打扰期间不得再冒出排队的普通提醒"
    assert quiet_mode.shared_quiet_state().drain() == ["第二条"]


def test_quiet_does_not_touch_self_talk_or_link_bubbles(win):
    """自言自语/点击台词与联动状态气泡穿透：它们走 bubble_blocked/show_bubble。"""
    quiet_mode.shared_quiet_state().start(15)

    assert window_alerts.quiet_blocked(win) is True
    assert window_alerts.bubble_blocked(win) is False, "免打扰不得写进 bubble_blocked"

    assert win._show_self_talk_text("自言自语一句") is True
    assert _shown_texts(win)[-1] == "自言自语一句"

    # 联动状态气泡走 show_bubble（不经 bubble_blocked / quiet_blocked）
    win.show_bubble("联动：正在思考", duration_ms=3000)
    assert "联动：正在思考" in _shown_texts(win)


def test_report_quiet_summary_uses_one_bubble(win):
    assert window_alerts.report_quiet_summary(win, []) is False, "空暂存不打扰用户"
    assert window_alerts.report_quiet_summary(win, ["甲", "乙"]) is True

    text = _shown_texts(win)[-1]
    assert "2 条提醒" in text and "乙" in text


def test_end_quiet_mode_reports_and_clears(win):
    from pet.context_menus.shared import end_quiet_mode

    quiet_mode.shared_quiet_state().start(15)
    win.show_alert("卡住了", duration_ms=6000, sticky=False, alert_type="watchdog")
    win._alert_current = None  # 清掉展示态，让汇报气泡立刻上屏

    assert end_quiet_mode(win) == ["卡住了"]
    assert quiet_mode.shared_quiet_state().pending_count() == 0
    assert "1 条提醒" in _shown_texts(win)[-1]


# ---------------------------------------------------------------- 3. 接线


def _fake_pet(cfg):
    return type("Pet", (), {"cfg": cfg})()


def test_quiet_menu_lists_durations_and_shows_remaining(qapp, tmp_path):
    from PySide6.QtWidgets import QMenu

    from pet.config import Config
    from pet.context_menus.shared import add_quiet_mode_menu

    pet = _fake_pet(Config(base=tmp_path))
    root_menu = QMenu()
    submenu = add_quiet_mode_menu(root_menu, pet)
    labels = [action.text() for action in submenu.actions()]
    assert [label for label in labels if label] == [
        "15 分钟", "30 分钟（默认）", "1 小时", "2 小时", "提前结束",
    ]
    assert [a.isEnabled() for a in submenu.actions() if a.text() == "提前结束"] == [False]

    # 点击一档：立刻开始，时长取自该档
    submenu.actions()[2].trigger()
    state = quiet_mode.shared_quiet_state()
    assert state.manual_active() is True
    assert state.started_minutes() == 60

    # 开启期间菜单项显示剩余时间（子菜单标题 / 进行中 / 提前结束三处）
    active_sub = add_quiet_mode_menu(QMenu(root_menu), pet)
    assert active_sub.title().startswith("免打扰 · 剩余 ")
    active_labels = [action.text() for action in active_sub.actions()]
    assert "1 小时 · 进行中" in active_labels
    end_label = [label for label in active_labels if label.startswith("提前结束（剩余 ")][0]
    assert [a.isEnabled() for a in active_sub.actions() if a.text() == end_label] == [True]


def test_quiet_menu_end_action_reports(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu

    from pet.config import Config
    from pet.context_menus.shared import add_quiet_mode_menu

    pet = _fake_pet(Config(base=tmp_path))
    quiet_mode.shared_quiet_state().start(15)
    quiet_mode.shared_quiet_state().remember("攒了一条")
    reported: list = []
    monkeypatch.setattr(
        window_alerts, "report_quiet_summary", lambda host, items: reported.append(items)
    )

    root_menu = QMenu()
    submenu = add_quiet_mode_menu(root_menu, pet)
    end_action = [a for a in submenu.actions() if a.text().startswith("提前结束")][0]
    end_action.trigger()

    assert reported == [["攒了一条"]]
    assert quiet_mode.shared_quiet_state().manual_active() is False


def test_default_duration_setting_moves_the_menu_marker(qapp, tmp_path):
    from PySide6.QtWidgets import QMenu

    from pet.config import Config
    from pet.context_menus.shared import add_quiet_mode_menu

    cfg = Config(base=tmp_path)
    cfg.set("quiet_minutes_default", 120)

    root_menu = QMenu()
    labels = [a.text() for a in add_quiet_mode_menu(root_menu, _fake_pet(cfg)).actions()]
    assert "2 小时（默认）" in labels
    assert "30 分钟（默认）" not in labels


@pytest.mark.parametrize("template", ["legacy", "modern"])
def test_both_window_menu_paths_expose_quiet_entry(qapp, tmp_path, template):
    """窗口侧 legacy 与 modern 两条菜单路径都要有免打扰入口。

    overlay（facade）路径由 ``test_sprite_menu_parity.py`` 锁死——facade 直接复用
    context_menus 的同一套建造器，两条路径共用这一处菜单结构。
    """
    from PySide6.QtWidgets import QMenu

    from pet.context_menu import populate_context_menu
    from tests.pet_window_fakes import make_pet_window

    window = make_pet_window(tmp_path, runtime_id=f"slot-{template}")
    window.cfg.set("context_menu_template", template)
    menu = QMenu()
    populate_context_menu(menu, window)

    titles = [action.text() for action in menu.actions()]
    titles += [a.menu().title() for a in menu.actions() if a.menu() is not None]
    assert any(title.startswith("免打扰") for title in titles), f"{template} 菜单缺少免打扰入口"
    window.close()
    qapp.processEvents()


def test_overlay_facade_host_can_build_quiet_menu(qapp, tmp_path):
    """overlay 的 ``SpriteMenuFacade`` 宿主也能建这个入口。

    facade 直接复用 context_menus 的同一套建造器（overlay 全量菜单树与窗口侧
    逐点一致由 ``test_sprite_menu_parity.py`` 锁死）；这里补一条**宿主形状**的
    钉子：建造器只读 ``pet.cfg``，不依赖任何 PetWindow 专有属性。
    """
    from PySide6.QtWidgets import QMenu

    from pet.config import Config
    from pet.context_menus.shared import add_quiet_mode_menu
    from pet.sprite_menu_facade import SpriteMenuFacade

    shell = type("Shell", (), {"_config": Config(base=tmp_path), "sprite": object()})()
    root_menu = QMenu()
    submenu = add_quiet_mode_menu(root_menu, SpriteMenuFacade(shell))

    assert [a.text() for a in submenu.actions() if a.text()][:4] == [
        "15 分钟", "30 分钟（默认）", "1 小时", "2 小时",
    ]


def test_legacy_menu_entry_is_a_submenu_with_durations(qapp, tmp_path):
    from PySide6.QtWidgets import QMenu

    from pet.context_menu import populate_context_menu
    from tests.pet_window_fakes import make_pet_window

    window = make_pet_window(tmp_path, runtime_id="slot-legacy-sub")
    window.cfg.set("context_menu_template", "legacy")
    menu = QMenu()
    populate_context_menu(menu, window)

    submenus = [a.menu() for a in menu.actions() if a.menu() is not None]
    quiet = [s for s in submenus if s.title().startswith("免打扰")]
    assert quiet, "legacy 菜单缺少免打扰子菜单"
    assert [a.text() for a in quiet[0].actions() if a.text()][:4] == [
        "15 分钟", "30 分钟（默认）", "1 小时", "2 小时",
    ]
    window.close()
    qapp.processEvents()


def test_appshell_fullscreen_broadcast_flips_quiet(qapp):
    """既有全屏避让广播（AppShell._on_shared_fullscreen）是等效免打扰的唯一来源。"""
    from pet.app import AppShell

    shell = type("Shell", (), {"_shared": object(), "_instances": []})()
    assert quiet_mode.shared_quiet_state().fullscreen() is False

    AppShell._on_shared_fullscreen(shell, True)
    assert quiet_mode.shared_quiet_state().fullscreen() is True
    assert quiet_mode.shared_quiet_state().suppression_active() is True

    AppShell._on_shared_fullscreen(shell, False)
    assert quiet_mode.shared_quiet_state().suppression_active() is False


def test_ticker_reports_queued_alerts_when_quiet_expires(qapp):
    """真实事件循环：到期后轮询表结算一次、汇报暂存提醒并自行停表。"""
    clock = FakeClock()
    state = quiet_mode.QuietState(clock=clock)
    ticker = quiet_mode.QuietTicker(state=state, interval_ms=10)
    reported: list[list[str]] = []
    ticker.ended.connect(reported.append)
    try:
        state.start(15)
        state.remember("攒了一条")
        assert ticker.active() is True, "免打扰一开始，轮询表就该跑起来"
        _spin(qapp, lambda: state.check_end() is None and state.manual_active())

        clock.advance(15 * 60)
        _spin(qapp, lambda: bool(reported))
        assert reported == [["攒了一条"]]
        _spin(qapp, lambda: not ticker.active())
    finally:
        ticker.stop()


def test_ticker_does_not_run_when_quiet_never_started(qapp):
    ticker = quiet_mode.QuietTicker(state=quiet_mode.QuietState(clock=FakeClock()),
                                    interval_ms=10)
    try:
        assert ticker.active() is False
        _pump(qapp, 0.15)
        assert ticker.active() is False
    finally:
        ticker.stop()


def _pump(qapp, seconds: float) -> None:
    """空转事件循环若干秒（用于断言"什么都不该发生"）。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def _spin(qapp, done, *, timeout: float = 5.0) -> None:
    """宽预算事件循环（CI 慢 runner 是本地数倍慢；宁可多等，不赌时序）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if done():
            return
        time.sleep(0.005)
    assert done(), "等待超时：条件在预算内未满足"


def test_settings_rows_live_in_automation_domain_and_round_trip(qapp, tmp_path):
    from pet import settings_quiet
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow

    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        page = dialog.pages.widget(labels.index("自动化与联动"))
        for key in settings_quiet.ROW_KEYS:
            row = dialog.findChild(SettingRow, f"settingRow_{key}")
            assert row is not None, f"缺少设置行 {key}"
            assert page.isAncestorOf(row), f"{key} 不在「自动化与联动」域里"

        dialog.quiet_minutes_select.setCurrentIndex(
            dialog.quiet_minutes_select.findData(120)
        )
        dialog.quiet_also_on_fullscreen_check.setChecked(False)
        settings_quiet.save_quiet_settings(dialog)

        assert dialog.config.get("quiet_minutes_default") == 120
        assert dialog.config.get("quiet_also_on_fullscreen") is False
        dialog.config.save()
        assert Config(base=tmp_path).get("quiet_minutes_default") == 120
    finally:
        dialog.close()
        qapp.processEvents()


def test_config_normalizes_dirty_quiet_values(tmp_path):
    """手改 config.json：档位归一到合法档、字符串布尔不得误开（#129 同规）。"""
    from pet.config import Config

    cfg = Config(base=tmp_path)
    cfg.set("quiet_minutes_default", "abc")
    assert cfg.data["quiet_minutes_default"] == config_mod.DEFAULT_QUIET_MINUTES
    cfg.set("quiet_minutes_default", 45)
    assert cfg.data["quiet_minutes_default"] in config_mod.QUIET_MINUTE_CHOICES
    cfg.set("quiet_also_on_fullscreen", "false")
    assert cfg.data["quiet_also_on_fullscreen"] is False


def test_config_defaults_match_quiet_mode_constants(tmp_path):
    """默认值 dict 的免打扰两键与 feature 常量必须一致（防止两处漂移）。"""
    from pet.config import Config

    cfg = Config(base=tmp_path)
    assert cfg.get("quiet_minutes_default") == config_mod.DEFAULT_QUIET_MINUTES
    assert cfg.get("quiet_also_on_fullscreen") is config_mod.DEFAULT_QUIET_ALSO_ON_FULLSCREEN


# ---------------------------------------------------------------- 子宠页作用域
def test_quiet_controls_are_main_pet_only(qapp, tmp_path):
    """子宠页：免打扰两键是进程级默认值（不在 PER_SLOT_SETTING_KEYS）→ 置灰。

    子宠页保存写 ``config-slot-N.json``，而免打扰的消费方（右键菜单命令、全屏
    联动、托盘的默认档）一律读主配置，改了等于没改；故如实置灰 + tooltip。
    """
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    master = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    child = ModernSettingsDialog(Config(base=tmp_path, instance_id="slot-1"),
                                 include_ai=False)
    try:
        assert master.quiet_minutes_select.isEnabled() is True
        assert master.quiet_also_on_fullscreen_check.isEnabled() is True
        for control in (child.quiet_minutes_select,
                        child.quiet_also_on_fullscreen_check):
            assert control.isEnabled() is False
            assert control.toolTip() == "仅主桌宠可设置"
    finally:
        for dialog in (master, child):
            dialog.close()
            dialog.deleteLater()
        qapp.processEvents()
