# -*- coding: utf-8 -*-
"""设置页「扩展管理」域：域页装配 + 宿主面（谁能动活桌宠）的真窗口行为。

交付验收走真实 ``ModernSettingsDialog`` 这个公开 seam（与
``tests/test_settings_page_guide.py`` 同一纪律）；宿主面的"活桌宠"用真实运行时标记 +
真实槽档案伪造，**不 mock 自己的判定函数**——那等于拿被测实现自证。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pet.modern_settings_dialog as settings_mod
from pet import catalog, pet_profiles, settings_mod_domain, slot_manager
from pet.config import Config
from pet.mod_center_ui import ModCenterWidget
from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow
from pet.settings_mod_domain import DialogModHost, USE_HINT

app = QApplication.instance() or QApplication([])

_DOMAIN = "扩展管理"


class FakeWindow(QWidget):
    """最小桌宠窗口：只兑现「换装入口」与「当前素材目录」两件宿主面。"""

    def __init__(self, asset_dir: Path | None = None):
        super().__init__()
        self.lib = SimpleNamespace(_asset_dir=asset_dir) if asset_dir is not None else None
        self.switched: list[str] = []

    def on_switch_character(self, character_id: str) -> None:
        self.switched.append(character_id)


def _write_package(root: Path, *, character_id: str = "demo", version: str = "1.0.0") -> Path:
    package = root / "package"
    videos = package / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    (videos / "idle.webm").write_bytes(b"test-video")
    (package / "manifest.json").write_text(
        json.dumps({"id": character_id, "name": character_id.title(), "version": version}),
        encoding="utf-8")
    return package


@pytest.fixture
def env(tmp_path, monkeypatch):
    """托管根 = ``<tmp>/<APP_DIR_NAME>``，并由 catalog 当作外部角色根（生产口径）。"""
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    data_root = tmp_path / "dsh-pet-standalone"
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [data_root / "characters"])
    return data_root


def _dialog(env, *, parent=None, include_ai=False):
    dialog = ModernSettingsDialog(Config(base=env.parent), parent, include_ai=include_ai)
    return dialog


def _page(dialog) -> QWidget:
    index = next(i for i in range(dialog.sidebar.count())
                 if dialog.sidebar.item(i).text() == _DOMAIN)
    return dialog.pages.widget(index)


def pump(predicate, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        wait = QEventLoop()
        QTimer.singleShot(20, wait.quit)
        wait.exec()
    assert predicate()


# ------------------------------------------------------------------ 域页装配

def test_domain_page_carries_the_mod_center(env):
    dialog = _dialog(env)
    try:
        page = _page(dialog)
        widget = page.findChild(ModCenterWidget, "modCenter")
        assert widget is not None
        assert widget is dialog.mod_center
        row = page.findChild(SettingRow, "settingRow_mod_center")
        assert row is not None and row.control is widget
        section = page.findChild(settings_mod_domain.SettingsSection)
        assert section.description_label.text().strip(), "新分组必须在 SECTION_GUIDE 里有描述"
    finally:
        dialog.close()


def test_domain_order_and_nav_entry(env):
    dialog = _dialog(env)
    try:
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        assert labels.index(_DOMAIN) == labels.index("文件识别") + 1
        from pet.settings_widgets import SETTINGS_DOMAIN_NAV
        assert ("扩展管理", "tools") in SETTINGS_DOMAIN_NAV
    finally:
        dialog.close()


def test_the_domain_is_not_a_settings_row_of_another_page(env):
    """一行只属一个域：不允许落进「待分类（开发期）」，也不许在别的域页里再出现一份。"""
    dialog = _dialog(env)
    try:
        row = dialog.findChild(SettingRow, "settingRow_mod_center")
        owners = [dialog.sidebar.item(i).text() for i in range(dialog.pages.count())
                  if dialog.pages.widget(i).isAncestorOf(row)]
        assert owners == [_DOMAIN]
        assert not [widget for widget in dialog.findChildren(ModCenterWidget)][1:]
    finally:
        dialog.close()


def test_search_alias_lands_on_the_mod_center_row(env):
    """搜「插件」/「MOD」：候选里有「扩展管理」域那一行，回车可达且跳进该域。"""
    dialog = _dialog(env)
    try:
        for query in ("插件", "mod"):
            dialog.search_edit.setText("")
            app.processEvents()
            dialog.search_edit.setText(query)
            app.processEvents()
            matches = list(dialog._search_matches)
            keys = [row.objectName() for row in matches]
            # 「插件」也是别的行 hint 里的词（foobar 歌词行的「第三方插件名」）——
            # 关键词命中是既有行为，这里只要求本域那一行在候选里。
            assert "settingRow_mod_center" in keys, (query, keys)
            for _press in range(len(matches)):
                if dialog._search_matches[dialog._search_index].objectName() == "settingRow_mod_center":
                    break
                QTest.keyClick(dialog.search_edit, Qt.Key.Key_Return)
                app.processEvents()
            assert dialog._search_matches[dialog._search_index].objectName() == "settingRow_mod_center"
            assert dialog.sidebar.currentItem().text() == _DOMAIN
    finally:
        dialog.close()


def test_routed_config_shape_is_supported(env):
    """主进程/子宠页传给设置窗的是**路由视图**（``SlotRoutedConfig``），宿主面同样要能用。

    这是生产形态：``Config`` 直传只在测试里出现。路由视图的 ``dir``/``instance_id``
    走 slot 身份那份，托管根必须取它而不是主配置。
    """
    from pet.settings_slot_config import route_settings_config

    routed = route_settings_config(Config(base=env.parent, instance_id="slot-0"))
    dialog = ModernSettingsDialog(routed, None, include_ai=False)
    try:
        assert dialog.mod_host.data_root == Path(routed.dir)
        assert [row.key for row in dialog.mod_controller.entries()]
        assert dialog.mod_center.rows  # 清单行真的画出来了
    finally:
        dialog.close()


# ------------------------------------------------------- 导入 / 启停 / 删除

def test_import_enable_and_delete_through_the_real_dialog(env):
    dialog = _dialog(env)
    try:
        controller = dialog.mod_controller
        source = _write_package(env.parent / "source")
        results = []
        controller.result.connect(lambda _key, outcome: results.append(outcome))
        assert controller.import_source(source)
        pump(lambda: not controller.busy)
        assert results[-1].success, results[-1].message
        row = dialog.mod_center.rows["角色资源:demo"]
        assert not row.entry.enabled
        # 首次导入没有"被更新的那一行"可挂，结果落在汇总行（与 DLC 同一协议）
        assert dialog.mod_center.summary.text().startswith("已导入")

        row.toggle.click()
        pump(lambda: not controller.busy)
        assert dialog.mod_controller.resources._entry("demo").enabled
        assert dialog.mod_center.rows["角色资源:demo"].toggle.text() == "停用"

        assert controller.perform("delete", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        assert all(outcome.success for outcome in results), [o.message for o in results]
        assert source.is_dir()
        assert "角色资源:demo" not in dialog.mod_center.rows
    finally:
        dialog.close()


def test_import_of_a_feature_package_reports_the_truthful_reason(env):
    dialog = _dialog(env)
    try:
        package = _write_package(env.parent / "feature")
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(kind="feature", execution_kind="host-worker")
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert dialog.mod_controller.import_source(package) is False
        assert dialog.mod_center.summary.text().startswith("本版本只支持角色资源包")
    finally:
        dialog.close()


# ----------------------------------------------------------- 「使用」入口

def test_use_button_is_greyed_out_when_no_pet_window_is_attached(env):
    """没有窗口可依附（独立设置进程）时按钮置灰并写明原因，而不是点了才失败。"""
    dialog = _dialog(env)
    try:
        host = dialog.mod_host
        assert host.can_use is False
        assert host.use_hint == USE_HINT
        row = dialog.mod_center.rows["角色资源:resource:builtin:shenshen"]
        assert not row.settings.isEnabled()
        assert row.settings.toolTip() == USE_HINT
    finally:
        dialog.close()


def test_use_is_deferred_to_the_close_of_the_settings_window(env):
    """「使用」记下请求、关窗时执行：换角色会重建桌宠窗口，而设置窗是它的子窗口。"""
    window = FakeWindow()
    dialog = _dialog(env, parent=window)
    dialog.show()
    app.processEvents()
    try:
        controller = dialog.mod_controller
        controller.import_source(_write_package(env.parent / "source"))
        pump(lambda: not controller.busy)
        controller.perform("enable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        assert dialog.mod_host.can_use is True
        results = []
        controller.result.connect(lambda _key, outcome: results.append(outcome))
        controller.perform("use", ["角色资源:demo"])
        assert window.switched == [], "当场换装会把设置窗（旧窗的子窗口）一起销毁"
        assert results[-1].success and "关闭设置页后生效" in results[-1].message
    finally:
        dialog.close()
        app.processEvents()
    assert window.switched == ["demo"], "关窗时必须执行记下的换装"


def test_pending_use_is_recorded_once_and_cleared(env):
    """重复点「使用」不叠加请求；执行过一次之后关窗不再重复动作。"""
    window = FakeWindow()
    dialog = _dialog(env, parent=window)
    dialog.show()
    app.processEvents()
    try:
        controller = dialog.mod_controller
        controller.import_source(_write_package(env.parent / "source"))
        pump(lambda: not controller.busy)
        controller.perform("enable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        controller.perform("use", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        controller.perform("use", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        assert dialog.mod_host.pending_use == "demo"
    finally:
        dialog.close()
        app.processEvents()
    assert window.switched == ["demo"]
    dialog.mod_host.apply_pending_use()          # 幂等：没有请求就什么都不做
    assert window.switched == ["demo"]


def test_use_is_a_no_op_when_the_pet_already_renders_that_character(env):
    window = FakeWindow()
    dialog = _dialog(env, parent=window)
    try:
        controller = dialog.mod_controller
        controller.import_source(_write_package(env.parent / "source"))
        pump(lambda: not controller.busy)
        controller.perform("enable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        dialog.config.set("character", "demo")
        results = []
        controller.result.connect(lambda _key, outcome: results.append(outcome))
        controller.perform("use", ["角色资源:demo"])
        assert dialog.mod_host.pending_use == ""
        assert window.switched == []
        assert results[-1].success and "已经在该角色上" in results[-1].message
    finally:
        dialog.close()


# --------------------------------------------------- 活桌宠占用（放行判据）

def _write_runtime_marker(data_root: Path, *, pid: int | None = None) -> Path:
    data_root.mkdir(parents=True, exist_ok=True)
    marker = slot_manager.runtime_marker_path(data_root, "slot-0", versioned=True)
    marker.write_text(json.dumps({"pid": os.getpid() if pid is None else pid}), encoding="utf-8")
    return marker


def test_live_pet_without_window_is_seen_through_the_runtime_marker(env):
    data_root = env
    marker = _write_runtime_marker(data_root)
    profile = pet_profiles.write_profile_settings(data_root, 0, {"character": "demo"})
    assert profile.ok, profile
    dialog = _dialog(env)
    try:
        usage = dialog.mod_host.live_usage()
        assert usage.verified is True
        assert "demo" in usage.character_ids
        # 该角色包正在被这只宠使用 ⇒ 停用被拒（要用户先换装）
        source = _write_package(env.parent / "source")
        controller = dialog.mod_controller
        controller.import_source(source)
        pump(lambda: not controller.busy)
        controller.perform("enable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        entry = controller.resources._entry("demo")
        results = []
        controller.result.connect(lambda _key, outcome: results.append(outcome))
        assert controller.perform("disable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        assert not results[-1].success and "正在使用" in results[-1].message
        assert controller.resources._entry("demo").enabled

        # 换到别的角色后，同一份清单即可停用（判据跟着档案走，不是写死的开关）
        assert pet_profiles.write_profile_settings(data_root, 0, {"character": "shenshen"}).ok
        assert controller.perform("disable", ["角色资源:demo"])
        pump(lambda: not controller.busy)
        assert results[-1].success, results[-1].message
        assert not controller.resources._entry("demo").enabled
        assert (data_root / "mod-disabled" / "demo").is_dir()   # 停用 = 搬出扫描根
    finally:
        dialog.close()
        marker.unlink(missing_ok=True)


def test_dead_pet_marker_does_not_block_operations(env):
    data_root = env
    marker = _write_runtime_marker(data_root, pid=999_999_999)
    assert pet_profiles.write_profile_settings(data_root, 0, {"character": "demo"}).ok
    dialog = _dialog(env)
    try:
        usage = dialog.mod_host.live_usage()
        assert usage.verified is True
        assert usage.character_ids == ()  # 死进程的标记不算活桌宠
    finally:
        dialog.close()
        marker.unlink(missing_ok=True)


def test_unreadable_owner_character_is_reported_as_unverified(env, monkeypatch):
    """读不出「谁在用」时按可能在用处理：verified=False（宁可拒绝，不猜）。"""
    _write_runtime_marker(env)
    dialog = _dialog(env)
    try:
        host: DialogModHost = dialog.mod_host
        monkeypatch.setattr(settings_mod_domain, "_slot_character", lambda *_args: "")
        monkeypatch.setattr(DialogModHost, "_owner_character", lambda _self: "")
        usage = host.live_usage()
        assert usage.verified is False
        assert usage.asset_dirs == ()
    finally:
        dialog.close()
