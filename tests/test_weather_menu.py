# -*- coding: utf-8 -*-
"""天气菜单与城市子菜单（menu builders + 注册表 + 添加/删除流程 + 城市对话框）。

用例只碰公开面：菜单建造器、注册表 action id、城市对话框的公开方法、配置写入
记录。不断言私有调用顺序，也不真发外网请求（搜索函数注入）。

约定与 ``add_balance`` / ``build_character_menu`` 一致：建造器读 ``pet.cfg``、
经 ``pet.on_show_weather`` 把结果交给冒泡服务；城市列表是**全局设置**（窗口路径
直接写主配置，overlay 路径经 ``_SpriteConfig`` 的 ``__getattr__`` 转发到主配置）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from pet import weather as W  # noqa: E402
from pet import weather_menu as M  # noqa: E402
from pet.context_menus.registry import MENU_ACTIONS  # noqa: E402

app = QApplication.instance() or QApplication([])


class _Cfg:
    """配置视图替身：读 dict，写记账（真实场景是 Config / _SpriteConfig 视图）。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list[tuple[str, object]] = []
        self.saves = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.writes.append((key, value))

    def save(self):
        self.saves += 1

    def written(self, key):
        return [value for name, value in self.writes if name == key]


class _Pet:
    """菜单宿主替身（PetWindow / SpriteMenuFacade 的公共面）。"""

    def __init__(self, values=None, *, available=True):
        self.cfg = _Cfg(values)
        self.shown: list = []
        self.on_show_weather = (
            (lambda *args: self.shown.append(args)) if available else None
        )


class _FakeDialog(QObject):
    """城市对话框替身：与 ``WeatherCityDialog`` 的公开面同形（``exec`` 不阻塞）。"""

    search_requested = Signal(str)

    def __init__(self, name="", *, query="", accepted=True):
        super().__init__()
        self._name = name
        self._query = query
        self._accepted = accepted
        self.begun = 0
        self.results_seen: list = []

    def exec(self) -> int:  # noqa: A003 - 模仿 QDialog.exec
        if self._query:
            self.search_requested.emit(self._query)
        return 1 if self._accepted else 0

    def chosen_name(self) -> str:
        return self._name

    def begin_search(self) -> None:
        self.begun += 1

    def set_search_results(self, results, error="") -> None:
        self.results_seen.append((results, error))


def _labels(menu):
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _find(menu, label):
    for action in menu.actions():
        if action.text() == label:
            return action
    raise AssertionError(f"菜单缺项 {label}；实际 = {_labels(menu)}")


def _factory(name: str, **kwargs):
    return lambda _parent=None: _FakeDialog(name, **kwargs)


# ---------------------------------------------------------------- 查看天气入口
def test_show_weather_action_calls_through_to_the_window_callback():
    pet = _Pet({})
    menu = QMenu()
    action = M.add_show_weather(menu, pet)
    assert action.text() == "查看天气"
    assert action.property("closeOnTrigger") is True
    action.trigger()
    assert pet.shown == [(pet,)], "窗口/壳侧的 on_show_weather 必须以宿主自身为 parent"


def test_show_weather_action_absent_without_callback():
    pet = _Pet({}, available=False)
    menu = QMenu()
    assert M.add_show_weather(menu, pet) is None
    assert _labels(menu) == []


# ---------------------------------------------------------------- 城市子菜单
def _city_actions(submenu):
    return [action.text() for action in submenu.actions() if action.isCheckable()]


def test_city_submenu_checks_the_current_city_and_lists_all_of_them():
    pet = _Pet({"weather_city": "上海", "weather_city_list": ["北京", "上海", "鹿城"]})
    menu = QMenu()
    submenu = M.add_weather_cities(menu, pet)
    assert submenu is not None and submenu.title() == "天气城市"
    assert _city_actions(submenu) == ["北京", "上海", "鹿城"]
    checked = [action.text() for action in submenu.actions()
               if action.isCheckable() and action.isChecked()]
    assert checked == ["上海"], "当前城市必须有且只有一个勾"
    assert _labels(submenu) == ["北京", "上海", "鹿城", "添加城市…", "删除城市"]


def test_city_submenu_shows_an_empty_hint_when_no_city_is_configured():
    pet = _Pet({"weather_city": "", "weather_city_list": []})
    menu = QMenu()
    submenu = M.add_weather_cities(menu, pet)
    assert _city_actions(submenu) == []
    assert "还没有城市" in _labels(submenu)[0]


