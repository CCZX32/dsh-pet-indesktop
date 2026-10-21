from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
)

from ...mods.feature import CORE_FEATURE_IDS
from .base import SettingsPage, make_button, make_checkbox

FILTER_ALL = "all"
FILTER_BASE = "base"
FILTER_ADDON = "addon"
FILTERS = (
    ("全部扩展", FILTER_ALL),
    ("基础扩展", FILTER_BASE),
    ("加装扩展", FILTER_ADDON),
)


class ModsPage(SettingsPage):
    title = "扩展管理"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        installer, mod_state = self._load_api()
        self._supported = installer is not None and mod_state is not None
        self._mod_states: dict[str, bool] = {}
        self._trusted_ids: set[str] = set()
        self._core_ids: set[str] = set()

        if not self._supported:
            self.add_note("扩展 API 不可用，无法管理扩展。请检查 petcore 安装是否完整。")

        feature_card = self.section("功能扩展")
        self.feature_check = make_checkbox(self)
        config = getattr(host, "config", None)
        self._initial_feature = bool(config.get("allow_feature_mods")) if config is not None else False
        self.feature_check.setChecked(self._initial_feature)
        self.feature_check.toggled.connect(self._on_feature_toggled)
        feature_card.add_row(
            "允许功能扩展",
            self.feature_check,
            "仅从用户数据目录加载 feature 包；保存后点「重新加载扩展」生效。",
        )

        card = self.section("已安装的扩展")
        self.filter_combo = QComboBox(self)
        self.filter_combo.setObjectName("modsFilter")
        self.filter_combo.setAccessibleName("扩展筛选")
        for label, value in FILTERS:
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        card.add_row(
            "显示范围",
            self.filter_combo,
            "「基础扩展」随程序内置（其中已并入 Core 的会标注出来）；"
            "「加装扩展」来自安装向导勾选投放或手动导入。",
        )
        self.mods_list = QListWidget(self)
        self.mods_list.setObjectName("modsList")
        self.mods_list.setAccessibleName("已安装的扩展")
        self.mods_list.setMinimumHeight(190)
        self.mods_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        card.add_widget(self.mods_list)

        self.enable_button = make_button("启用", self)
        self.enable_button.clicked.connect(lambda: self._set_enabled(True))
        self.disable_button = make_button("停用", self)
        self.disable_button.clicked.connect(lambda: self._set_enabled(False))
        self.import_zip_button = make_button("导入 ZIP", self)
        self.import_zip_button.setToolTip("从 .zip 扩展包安装")
        self.import_zip_button.clicked.connect(self._import_zip)
        self.import_dir_button = make_button("导入目录", self)
        self.import_dir_button.setToolTip("从本地目录安装扩展")
        self.import_dir_button.clicked.connect(self._import_dir)
        self.remove_button = make_button("卸载", self)
        self.remove_button.clicked.connect(self._remove)
        self.reload_button = make_button("重新加载扩展", self)
        self.reload_button.clicked.connect(self._reload)
        # 竖向导航把内容区压窄了：按钮按语义分三行两列，窄窗口也不会被挤出可视区。
        card.add_buttons([self.enable_button, self.disable_button])
        card.add_buttons([self.import_zip_button, self.import_dir_button])
        card.add_buttons([self.remove_button, self.reload_button])

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("settingHint")
        self.status_label.setWordWrap(True)
        card.add_widget(self.status_label)

        self.detail_label = QLabel("", self)
        self.detail_label.setObjectName("settingHint")
        self.detail_label.setWordWrap(True)
        card.add_widget(self.detail_label)

        diagnostics_card = self.section("诊断信息")
        self.diagnostics_view = QPlainTextEdit(self)
        self.diagnostics_view.setReadOnly(True)
        self.diagnostics_view.setAccessibleName("诊断信息")
        self.diagnostics_view.setMinimumHeight(110)
        diagnostics_card.add_widget(self.diagnostics_view)

        self.mods_list.currentRowChanged.connect(self._update_buttons)
        self._refresh()
        if not self._supported:
            self._set_controls_enabled(False)

    def _load_api(self):
        try:
            from ...mods import install as installer
            from ...mods import state as mod_state
        except Exception:
            return None, None
        return installer, mod_state

    def _root(self) -> Path:
        return Path(str(getattr(self.host, "root", Path.cwd())))

    def _mods(self) -> tuple:
        result = getattr(self.host, "load_result", None)
        return tuple(getattr(result, "mods", ()) or ())

    def _refresh(self) -> None:
        self._refresh_list()
        self._refresh_diagnostics()

    def _on_filter_changed(self, _index: int) -> None:
        self._refresh_list()

    def _current_filter(self) -> str:
        data = self.filter_combo.currentData()
        return str(data) if data else FILTER_ALL

    def _classify(self, mod) -> str:
        manifest = getattr(mod, "manifest", None)
        mod_id = str(getattr(mod, "id", "") or getattr(manifest, "id", "") or "")
        if mod_id in CORE_FEATURE_IDS:
            return FILTER_BASE
        path = getattr(mod, "path", None)
        if self._in_builtin(path):
            return FILTER_BASE
        # 安装器投放的 `.trusted` 包与用户导入都算「加装」：它们不是 Core 的一部分。
        return FILTER_ADDON

    def _in_builtin(self, path) -> bool:
        if path is None:
            return False
        try:
            from ... import paths

            root = paths.builtin_features_dir().parent.resolve()
            candidate = Path(path).resolve()
        except (OSError, RuntimeError):
            return False
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

    def _refresh_list(self) -> None:
        selected = self._selected_mod()
        self.mods_list.blockSignals(True)
        self.mods_list.clear()
        self._mod_states = {}
        self._trusted_ids = set()
        self._core_ids = set()
        current_filter = self._current_filter()
        for mod in self._mods():
            manifest = getattr(mod, "manifest", None)
            mod_id = str(getattr(mod, "id", "") or getattr(manifest, "id", "") or "")
            if not mod_id:
                continue
            if current_filter != FILTER_ALL and self._classify(mod) != current_filter:
                continue
            name_zh = str(getattr(manifest, "name_zh", "") or "")
            name = str(getattr(manifest, "name", "") or "")
            display = name_zh or name or mod_id
            version = str(getattr(manifest, "version", "") or "")
            enabled = bool(getattr(mod, "enabled", False))
            status = "已启用" if enabled else "已停用"
            text = f"{display} · {mod_id}"
            if version:
                text += f" · v{version}"
            text += f" · {status}"
            core = mod_id in CORE_FEATURE_IDS
            if core:
                text += " · 已并入 Core"
                self._core_ids.add(mod_id)
            trusted = self._is_trusted(getattr(mod, "path", None))
            if trusted:
                text += " · 随安装包"
                self._trusted_ids.add(mod_id)
            item = QListWidgetItem(text, self.mods_list)
            item.setData(Qt.ItemDataRole.UserRole, mod_id)
            if core:
                item.setToolTip("已并入 Core：设置见对应 Core 设置页")
            elif trusted:
                item.setToolTip("随安装程序投放，卸载请使用安装程序")
            self._mod_states[mod_id] = enabled
        if self.mods_list.count() == 0:
            placeholder = QListWidgetItem(self._empty_text(current_filter), self.mods_list)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.mods_list.blockSignals(False)
        if selected is not None:
            for row in range(self.mods_list.count()):
                if self.mods_list.item(row).data(Qt.ItemDataRole.UserRole) == selected:
                    self.mods_list.setCurrentRow(row)
                    break
        self._update_buttons(self.mods_list.currentRow())

    def _empty_text(self, current_filter: str) -> str:
        if not self._supported:
            return "（扩展 API 不可用）"
        if current_filter != FILTER_ALL:
            return "（该分类暂无扩展）"
        return "（未安装扩展）"

    def _is_trusted(self, path) -> bool:
        if path is None:
            return False
        try:
            from ...mods import trust as mod_trust
        except Exception:
            return False
        try:
            return mod_trust.is_trusted(path)
        except Exception:
            return False

    def _update_details(self, mod_id: str | None) -> None:
        if mod_id is None:
            self.detail_label.setText("")
            return
        for mod in self._mods():
            manifest = getattr(mod, "manifest", None)
            if str(getattr(mod, "id", "") or "") != mod_id:
                continue
            name_zh = str(getattr(manifest, "name_zh", "") or "")
            name = str(getattr(manifest, "name", "") or "")
            display = name_zh or name or mod_id
            kind = str(getattr(manifest, "kind", "") or "")
            version = str(getattr(manifest, "version", "") or "")
            path = getattr(mod, "path", None)
            parts = [f"{display} · {kind or '未知类型'}" + (f" · v{version}" if version else "")]
            identity = f"ID：{mod_id}"
            if name and name != display:
                identity += f" · 英文名：{name}"
            parts.append(identity)
            if path is not None:
                parts.append(f"位置：{path}")
            core = mod_id in self._core_ids
            trusted = self._is_trusted(path)
            if core:
                parts.append("状态：已并入 Core，不再作为扩展启用/停用；设置见对应 Core 设置页")
            elif trusted:
                parts.append("状态：随安装程序卸载，不能在此移除")
            if kind == "feature" and not core:
                if trusted:
                    parts.append("授权：随安装包投放，已启用")
                elif self._feature_allowed():
                    parts.append("授权：按「允许功能扩展」启用")
                else:
                    parts.append("授权：未授权，功能不会加载")
            self.detail_label.setText("\n".join(parts))
            return
        self.detail_label.setText("")

    def _feature_allowed(self) -> bool:
        config = getattr(self.host, "config", None)
        getter = getattr(config, "get", None)
        if not callable(getter):
            return False
        try:
            return bool(getter("allow_feature_mods"))
        except Exception:
            return False

    def _refresh_diagnostics(self) -> None:
        diagnostics = [str(item) for item in (getattr(self.host, "diagnostics", None) or [])]
        self.diagnostics_view.setPlainText("\n".join(diagnostics) if diagnostics else "（无诊断信息）")

    def _selected_mod(self) -> str | None:
        item = self.mods_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return str(data) if data is not None else None

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.filter_combo,
            self.mods_list,
            self.enable_button,
            self.disable_button,
            self.import_zip_button,
            self.import_dir_button,
            self.remove_button,
        ):
            widget.setEnabled(enabled)

    def _update_buttons(self, _row: int = -1) -> None:
        if not self._supported:
            self._set_controls_enabled(False)
            self._update_details(None)
            return
        mod_id = self._selected_mod()
        enabled = self._mod_states.get(mod_id) if mod_id is not None else None
        core = mod_id is not None and mod_id in self._core_ids
        self.enable_button.setEnabled(enabled is False and not core)
        self.disable_button.setEnabled(enabled is True and not core)
        self.remove_button.setEnabled(
            mod_id is not None and not core and mod_id not in self._trusted_ids
        )
        self._update_details(mod_id)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _reload(self) -> None:
        reload_mods = getattr(self.host, "reload_mods", None)
        if callable(reload_mods):
            try:
                reload_mods()
            except Exception as exc:
                self._set_status(f"重新加载扩展失败：{exc}")
        self._refresh()

    def _set_enabled(self, enabled: bool) -> None:
        mod_id = self._selected_mod()
        _, mod_state = self._load_api()
        if mod_id is None or mod_state is None:
            return
        try:
            mod_state.set_enabled(self._root(), mod_id, enabled)
        except Exception as exc:
            self._set_status(f"操作失败：{exc}")
            return
        self._set_status(f"已{'启用' if enabled else '停用'} {mod_id}")
        self._reload()

    def _import_zip(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择扩展包", "", "扩展包 (*.zip);;所有文件 (*)")
        if path:
            self._install(Path(path))

    def _import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择扩展目录")
        if path:
            self._install(Path(path))

    def _install(self, source: Path) -> None:
        installer, _ = self._load_api()
        if installer is None:
            return
        try:
            ok, message = installer.install(source, self._root())
        except Exception as exc:
            ok, message = False, f"安装失败：{exc}"
        self._set_status(message)
        if ok:
            self._reload()

    def _remove(self) -> None:
        mod_id = self._selected_mod()
        installer, _ = self._load_api()
        if mod_id is None or installer is None or mod_id in self._trusted_ids:
            return
        answer = QMessageBox.question(
            self,
            "卸载扩展",
            f"确定要卸载扩展「{mod_id}」吗？这会删除扩展目录中的文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            ok, message = installer.remove(self._root(), mod_id)
        except Exception as exc:
            ok, message = False, f"卸载失败：{exc}"
        self._set_status(message)
        if ok:
            self._reload()

    def _on_feature_toggled(self, checked: bool) -> None:
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("allow_feature_mods", bool(checked))
        self._set_status("功能扩展开关已改变；保存后点「重新加载扩展」生效。")
        self.changed.emit()

    def dirty(self) -> bool:
        return self.feature_check.isChecked() != self._initial_feature

    def confirm_save(self) -> None:
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("allow_feature_mods", self.feature_check.isChecked())
        self._initial_feature = self.feature_check.isChecked()

    def discard_changes(self) -> None:
        self.feature_check.blockSignals(True)
        self.feature_check.setChecked(self._initial_feature)
        self.feature_check.blockSignals(False)
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("allow_feature_mods", self._initial_feature)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return [
            "扩展",
            "模组",
            "mod",
            "插件",
            "安装",
            "卸载",
            "启用",
            "停用",
            "诊断",
            "基础扩展",
            "加装扩展",
            "已并入 Core",
            "install",
            "remove",
        ]
