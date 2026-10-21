from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.contracts.contributions import SettingsPageSpec
from petcore.contracts.host import HostPorts
from petcore.mods.feature import FeatureManager
from petcore.ui.menu_model import MenuItem, MenuModel
from petcore.ui.settings.base import SettingsPage
from petcore.ui.settings.dialog import SettingsDialog

CORE_TITLES = [
    "常规",
    "外观与交互",
    "互动与物理",
    "多宠",
    "菜单",
    "扩展管理",
    "API 与账户",
    "关于与诊断",
]


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.click_through = False
        self.always_on_top = True
        self.scale = 0.72
        self.character = "shenshen"
        self.visible = True
        self.edge_probe = False

    def set_character(self, character_id, *, persist=True):
        self.character = character_id
        self.calls.append(("set_character", character_id, persist))

    def set_scale(self, scale, *, persist=True):
        self.scale = scale
        self.calls.append(("set_scale", scale, persist))

    def set_click_through(self, value, *, persist=True):
        self.click_through = bool(value)
        self.calls.append(("set_click_through", bool(value), persist))

    def set_always_on_top(self, value, *, persist=True):
        self.always_on_top = bool(value)
        self.calls.append(("set_always_on_top", bool(value), persist))

    def set_visible(self, visible):
        self.visible = bool(visible)
        self.calls.append(("set_visible", bool(visible)))

    def set_edge_probe_enabled(self, enabled, *, persist=True):
        self.edge_probe = bool(enabled)
        self.calls.append(("set_edge_probe_enabled", bool(enabled), persist))

    def isVisible(self):
        return self.visible

    def toggle_click_through(self):
        self.set_click_through(not self.click_through)

    def toggle_always_on_top(self):
        self.set_always_on_top(not self.always_on_top)

    def move_to_primary(self):
        self.calls.append(("move_to_primary",))

    def return_corner(self):
        self.calls.append(("return_corner",))

    def reset_position(self):
        self.calls.append(("reset_position",))

    def open_settings(self, initial_page=None):
        self.calls.append(("open_settings", initial_page))

    def say(self, text):
        self.calls.append(("say", text))


class FakeHost:
    def __init__(self, root: Path):
        self.config = Config(root)
        self.root = root
        self.window = FakeWindow()
        self.load_result = None
        self.diagnostics = []
        self.mod_dirs = ()
        self.settings_pages = None
        self.opened_data_dir = False
        self.reloaded = False
        # 与 CoreHost 同构：内置特性常驻，设置页据此内嵌 Core 特性页。
        self.features = FeatureManager(HostPorts(), host=self)
        self.diagnostics.extend(self.features.load_builtin_features())
        self._character = CharacterSpec(
            id="fallback",
            name="Fallback",
            root=root,
            media_kind="none",
            animations=(),
            owner="core",
        )

    def characters(self):
        return [self._character]

    def character_for(self, character_id):
        return self._character

    def build_menu(self, parent=None):
        return None

    def open_data_dir(self):
        self.opened_data_dir = True

    def reload_mods(self):
        self.reloaded = True

    def apply_live_settings(self):
        window = self.window
        character = str(self.config.get("character") or "")
        if character and character != window.character:
            window.set_character(character, persist=False)
        scale = float(self.config.get("scale") or 0.72)
        if abs(scale - window.scale) > 1e-9:
            window.set_scale(scale, persist=False)
        always_on_top = bool(self.config.get("always_on_top"))
        if always_on_top != window.always_on_top:
            window.set_always_on_top(always_on_top, persist=False)
        click_through = bool(self.config.get("click_through"))
        if click_through != window.click_through:
            window.set_click_through(click_through, persist=False)

    def set_hotkey(self, text, *, persist=True):
        self.hotkey = text
        return True, ""

    def quit_app(self):
        return None


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_modal_questions(monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )


def _host(tmp_path: Path) -> FakeHost:
    return FakeHost(tmp_path)


def _page(dialog: SettingsDialog, title: str) -> QWidget:
    for index in range(dialog.stack.count()):
        page = dialog.stack.widget(index)
        if getattr(page, "title", "") == title:
            return page
    raise AssertionError(f"missing settings page: {title}")


def _embedded(page, title: str) -> SettingsPage:
    for child in page._embedded_pages:
        if getattr(child, "title", "") == title:
            return child
    raise AssertionError(f"missing embedded page: {title}")


def _titles(dialog: SettingsDialog) -> list[str]:
    return [dialog.nav.item(row).text() for row in range(dialog.nav.count())]


