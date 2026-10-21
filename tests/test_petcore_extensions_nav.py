"""扩展管理的竖向导航、分组、中文名与过滤回归。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.contracts.contributions import SettingsPageSpec
from petcore.contracts.host import HostPorts
from petcore.mods import feature as feature_mod
from petcore.mods.manifest import load_manifest
from petcore.ui.settings.base import SettingsPage
from petcore.ui.settings.dialog import SettingsDialog
from petcore.ui.settings.page_mods import ModsPage
from tests.test_petcore_settings import FakeHost

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "petcore-mods"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 扩展页导航
class _BasePage(SettingsPage):
    title = "基础页"

    def __init__(self, host):
        super().__init__(host)
        self.disposed = False

    def dispose(self):
        self.disposed = True


class _AddonPage(SettingsPage):
    title = "加装页"

    def __init__(self, host):
        super().__init__(host)
        self.disposed = False

    def dispose(self):
        self.disposed = True


def _extensions(dialog: SettingsDialog):
    for index in range(dialog.stack.count()):
        page = dialog.stack.widget(index)
        if getattr(page, "title", "") == "扩展管理":
            return page
    raise AssertionError("missing extensions page")


def _host_with_pages(tmp_path: Path) -> FakeHost:
    host = FakeHost(tmp_path)
    host.settings_pages = lambda: [
        SettingsPageSpec(
            "base.one", "Base one", _BasePage, order=10, label="基础一号", group="base"
        ),
        # order 更小：注册顺序会排在前面，但导航与 labels 必须按分组顺序。
        SettingsPageSpec(
            "addon.one", "Addon one", _AddonPage, order=5, label="加装一号", group="addon"
        ),
    ]
    return host


def test_nav_puts_mods_first_then_group_headers(app, tmp_path):
    dialog = SettingsDialog(_host_with_pages(tmp_path))
    extensions = _extensions(dialog)
    nav = extensions.nav
    labels = [nav.item(row).text() for row in range(nav.count())]
    assert labels == ["扩展管理", "▾ 基础扩展", "基础一号", "▾ 加装扩展", "加装一号"]

    for row in (1, 3):
        flags = nav.item(row).flags()
        assert not (flags & Qt.ItemFlag.ItemIsSelectable)
        assert flags & Qt.ItemFlag.ItemIsEnabled

    assert nav.item(0).data(Qt.ItemDataRole.UserRole) == "mods"
    assert nav.item(2).data(Qt.ItemDataRole.UserRole) == "extension:base.one"
    assert nav.item(4).data(Qt.ItemDataRole.UserRole) == "extension:addon.one"

    assert extensions.tabs.labels() == ("扩展管理", "基础一号", "加装一号")
    assert extensions.tabs.keys() == (
        "mods",
        "extension:base.one",
        "extension:addon.one",
    )
    dialog.close()


def test_group_headers_collapse_their_children(app, tmp_path):
    dialog = SettingsDialog(_host_with_pages(tmp_path))
    dialog.show()
    app.processEvents()
    extensions = _extensions(dialog)
    nav = extensions.nav

    def click_item(item):
        QTest.mouseClick(
            nav.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            nav.visualItemRect(item).center(),
        )
        app.processEvents()

    base_header = nav.item(1)
    assert nav.item(2).isHidden() is False

    click_item(base_header)
    assert base_header.text().startswith("▸")
    assert nav.item(2).isHidden() is True
    assert extensions.is_group_collapsed("base") is True
    # 折叠只影响导航可见性，标签门面与页面注册不变。
    assert extensions.tabs.labels() == ("扩展管理", "基础一号", "加装一号")
    assert nav.currentItem().text() == "扩展管理"

    click_item(base_header)
    assert base_header.text().startswith("▾")
    assert nav.item(2).isHidden() is False
    assert extensions.is_group_collapsed("base") is False
    dialog.close()


def test_deep_link_expands_a_collapsed_group(app, tmp_path):
    dialog = SettingsDialog(_host_with_pages(tmp_path))
    dialog.show()
    app.processEvents()
    extensions = _extensions(dialog)
    nav = extensions.nav

    QTest.mouseClick(
        nav.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        nav.visualItemRect(nav.item(1)).center(),
    )
    app.processEvents()
    assert extensions.is_group_collapsed("base") is True

    extensions.select_tab("extension:base.one")

    assert extensions.is_group_collapsed("base") is False
    assert nav.item(2).isHidden() is False
    assert extensions.tabs.currentKey() == "extension:base.one"
    dialog.close()


def test_core_feature_pages_never_show_in_extension_nav(app, tmp_path):
    host = FakeHost(tmp_path)
    host.settings_pages = host.features.settings_pages
    dialog = SettingsDialog(host)
    extensions = _extensions(dialog)
    # 7 个内置特性的设置页全部内嵌进 Core 页，扩展导航只剩「扩展管理」。
    assert extensions.tabs.labels() == ("扩展管理",)
    assert [nav_row for nav_row in extensions._row_keys.values()] == ["mods"]
    dialog.close()


def test_nav_selection_switches_stack_and_keeps_tab_facade(app, tmp_path):
    dialog = SettingsDialog(_host_with_pages(tmp_path))
    extensions = _extensions(dialog)
    pages = dict(extensions._pages)

    assert extensions.tabs.currentKey() == "mods"
    assert extensions.stack.currentWidget() is pages["mods"]

    extensions.select_tab("extension:addon.one")
    assert extensions.tabs.currentKey() == "extension:addon.one"
    assert extensions.stack.currentWidget() is pages["extension:addon.one"]
    assert extensions.nav.currentItem().text() == "加装一号"

    extensions.tabs.setCurrentKey("extension:base.one")
    assert extensions.tabs.currentKey() == "extension:base.one"
    assert extensions.stack.currentWidget() is pages["extension:base.one"]

    extensions.select_label("加装一号")
    assert extensions.tabs.currentKey() == "extension:addon.one"
    assert extensions.tabs.key_for_label("基础一号") == "extension:base.one"

    # 搜索定位等入口直接切 stack 时，左侧选中同步过来。
    extensions.stack.setCurrentWidget(pages["extension:base.one"])
    assert extensions.nav.currentItem().text() == "基础一号"
    assert extensions.tabs.currentKey() == "extension:base.one"

    addon_page = pages["extension:addon.one"]
    dialog.close()
    assert addon_page.disposed is True


def test_empty_group_keeps_its_header(app, tmp_path):
    host = FakeHost(tmp_path)
    host.settings_pages = lambda: []
    dialog = SettingsDialog(host)
    extensions = _extensions(dialog)
    nav = extensions.nav
    labels = [nav.item(row).text() for row in range(nav.count())]
    assert labels == [
        "扩展管理",
        "▾ 基础扩展",
        "（暂无）",
        "▾ 加装扩展",
        "（暂无）",
    ]
    assert extensions.tabs.labels() == ("扩展管理",)
    dialog.close()


# ---------------------------------------------------------------- 扩展管理页
def _mod(mod_id: str, name: str, name_zh: str, path: Path, *, enabled: bool = True):
    manifest = SimpleNamespace(
        id=mod_id, kind="feature", name=name, name_zh=name_zh, version="1.0.0"
    )
    return SimpleNamespace(id=mod_id, manifest=manifest, enabled=enabled, path=path)


def _host_with_mods(tmp_path: Path) -> FakeHost:
    host = FakeHost(tmp_path)
    builtin_demo = paths.builtin_features_dir().parent / "feature_demo"
    core_builtin = paths.builtin_features_dir() / "fun.self-talk"
    trusted = tmp_path / "mods" / "fun.festival"
    trusted.mkdir(parents=True)
    (trusted / ".trusted").write_text("", encoding="utf-8")
    addon = tmp_path / "mods" / "fun.divination"
    addon.mkdir(parents=True)
    host.load_result = SimpleNamespace(
        mods=(
            _mod("core.feature-demo", "Feature seam demo", "功能接缝示例", builtin_demo),
            _mod("fun.self-talk", "Self talk bubbles", "自言自语", core_builtin),
            _mod("fun.festival", "Festival reminder", "节日提醒", trusted),
            _mod("fun.divination", "Daily fortune", "抽签", addon, enabled=False),
        ),
        contents=(),
        diagnostics=(),
    )
    return host


def test_mods_page_filters_base_and_addon(app, tmp_path):
    page = ModsPage(_host_with_mods(tmp_path))

    assert page.filter_combo.count() == 3
    assert page.mods_list.count() == 4

    page.filter_combo.setCurrentIndex(1)
    assert page.filter_combo.currentData() == "base"
    assert page.mods_list.count() == 2
    base_texts = [
        page.mods_list.item(row).text() for row in range(page.mods_list.count())
    ]
    assert any(text.startswith("功能接缝示例 · core.feature-demo") for text in base_texts)
    assert any(text.startswith("自言自语 · fun.self-talk") for text in base_texts)
    assert all("节日提醒" not in text for text in base_texts)

    page.filter_combo.setCurrentIndex(2)
    assert page.mods_list.count() == 2
    addon_texts = [
        page.mods_list.item(row).text() for row in range(page.mods_list.count())
    ]
    assert any(text.startswith("抽签 · fun.divination") for text in addon_texts)
    assert any(text.startswith("节日提醒 · fun.festival") for text in addon_texts)
    assert any("已停用" in text for text in addon_texts)

    page.filter_combo.setCurrentIndex(0)
    assert page.mods_list.count() == 4


def test_core_features_are_listed_as_merged_into_core(app, tmp_path):
    page = ModsPage(_host_with_mods(tmp_path))
    rows = {
        page.mods_list.item(row).data(Qt.ItemDataRole.UserRole): row
        for row in range(page.mods_list.count())
    }

    core_row = rows["fun.self-talk"]
    assert "已并入 Core" in page.mods_list.item(core_row).text()
    page.mods_list.setCurrentRow(core_row)
    assert page.enable_button.isEnabled() is False
    assert page.disable_button.isEnabled() is False
    assert page.remove_button.isEnabled() is False
    assert "设置见对应 Core 设置页" in page.detail_label.text()

    plain_base_row = rows["core.feature-demo"]
    page.mods_list.setCurrentRow(plain_base_row)
    assert "已并入 Core" not in page.mods_list.item(plain_base_row).text()
    assert page.disable_button.isEnabled() is True
    assert page.remove_button.isEnabled() is True


def test_shipped_mod_cannot_be_removed_from_the_page(app, tmp_path):
    page = ModsPage(_host_with_mods(tmp_path))
    rows = {
        page.mods_list.item(row).data(Qt.ItemDataRole.UserRole): row
        for row in range(page.mods_list.count())
    }

    trusted_row = rows["fun.festival"]
    page.mods_list.setCurrentRow(trusted_row)
    assert page.remove_button.isEnabled() is False
    assert "随安装程序卸载" in page.detail_label.text()
    assert "Festival reminder" in page.detail_label.text()
    assert "ID：fun.festival" in page.detail_label.text()

    addon_row = rows["fun.divination"]
    page.mods_list.setCurrentRow(addon_row)
    assert page.remove_button.isEnabled() is True
    assert "随安装程序卸载" not in page.detail_label.text()


# ---------------------------------------------------------------- manifest 中文名
def _write_pack(root: Path, extra: dict | None = None) -> Path:
    pack = root / "demo.one"
    (pack / "host").mkdir(parents=True, exist_ok=True)
    (pack / "host" / "factory.py").write_text(
        "def create_host(context):\n    return None\n", encoding="utf-8"
    )
    payload = {
        "schema": 1,
        "kind": "feature",
        "id": "demo.one",
        "name": "Demo one",
        "version": "1.0.0",
        "api_version": "1",
        "entrypoint": "host/factory.py:create_host",
    }
    payload.update(extra or {})
    (pack / "mod.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return pack


def test_manifest_reads_name_zh(tmp_path):
    manifest, warnings = load_manifest(_write_pack(tmp_path, {"name_zh": "示例扩展"}))
    assert manifest is not None
    assert manifest.name_zh == "示例扩展"
    assert warnings == []


def test_manifest_without_name_zh_is_still_valid(tmp_path):
    manifest, warnings = load_manifest(_write_pack(tmp_path))
    assert manifest is not None
    assert manifest.name_zh == ""
    assert warnings == []


@pytest.mark.parametrize("value", [12, "", "   ", None])
def test_invalid_name_zh_falls_back_with_a_warning(tmp_path, value):
    manifest, warnings = load_manifest(_write_pack(tmp_path, {"name_zh": value}))
    assert manifest is not None
    assert manifest.name_zh == ""
    assert "name_zh invalid; ignored" in warnings


def test_long_name_zh_is_truncated(tmp_path):
    manifest, warnings = load_manifest(_write_pack(tmp_path, {"name_zh": "备" * 200}))
    assert manifest is not None
    assert len(manifest.name_zh) == 128
    assert any("name_zh" in warning for warning in warnings)


# ---------------------------------------------------------------- 设置页规格
def test_trusted_installer_pack_is_an_addon(tmp_path):
    import shutil

    pack = tmp_path / "mods" / "fun.divination"
    shutil.copytree(EXAMPLES / "fun.divination", pack)
    (pack / ".trusted").write_text("", encoding="utf-8")
    manifest, problems = load_manifest(pack)
    assert manifest is not None and problems == []

    manager = feature_mod.FeatureManager(HostPorts())
    assert manager.load(
        pack=pack, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    ) == []
    spec = next(
        spec for spec in manager.settings_pages() if spec.owner == "fun.divination"
    )
    assert spec.group == "addon"


def test_settings_page_spec_defaults_group_to_base():
    spec = SettingsPageSpec("x", "标题", lambda host: None)
    assert spec.group == "base"
    assert spec.owner == ""
    assert spec.label == ""
    assert spec.host_page == ""


def test_feature_pages_carry_label_owner_and_group():
    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load_builtin_features()
    assert diagnostics == []
    specs = {spec.id: spec for spec in manager.settings_pages()}
    assert specs["self_talk"].label == "自言自语"
    assert specs["self_talk"].owner == "fun.self-talk"
    assert specs["self_talk"].group == "core"
    assert specs["self_talk"].host_page == "interaction"

    pack = EXAMPLES / "fun.divination"
    manifest, problems = load_manifest(pack)
    assert manifest is not None and problems == []
    assert manager.load(
        pack=pack, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    ) == []
    addon_spec = next(
        spec for spec in manager.settings_pages() if spec.owner == "fun.divination"
    )
    assert addon_spec.label == "抽签"
    assert addon_spec.group == "addon"
    assert addon_spec.host_page == ""