def test_clicking_a_city_switches_persists_and_shows_weather():
    pet = _Pet({"weather_city": "上海", "weather_city_list": ["北京", "上海"]})
    menu = QMenu()
    submenu = M.add_weather_cities(menu, pet)
    _find(submenu, "北京").trigger()
    assert pet.cfg.written("weather_city") == ["北京"]
    assert pet.cfg.saves == 1
    assert len(pet.shown) == 1, "切换城市后顺手把天气冒出来（否则还要再点一次）"


def test_switching_to_a_city_missing_from_the_list_keeps_the_list_consistent():
    pet = _Pet({"weather_city": "上海", "weather_city_list": ["上海"]})
    M.switch_city(pet, "鹿城")
    assert pet.cfg.get("weather_city") == "鹿城"
    assert pet.cfg.get("weather_city_list") == ["上海", "鹿城"]


def test_delete_city_submenu_removes_the_city_and_moves_the_current_one():
    pet = _Pet({"weather_city": "上海", "weather_city_list": ["北京", "上海"]})
    menu = QMenu()
    submenu = M.add_weather_cities(menu, pet)
    remove_menu = _find(submenu, "删除城市").menu()
    assert remove_menu is not None
    _find(remove_menu, "上海").trigger()
    assert pet.cfg.get("weather_city_list") == ["北京"]
    assert pet.cfg.get("weather_city") == "北京"
    assert pet.cfg.saves == 1


# ---------------------------------------------------------------- 添加城市
def test_add_city_flow_adds_selects_persists_and_shows_weather():
    pet = _Pet({"weather_city": "", "weather_city_list": []})
    added = M.add_city_flow(pet, dialog_factory=_factory("鹿城区"))
    assert added == "鹿城", "手填带后缀的城市名归一化后再存（鹿城区 → 鹿城）"
    assert pet.cfg.get("weather_city_list") == ["鹿城"]
    assert pet.cfg.get("weather_city") == "鹿城"
    assert pet.cfg.saves == 1
    assert len(pet.shown) == 1


def test_add_city_flow_reports_the_cap_instead_of_silently_dropping_it():
    full = [f"城市{i}" for i in range(W.MAX_CITIES)]
    pet = _Pet({"weather_city": full[0], "weather_city_list": list(full)})
    notes: list[str] = []
    added = M.add_city_flow(pet, dialog_factory=_factory("新城市"), notify=notes.append)
    assert added == ""
    assert notes == [W.CITY_LIMIT_TEXT]
    assert pet.cfg.get("weather_city_list") == full
    assert pet.cfg.writes == []


def test_add_city_flow_does_nothing_when_the_dialog_is_cancelled():
    pet = _Pet({"weather_city": "", "weather_city_list": []})
    assert M.add_city_flow(pet, dialog_factory=_factory("", accepted=False)) == ""
    assert pet.cfg.writes == []
    assert pet.shown == []


def test_open_add_city_dialog_threads_search_results_back_into_the_dialog():
    """对话框请求搜索 → 注入的搜索函数在调用线程执行 → 结果回填对话框。"""
    pet = _Pet({})
    dialog = _FakeDialog("鹿城", query="鹿城")
    queries: list[str] = []

    def searcher(query):
        queries.append(query)
        return [W.CityCandidate(code="101210710", name="鹿城", region="浙江")], ""

    chosen = M.open_add_city_dialog(
        pet, dialog_factory=lambda _parent=None: dialog, search=searcher,
        run_async=lambda work: work(),
    )
    assert chosen == "鹿城"
    assert queries == ["鹿城"]
    assert dialog.begun == 1
    assert dialog.results_seen == [
        ([W.CityCandidate(code="101210710", name="鹿城", region="浙江")], "")
    ]


# ---------------------------------------------------------------- 城市对话框
def test_city_dialog_search_button_emits_the_typed_query():
    dialog = M.WeatherCityDialog()
    seen: list[str] = []
    dialog.search_requested.connect(seen.append)
    dialog.name_edit.setText(" 鹿城区 ")
    dialog.search_btn.click()
    assert seen == ["鹿城区"]

    dialog.name_edit.setText("   ")
    dialog.search_btn.click()
    assert seen == ["鹿城区"], "空白输入不触发搜索"