def test_core_pages_and_contract(app, tmp_path):
    dialog = SettingsDialog(_host(tmp_path))
    assert _titles(dialog) == CORE_TITLES
    assert dialog.stack.count() == len(CORE_TITLES)
    for index in range(dialog.stack.count()):
        page = dialog.stack.widget(index)
        for method in ("dirty", "draft", "confirm_save", "discard_changes", "dispose", "keywords"):
            assert callable(getattr(page, method)), (getattr(page, "title", index), method)
        assert isinstance(page.dirty(), bool)
        assert isinstance(page.keywords(), list)
    assert "petcore v" in dialog.version_label.text()
    dialog.close()


def test_edge_probe_and_hotkey_settings_are_live(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")

    appearance.edge_probe_check.setChecked(True)
    assert host.window.edge_probe is True
    assert host.config.get("edge_probe_enabled") is True

    appearance.hotkey_edit.setText("ctrl+alt+p")
    appearance.hotkey_edit.editingFinished.emit()
    assert appearance.hotkey_edit.text() == "Ctrl+Alt+P"
    assert host.hotkey == "Ctrl+Alt+P"
    assert host.config.get("hotkey_toggle_pet") == "Ctrl+Alt+P"

    dialog.cancel_button.click()
    assert host.window.edge_probe is False
    assert host.config.get("edge_probe_enabled") is False


def test_dialog_is_non_modal(app, tmp_path):
    dialog = SettingsDialog(_host(tmp_path))
    assert dialog.isModal() is False
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    dialog.close()


def test_scale_widgets_cover_10_to_300_percent(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")
    assert appearance.scale_slider.minimum() == 10
    assert appearance.scale_slider.maximum() == 300
    assert appearance.scale_spin.minimum() == 10
    assert appearance.scale_spin.maximum() == 300
    assert appearance.scale_spin.text().strip() == "72 %"

    appearance.scale_spin.setValue(237)
    dialog._apply_live()
    assert host.config.get("scale") == 2.37
    assert host.window.scale == 2.37
    assert ("set_scale", 2.37, False) in host.window.calls

    appearance.scale_spin.setValue(500)
    assert appearance.scale_spin.value() == 300
    assert host.config.get("scale") == 3.0
    dialog.cancel_button.click()


def test_live_preview_applies_without_save(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")
    appearance.scale_spin.setValue(150)
    for _ in range(20):
        app.processEvents()
        if host.window.scale == 1.5:
            break
        QTest.qWait(10)
    assert host.window.scale == 1.5
    assert host.config.get("scale") == 1.5
    assert not (tmp_path / "config.json").exists()
    dialog.cancel_button.click()


def test_save_applies_scale_and_click_through(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")
    appearance.scale_spin.setValue(200)
    appearance.click_through_check.setChecked(True)
    dialog._apply_live()

    assert host.window.scale == 2.0
    assert host.window.click_through is True
    assert ("set_scale", 2.0, False) in host.window.calls

    dialog.save_button.click()

    assert host.config.get("scale") == 2.0
    assert host.config.get("click_through") is True
    assert host.config.get("character") == "shenshen"
    assert ("set_click_through", True, False) in host.window.calls
    assert not any(call[0] == "set_character" for call in host.window.calls)
    assert Config.load(tmp_path).get("scale") == 2.0
    assert Config.load(tmp_path).get("click_through") is True

    reopened = SettingsDialog(host)
    assert _page(reopened, "外观与交互").scale_spin.value() == 200
    reopened.close()


def test_cancel_reverts_live_changes(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    appearance = _page(dialog, "外观与交互")
    appearance.scale_spin.setValue(150)
    appearance.click_through_check.setChecked(True)
    dialog._apply_live()
    assert host.window.scale == 1.5
    assert host.window.click_through is True
    assert appearance.dirty() is True

    dialog.cancel_button.click()

    assert host.config.get("scale") == 0.72
    assert host.config.get("click_through") is False
    assert host.window.scale == 0.72
    assert host.window.click_through is False
    assert not (tmp_path / "config.json").exists()
    assert appearance.click_through_check.isChecked() is False
    assert appearance.scale_spin.value() == 72


def test_close_button_saves_live_changes(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    dialog.show()
    appearance = _page(dialog, "外观与交互")
    appearance.scale_spin.setValue(150)
    dialog._apply_live()

    dialog.close()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert host.config.get("scale") == 1.5
    assert host.window.scale == 1.5
    assert Config.load(tmp_path).get("scale") == 1.5


def test_initial_page_and_select_page(app, tmp_path):
    dialog = SettingsDialog(_host(tmp_path), initial_page="appearance")
    assert dialog.stack.currentWidget().title == "外观与交互"
    dialog.select_page("about")
    assert dialog.stack.currentWidget().title == "关于与诊断"
    dialog.close()


def test_search_filters_by_title_and_keywords(app, tmp_path):
    dialog = SettingsDialog(_host(tmp_path))
    dialog.search.setText("外观")
    assert dialog.nav.item(0).isHidden() is True
    assert dialog.nav.item(1).isHidden() is False
    assert dialog.search_status.text() == "匹配 1 个页面"

    dialog.search.clear()
    assert all(not dialog.nav.item(row).isHidden() for row in range(dialog.nav.count()))

    dialog.search.setText("DIAGNOSTICS")
    assert dialog.nav.item(CORE_TITLES.index("关于与诊断")).isHidden() is False
    assert dialog.search_status.text() == "匹配 1 个页面"

    dialog.search.setText("API 密钥")
    assert dialog.nav.item(CORE_TITLES.index("API 与账户")).isHidden() is False

    dialog.search.setText("没有这个页面")
    assert all(dialog.nav.item(row).isHidden() for row in range(dialog.nav.count()))
    assert dialog.search_status.text() == "没有匹配的设置页"
    dialog.close()


def test_menu_page_edits_layout_and_saves(app, tmp_path):
    host = _host(tmp_path)
    model = MenuModel()
    for order, item_id in enumerate(("a", "b", "c")):
        model.register(MenuItem(item_id, item_id.upper(), order=order))
    host.menu_model = model
    host.config.set(
        "menu_layout",
        {
            "schema_version": 1,
            "layout_id": "petcore-default-v1",
            "nodes": [
                {"type": "action", "id": "a", "visible": True},
                {"type": "action", "id": "b", "visible": True},
                {"type": "action", "id": "c", "visible": True},
            ],
        },
    )
    dialog = SettingsDialog(host)
    page = _page(dialog, "菜单")
    editor = page.editor
    assert editor.tree.topLevelItemCount() == 3
    assert [editor.tree.topLevelItem(row).text(0) for row in range(3)] == ["A", "B", "C"]

    editor.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
    editor.move_selected(-1)

    dialog.save_button.click()

    saved = host.config.get("menu_layout")
    assert [node["id"] for node in saved["nodes"]] == ["b", "a", "c"]
    assert saved["nodes"][1]["visible"] is False


def test_contributed_pages_are_isolated_and_disposed(app, tmp_path):
    host = _host(tmp_path)
    created = []

    class ExtraPage(SettingsPage):
        title = "自定义页"

        def __init__(self, host):
            super().__init__(host)
            self.disposed = False
            created.append(self)

        def keywords(self):
            return ["自定义"]

        def dispose(self):
            self.disposed = True

    def boom(host):
        raise RuntimeError("bad contribution")

    host.settings_pages = lambda: [
        SettingsPageSpec("extra", "自定义页", ExtraPage, order=5),
        SettingsPageSpec("broken", "坏页", boom, order=6),
    ]
    dialog = SettingsDialog(host)
    assert _titles(dialog) == CORE_TITLES
    extensions = _page(dialog, "扩展管理")
    assert "自定义页" in extensions.tabs.labels()
    assert len(created) == 1

    extensions.select_tab("extension:extra")
    assert extensions.tabs.currentKey() == "extension:extra"

    dialog.close()
    assert created[0].disposed is True


def test_plain_widget_contribution_is_hosted_with_hint(app, tmp_path):
    from PySide6.QtWidgets import QLabel

    host = _host(tmp_path)
    host.settings_pages = lambda: [
        SettingsPageSpec("plain", "普通控件", lambda _host: QLabel("hello"), order=7),
    ]
    dialog = SettingsDialog(host)
    extensions = _page(dialog, "扩展管理")
    assert "普通控件" in extensions.tabs.labels()
    extensions.select_tab("extension:plain")
    assert extensions.tabs.currentKey() == "extension:plain"
    hosted = dict(extensions._pages)["extension:plain"]
    assert hosted.dirty() is False
    texts = [label.text() for label in hosted.scroll.widget().findChildren(QLabel)]
    assert any("没有实现 SettingsPage" in text for text in texts)
    dialog.close()


def test_golden_spin_sub_option_follows_its_parent(app, tmp_path):
    host = _host(tmp_path)
    host.config.set("golden_spin_on_click", False)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    row = interaction._spin_direct_row
    assert row.isVisibleTo(interaction) is False
    interaction._checks["golden_spin_on_click"].setChecked(True)
    assert row.isVisibleTo(interaction) is True
    interaction._checks["golden_spin_on_click"].setChecked(False)
    assert row.isVisibleTo(interaction) is False
    dialog.close()


def test_search_matches_setting_rows_and_jumps_to_the_page(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    dialog.search.setText("黄金回旋")
    app.processEvents()
    assert dialog.search_status.text().startswith("匹配")
    assert dialog.nav.currentItem().text() == "互动与物理"

    dialog.search.setText("开机自动启动")
    app.processEvents()
    assert dialog.nav.currentItem().text() == "常规"

    dialog.search.setText("完全不存在的东西")
    app.processEvents()
    assert dialog.search_status.text() == "没有匹配的设置页"
    dialog.close()


# ---------------------------------------------------------------- 页内分页
def test_interaction_page_splits_into_inner_tabs(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    tabs = interaction.tab_container
    assert tabs is not None
    assert tabs.labels() == (
        "点击与音效",
        "点击台词",
        "自言自语",
        "拖拽与投掷",
        "碰撞与投喂",
        "动画",
        "彩蛋与配图",
        "免打扰",
    )
    assert tabs.keys() == (
        "click",
        "click_talk",
        "self_talk",
        "drag",
        "collision",
        "animation",
        "easter",
        "quiet",
    )
    dialog.close()


def test_embedded_page_changes_flow_through_save(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    click_talk = _embedded(interaction, "点击台词")

    click_talk.enabled.setChecked(True)
    assert host.config.get("click_talk_enabled") is True
    assert interaction.dirty() is True

    dialog.save_button.click()

    assert interaction.dirty() is False
    assert Config.load(tmp_path).get("click_talk_enabled") is True


def test_embedded_page_changes_flow_through_cancel(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    assert interaction.dirty() is False

    self_talk = _embedded(interaction, "自言自语")
    self_talk.enabled.setChecked(True)
    assert host.config.get("self_talk_enabled") is True
    assert interaction.dirty() is True

    dialog.cancel_button.click()

    assert host.config.get("self_talk_enabled") is False
    assert self_talk.enabled.isChecked() is False
    assert not (tmp_path / "config.json").exists()


def test_core_pages_host_their_feature_tabs(app, tmp_path):
    host = _host(tmp_path)
    host.menu_model = MenuModel()
    dialog = SettingsDialog(host)

    menu = _page(dialog, "菜单")
    assert menu.tab_container.labels() == ("菜单编排", "快捷启动")
    assert [page.title for page in menu._embedded_pages] == ["快捷启动"]

    launcher = menu._embedded_pages[0]
    launcher.editor.setPlainText("记事本|C:\\Windows\\notepad.exe|")
    assert menu.dirty() is True
    menu.confirm_save()
    assert host.config.get("quick_launch_apps") == [
        {"name": "记事本", "path": "C:\\Windows\\notepad.exe", "args": []}
    ]

    about = _page(dialog, "关于与诊断")
    assert about.tab_container.labels() == ("版本与诊断", "链接与项目", "网络信息", "回收内存")
    assert [page.title for page in about._embedded_pages] == ["链接与项目", "网络信息", "回收内存"]
    dialog.close()


def test_easter_display_mode_is_written_live(app, tmp_path):
    host = _host(tmp_path)
    writes: list[tuple[str, object]] = []
    original_set = host.config.set

    def recording_set(key, value):
        writes.append((str(key), value))
        original_set(key, value)

    host.config.set = recording_set
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    combo = interaction.easter_display
    assert combo.currentData() == "bubble"

    combo.setCurrentIndex(combo.findData("window"))

    assert combo.currentData() == "window"
    assert ("easter_egg_display", "window") in writes
    assert interaction.dirty() is True
    dialog.close()


def test_search_reveals_rows_inside_inner_tabs(app, tmp_path):
    dialog = SettingsDialog(_host(tmp_path))
    dialog.search.setText("点击时随机说话")
    app.processEvents()

    interaction = _page(dialog, "互动与物理")
    assert dialog.stack.currentWidget() is interaction
    assert interaction.tab_container.currentKey() == "click_talk"
    dialog.close()


def test_each_core_feature_page_is_built_exactly_once(app, tmp_path):
    host = _host(tmp_path)
    host.settings_pages = host.features.settings_pages
    dialog = SettingsDialog(host)

    extensions = _page(dialog, "扩展管理")
    for owner, feature in host.features.features.items():
        factory = feature.definition.settings_factory
        assert len(dialog.findChildren(factory)) == 1, owner
        assert extensions.findChildren(factory) == [], owner
    dialog.close()


def test_closing_dialog_disposes_embedded_pages(app, tmp_path):
    host = _host(tmp_path)
    dialog = SettingsDialog(host)
    interaction = _page(dialog, "互动与物理")
    assert interaction._embedded_pages

    dialog.close()

    assert interaction._embedded_pages == []


def test_interaction_rows_remain_reachable_from_menu_coverage(app, tmp_path):
    from petcore.ui.settings.coverage import CORE_MENU_SETTINGS_COVERAGE

    dialog = SettingsDialog(_host(tmp_path))
    interaction = _page(dialog, "互动与物理")
    haystack = " ".join(interaction.keywords())
    for menu_id, (page_key, row) in CORE_MENU_SETTINGS_COVERAGE.items():
        if page_key != "interaction":
            continue
        assert row in haystack, (menu_id, row)
    dialog.close()