def test_city_dialog_disables_search_while_pending_and_restores_it():
    dialog = M.WeatherCityDialog()
    dialog.name_edit.setText("鹿城")
    dialog.search_btn.click()
    assert dialog.search_btn.isEnabled() is False
    assert "搜索中" in dialog.status_label.text()

    dialog.set_search_results(
        [W.CityCandidate(code="101210710", name="鹿城", region="浙江")], "")
    assert dialog.search_btn.isEnabled() is True
    assert dialog.chosen_name() == "鹿城"
    assert [dialog.results.item(i).text() for i in range(dialog.results.count())] == ["鹿城（浙江）"]


def test_city_dialog_offers_manual_entry_when_the_search_finds_nothing():
    dialog = M.WeatherCityDialog()
    dialog.name_edit.setText("鹿城区")
    dialog.set_search_results([], "请求超时")
    assert dialog.results.count() == 0
    assert "请求超时" in dialog.status_label.text()
    assert "直接添加" in dialog.status_label.text()
    assert dialog.chosen_name() == "鹿城"
    assert dialog.add_btn.isEnabled() is True


def test_city_dialog_add_button_follows_the_input_state():
    dialog = M.WeatherCityDialog()
    assert dialog.add_btn.isEnabled() is False
    dialog.name_edit.setText("鹿城")
    assert dialog.add_btn.isEnabled() is True
    dialog.name_edit.setText("   ")
    assert dialog.add_btn.isEnabled() is False


def test_start_search_feeds_the_dialog_through_the_injected_searcher():
    dialog = M.WeatherCityDialog()
    queries: list[str] = []

    def searcher(query):
        queries.append(query)
        return [W.CityCandidate(code="101210710", name="鹿城", region="浙江")], ""

    M.start_search(dialog, "鹿城", searcher, runner=lambda work: work())
    assert queries == ["鹿城"]
    assert dialog.chosen_name() == "鹿城"
    assert dialog.search_btn.isEnabled() is True


def test_open_add_city_dialog_returns_the_chosen_name():
    pet = _Pet({})
    assert M.open_add_city_dialog(pet, dialog_factory=_factory("鹿城")) == "鹿城"


# ---------------------------------------------------------------- 注册表
def test_registry_exposes_weather_actions_with_labels_and_icons():
    from pet.context_menus.registry import ACTION_ICONS, ACTION_LABELS

    assert {"weather", "weather_cities"} <= MENU_ACTIONS.ids
    assert ACTION_LABELS["weather"] == "查看天气"
    assert ACTION_LABELS["weather_cities"] == "天气城市"
    assert ACTION_ICONS["weather"] == "weather"
    assert MENU_ACTIONS.default_icon("weather") == "weather"


def test_registry_gates_weather_on_the_callback_and_the_switch():
    class _NoCallback:
        cfg = _Cfg({})

    assert "weather" not in MENU_ACTIONS.available_ids(_NoCallback())

    pet = _Pet({"weather_enabled": True})
    assert {"weather", "weather_cities"} <= MENU_ACTIONS.available_ids(pet)
    assert {"weather", "weather_cities"} <= MENU_ACTIONS.enabled_ids(pet)

    off = _Pet({"weather_enabled": False})
    assert "weather" in MENU_ACTIONS.available_ids(off), "关掉开关只降级为置灰，位置保留"
    assert "weather" not in MENU_ACTIONS.enabled_ids(off)
    assert MENU_ACTIONS.disabled_reason("weather") == "天气功能已在设置中关闭"


def test_modern_default_layout_places_weather_beside_the_other_tools():
    from pet.menu_layout import load_default_menu_layout

    nodes = load_default_menu_layout("modern-default-v1")["nodes"]
    ids = [node["id"] for node in nodes]
    assert "weather" in ids and "weather_cities" in ids
    assert ids.index("weather") + 1 == ids.index("weather_cities")
    weather = next(node for node in nodes if node["id"] == "weather")
    assert weather["visible"] is True and weather["section"] == "tools"


# ---------------------------------------------------------------- 两条 facade
def test_real_petwindow_legacy_menu_contains_weather_entries(tmp_path):
    """legacy 扁平布局（真 PetWindow + 真建造器）里两个入口都在。"""
    import tests.test_sprite_menu_parity as parity
    from pet.config import Config
    from pet.context_menu import load_menu_template
    from pet.context_menus import build_legacy_menu

    config = Config(base=tmp_path)
    win = parity._reference_window(config)
    try:
        menu = QMenu()
        build_legacy_menu(menu, win, load_menu_template("legacy"))
        labels = _labels(menu)
        assert "查看天气" in labels and "天气城市" in labels
    finally:
        win.close()
