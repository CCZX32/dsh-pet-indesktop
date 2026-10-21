from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from ...engine.geometry import DEFAULT_SCALE, SCALE_MAX, SCALE_MIN, SCALE_STEPS
from ...platform import autostart, hotkey_spec, screens
from .base import (
    SettingsPage,
    build_embedded_page,
    embedded_page_specs,
    make_button,
    make_checkbox,
    make_slider,
    make_spin,
)


def _clamped_scale(value: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, float(value)))


def _percent(scale: float) -> int:
    return int(round(_clamped_scale(scale) * 100))


class GeneralPage(SettingsPage):
    title = "常规"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._autostart_supported = sys.platform == "win32"
        self._autostart_initial = False
        if self._autostart_supported:
            try:
                self._autostart_initial = bool(autostart.is_enabled())
            except Exception:
                self._autostart_initial = False
        self._draft_character: str | None = None
        self._draft_autostart = self._autostart_initial

        card = self.section("桌宠")
        self.character_combo = QComboBox(self)
        self.character_combo.setMinimumWidth(220)
        for spec in self.host.characters():
            self.character_combo.addItem(str(spec.name), str(spec.id))
        self._select_character(str(self.config().get("character") or ""))
        self._initial_character = self._current_character()
        self.character_combo.currentIndexChanged.connect(self._on_character_changed)
        card.add_row("角色", self.character_combo, "选择桌宠当前使用的角色。")

        self.autostart_check = make_checkbox(self)
        self.autostart_check.setChecked(self._autostart_initial)
        if not self._autostart_supported:
            self.autostart_check.setEnabled(False)
            self.autostart_check.setToolTip("仅在 Windows 上可用。")
        hint = "登录 Windows 后自动运行 petcore。" if self._autostart_supported else "仅在 Windows 上可用。"
        card.add_row("开机自动启动", self.autostart_check, hint)

        data_card = self.section("数据")
        open_button = make_button("打开数据目录", self)
        open_button.clicked.connect(self._open_data_dir)
        data_card.add_row("数据目录", open_button, "打开保存配置、日志和扩展的目录。")

        import_button = make_button("导入角色目录", self)
        import_button.clicked.connect(self._import_character)
        self.import_status = QLabel("支持包含 videos/ 和 manifest.json 的角色目录。", self)
        self.import_status.setObjectName("settingHint")
        self.import_status.setWordWrap(True)
        data_card.add_row(
            "角色资源包",
            import_button,
            "选择角色目录后生成并安装 content mod；导入成功后可在角色下拉框切换。",
        )
        data_card.add_widget(self.import_status)

        app_card = self.section("应用")
        quit_button = make_button("退出桌宠", self)
        quit_button.clicked.connect(self._quit_app)
        app_card.add_row("退出", quit_button, "关闭桌宠、托盘图标与所有扩展。")

    def config(self):
        return self.host.config

    def _select_character(self, character_id: str) -> None:
        if self.character_combo.count() == 0:
            return
        index = self.character_combo.findData(character_id)
        self.character_combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_character_changed(self, _index: int) -> None:
        character = self._current_character()
        if character:
            self.config().set("character", character)
        self.changed.emit()

    def _open_data_dir(self) -> None:
        opener = getattr(self.host, "open_data_dir", None)
        if callable(opener):
            opener()

    def _import_character(self) -> None:
        source = QFileDialog.getExistingDirectory(
            self, "选择角色资源目录", str(getattr(self.host, "root", ""))
        )
        if not source:
            return
        try:
            from ...content.importer import install_character_source

            ok, message, character_id = install_character_source(
                Path(source), self.host.root
            )
        except Exception as exc:
            ok, message, character_id = False, f"导入失败：{type(exc).__name__}: {exc}", None
        if not ok or not character_id:
            self.import_status.setText(str(message))
            QMessageBox.warning(self, "导入角色", str(message))
            return
        reloader = getattr(self.host, "reload_mods", None)
        if callable(reloader):
            reloader()
        index = self.character_combo.findData(character_id)
        if index < 0:
            for spec in self.host.characters():
                self.character_combo.addItem(str(spec.name), str(spec.id))
            index = self.character_combo.findData(character_id)
        if index >= 0:
            self.character_combo.setCurrentIndex(index)
        self.import_status.setText(f"已导入：{character_id}")

    def _quit_app(self) -> None:
        answer = QMessageBox.question(
            self,
            "退出桌宠",
            "确定要退出桌宠吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        quitter = getattr(self.host, "quit_app", None)
        if callable(quitter):
            quitter()

    def _current_character(self) -> str | None:
        if self.character_combo.count() == 0:
            return None
        data = self.character_combo.currentData()
        return str(data) if data is not None else None

    def dirty(self) -> bool:
        if self._current_character() != self._initial_character:
            return True
        return self._autostart_supported and self.autostart_check.isChecked() != self._autostart_initial

    def draft(self) -> None:
        self._draft_character = self._current_character()
        self._draft_autostart = self.autostart_check.isChecked()

    def confirm_save(self) -> None:
        if self._draft_character is not None:
            self.config().set("character", self._draft_character)
        if not self._autostart_supported or self._draft_autostart == self._autostart_initial:
            return
        try:
            changed = autostart.enable() if self._draft_autostart else autostart.disable()
        except Exception:
            changed = False
        if changed:
            self._autostart_initial = self._draft_autostart
            return
        self.autostart_check.setChecked(self._autostart_initial)
        QMessageBox.warning(self, "开机自动启动", "无法写入开机自启设置，请检查系统权限。")

    def discard_changes(self) -> None:
        self.character_combo.blockSignals(True)
        self._select_character(self._initial_character or "")
        self.character_combo.blockSignals(False)
        self.autostart_check.setChecked(self._autostart_initial)

    def keywords(self) -> list[str]:
        return [
            "常规",
            "角色",
            "开机",
            "启动",
            "自启",
            "数据目录",
            "退出",
            "general",
            "character",
            "autostart",
            "startup",
            "quit",
        ]


class AppearancePage(SettingsPage):
    title = "外观与交互"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._window = getattr(host, "window", None)
        self._initial_scale = _percent(float(self.config().get("scale") or DEFAULT_SCALE))
        self._initial_always_on_top = bool(self.config().get("always_on_top"))
        self._initial_click_through = bool(self.config().get("click_through"))
        self._initial_multi_screen = bool(self.config().get("multi_screen"))
        self._initial_edge_probe = bool(self.config().get("edge_probe_enabled"))
        self._initial_hotkey = str(self.config().get("hotkey_toggle_pet") or "")
        self._last_hotkey = self._initial_hotkey
        self._initial_ui_font_size = int(self.config().get("ui_font_size") or 13)
        self._initial_bubble_text_scale = int(self.config().get("bubble_text_scale") or 100)
        self._initial_stream_capture = bool(self.config().get("stream_capture_mode"))
        self._initial_visible = self._window_visible()

        scale_card = self.section("大小")
        scale_row = QWidget(self)
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(12)
        self.scale_slider = make_slider(scale_row)
        self.scale_slider.setRange(_percent(SCALE_MIN), _percent(SCALE_MAX))
        self.scale_spin = make_spin(scale_row)
        self.scale_spin.setRange(_percent(SCALE_MIN), _percent(SCALE_MAX))
        self.scale_spin.setSuffix(" %")
        self.scale_slider.setValue(self._initial_scale)
        self.scale_spin.setValue(self._initial_scale)
        self.scale_slider.valueChanged.connect(self._on_scale_percent)
        self.scale_spin.valueChanged.connect(self._on_scale_percent)
        scale_layout.addWidget(self.scale_slider, 1)
        scale_layout.addWidget(self.scale_spin)
        scale_card.add_row(
            "缩放",
            scale_row,
            f"拖动滑条或直接输入百分比，范围 {_percent(SCALE_MIN)}%–{_percent(SCALE_MAX)}%，实时生效。",
            expand=True,
        )
        preset_buttons = []
        for step in SCALE_STEPS:
            button = make_button(f"{_percent(step)}%", self)
            button.clicked.connect(lambda _checked=False, value=step: self._apply_scale(value))
            preset_buttons.append(button)
        reset_scale = make_button("恢复默认", self)
        reset_scale.clicked.connect(lambda: self._apply_scale(DEFAULT_SCALE))
        preset_buttons.append(reset_scale)
        scale_card.add_buttons(preset_buttons)

        card = self.section("外观")
        self.always_on_top_check = make_checkbox(self)
        self.always_on_top_check.setChecked(self._initial_always_on_top)
        self.always_on_top_check.toggled.connect(self._on_flags_changed)
        card.add_row("窗口置顶", self.always_on_top_check, "让桌宠始终显示在其他窗口之上。")

        self.click_through_check = make_checkbox(self)
        self.click_through_check.setChecked(self._initial_click_through)
        self.click_through_check.toggled.connect(self._on_flags_changed)
        card.add_row(
            "点击穿透",
            self.click_through_check,
            "影响所有桌宠：鼠标点击穿过桌宠，不再响应拖动与互动；开启后右键菜单点不到，可从托盘菜单关闭。",
        )

        self.stream_capture_check = make_checkbox(self)
        self.stream_capture_check.setChecked(self._initial_stream_capture)
        self.stream_capture_check.toggled.connect(self._on_stream_capture_changed)
        card.add_row(
            "直播捕获兼容",
            self.stream_capture_check,
            "影响所有桌宠，让 OBS / 直播姬能在窗口列表里枚举到桌宠。捕获方式请选 "
            "「Windows 10 (1903 及以上)」，BitBlt 会黑屏；多只桌宠的窗口都可单独捕获。",
        )

        self.visible_check = make_checkbox(self)
        self.visible_check.setChecked(self._initial_visible)
        self.visible_check.setEnabled(self._window is not None)
        self.visible_check.toggled.connect(self._on_visibility_changed)
        card.add_row("显示桌宠", self.visible_check, "取消勾选后桌宠隐藏；可从托盘或本设置重新显示。")

        self.edge_probe_check = make_checkbox(self)
        self.edge_probe_check.setChecked(self._initial_edge_probe)
        self.edge_probe_check.setEnabled(self._window is not None)
        self.edge_probe_check.toggled.connect(self._on_edge_probe_changed)
        card.add_row(
            "边缘探头",
            self.edge_probe_check,
            "贴到屏幕左/右缘后自动 45° 探头；点击拉直，5 秒后回到探头。",
        )

        self.hotkey_edit = QLineEdit(self)
        self.hotkey_edit.setPlaceholderText("例如 Ctrl+Alt+P（留空 = 不绑定）")
        self.hotkey_edit.setText(self._initial_hotkey)
        self.hotkey_edit.setMinimumWidth(220)
        self.hotkey_edit.editingFinished.connect(self._on_hotkey_finished)
        card.add_row(
            "显示/隐藏快捷键",
            self.hotkey_edit,
            "全局快捷键，至少包含一个修饰键；留空表示不绑定。",
        )

        text_card = self.section("文字")
        self.ui_font_size_spin = make_spin(self)
        self.ui_font_size_spin.setAccessibleName("界面字号")
        self.ui_font_size_spin.setRange(10, 18)
        self.ui_font_size_spin.setValue(self._initial_ui_font_size)
        self.ui_font_size_spin.valueChanged.connect(self._on_text_sizes_changed)
        text_card.add_row(
            "界面字号",
            self.ui_font_size_spin,
            "全局设置：同步调整设置页与所有桌宠的右键菜单字号。",
        )

        self.bubble_text_scale_spin = make_spin(self)
        self.bubble_text_scale_spin.setAccessibleName("对话气泡字号")
        self.bubble_text_scale_spin.setRange(50, 300)
        self.bubble_text_scale_spin.setSuffix(" %")
        self.bubble_text_scale_spin.setValue(self._initial_bubble_text_scale)
        self.bubble_text_scale_spin.valueChanged.connect(self._on_text_sizes_changed)
        text_card.add_row(
            "对话气泡字号",
            self.bubble_text_scale_spin,
            "气泡与文字一起等比放大。",
        )

        screen_card = self.section("屏幕与位置")
        self.multi_screen_check = make_checkbox(self)
        self.multi_screen_check.setChecked(self._initial_multi_screen)
        self.multi_screen_check.toggled.connect(self._on_flags_changed)
        screen_card.add_row("允许跨屏", self.multi_screen_check, "允许把桌宠拖到其他显示器；关闭时限制在当前屏幕。")
        self.screen_label = QLabel(self._screen_text(), self)
        self.screen_label.setObjectName("screenInfo")
        self.screen_label.setWordWrap(True)
        screen_card.add_widget(self.screen_label)

        primary_button = make_button("重置到主屏", self)
        primary_button.clicked.connect(self._move_to_primary)
        corner_button = make_button("回到右下角", self)
        corner_button.clicked.connect(self._return_corner)
        reset_button = make_button("重置位置", self)
        reset_button.clicked.connect(self._reset_position)
        screen_card.add_buttons([primary_button, corner_button, reset_button])

    def config(self):
        return self.host.config

    def _window_visible(self) -> bool:
        window = self._window
        checker = getattr(window, "isVisible", None)
        return bool(checker()) if callable(checker) else True

    def _sync_scale_widgets(self, percent: int) -> None:
        if self.scale_slider.value() != percent:
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(percent)
            self.scale_slider.blockSignals(False)
        if self.scale_spin.value() != percent:
            self.scale_spin.blockSignals(True)
            self.scale_spin.setValue(percent)
            self.scale_spin.blockSignals(False)

    def _apply_scale(self, scale: float) -> None:
        percent = _percent(scale)
        self._sync_scale_widgets(percent)
        self.config().set("scale", percent / 100.0)
        self.changed.emit()

    def _on_scale_percent(self, percent: int) -> None:
        self._apply_scale(percent / 100.0)

    def _on_flags_changed(self, _checked: bool = False) -> None:
        config = self.config()
        config.set("always_on_top", self.always_on_top_check.isChecked())
        config.set("click_through", self.click_through_check.isChecked())
        config.set("multi_screen", self.multi_screen_check.isChecked())
        self.changed.emit()

    def _on_visibility_changed(self, visible: bool) -> None:
        window = self._window
        if window is None:
            return
        setter = getattr(window, "set_visible", None)
        if callable(setter):
            setter(bool(visible))
            return
        if bool(window.isVisible()) != bool(visible):
            window.toggle_hidden()

    def _on_edge_probe_changed(self, enabled: bool) -> None:
        window = self._window
        self.config().set("edge_probe_enabled", bool(enabled))
        if window is not None:
            setter = getattr(window, "set_edge_probe_enabled", None)
            if callable(setter):
                setter(bool(enabled), persist=False)
        self.changed.emit()

    def _on_stream_capture_changed(self, enabled: bool) -> None:
        self.config().set("stream_capture_mode", bool(enabled))
        self._apply_stream_capture(bool(enabled))
        self.changed.emit()

    def _apply_stream_capture(self, enabled: bool) -> None:
        pets = getattr(self.host, "pets", None)
        windows = pets.each() if pets is not None else [self._window]
        for window in windows:
            if window is None:
                continue
            setter = getattr(window, "set_stream_capture_mode", None)
            if callable(setter):
                setter(bool(enabled), persist=False)

    def _on_hotkey_finished(self) -> None:
        raw = self.hotkey_edit.text().strip()
        normalized = hotkey_spec.normalize(raw)
        if raw and not normalized:
            self.hotkey_edit.setText(self._last_hotkey)
            QMessageBox.warning(
                self,
                "快捷键",
                "无法识别这个组合键；请使用类似 Ctrl+Alt+P 的写法，至少包含一个修饰键。",
            )
            return
        self.hotkey_edit.setText(normalized)
        self._last_hotkey = normalized
        self.config().set("hotkey_toggle_pet", normalized)
        applier = getattr(self.host, "set_hotkey", None)
        if callable(applier):
            applier(normalized)
        self.changed.emit()

    def _on_text_sizes_changed(self, _value: int = 0) -> None:
        config = self.config()
        font_size = int(self.ui_font_size_spin.value())
        bubble_scale = int(self.bubble_text_scale_spin.value())
        config.set("ui_font_size", font_size)
        config.set("bubble_text_scale", bubble_scale)
        self._sync_bubble_scale(bubble_scale)
        self.changed.emit()

    def _sync_bubble_scale(self, value: int) -> None:
        """气泡已经显示时立即重排；没有这个接缝就只写配置。"""
        setter = getattr(self._window, "set_text_scale", None)
        if callable(setter):
            setter(int(value), persist=False)

    def _screen_text(self) -> str:
        try:
            layout = screens.snapshot_from_qt()
        except Exception:
            return "当前屏幕：不可用"
        screen = layout.by_name(layout.primary) or (layout.screens[0] if layout.screens else None)
        if screen is None:
            return "当前屏幕：不可用"
        return f"当前屏幕：{screen.name} · {screen.width} × {screen.height} · DPR {screen.dpr:g}"

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.screen_label.setText(self._screen_text())
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(self._window_visible())
        self.visible_check.blockSignals(False)

    def _move_to_primary(self) -> None:
        window = self._window
        if window is not None:
            window.move_to_primary()

    def _return_corner(self) -> None:
        window = self._window
        if window is not None:
            window.return_corner()

    def _reset_position(self) -> None:
        window = self._window
        if window is not None:
            window.reset_position()

    def _current_percent(self) -> int:
        return int(self.scale_spin.value())

    def dirty(self) -> bool:
        if self._current_percent() != self._initial_scale:
            return True
        if int(self.ui_font_size_spin.value()) != self._initial_ui_font_size:
            return True
        if int(self.bubble_text_scale_spin.value()) != self._initial_bubble_text_scale:
            return True
        return (
            self.always_on_top_check.isChecked() != self._initial_always_on_top
            or self.click_through_check.isChecked() != self._initial_click_through
            or self.stream_capture_check.isChecked() != self._initial_stream_capture
            or self.multi_screen_check.isChecked() != self._initial_multi_screen
            or self.edge_probe_check.isChecked() != self._initial_edge_probe
            or self.hotkey_edit.text().strip() != self._initial_hotkey
        )

    def draft(self) -> None:
        return None

    def confirm_save(self) -> None:
        config = self.config()
        config.set("scale", self._current_percent() / 100.0)
        config.set("always_on_top", self.always_on_top_check.isChecked())
        config.set("click_through", self.click_through_check.isChecked())
        config.set("multi_screen", self.multi_screen_check.isChecked())
        config.set("stream_capture_mode", self.stream_capture_check.isChecked())
        config.set("edge_probe_enabled", self.edge_probe_check.isChecked())
        config.set("hotkey_toggle_pet", self.hotkey_edit.text().strip())
        config.set("ui_font_size", int(self.ui_font_size_spin.value()))
        config.set("bubble_text_scale", int(self.bubble_text_scale_spin.value()))

    def discard_changes(self) -> None:
        for widget in (self.scale_slider, self.scale_spin):
            widget.blockSignals(True)
        self.scale_slider.setValue(self._initial_scale)
        self.scale_spin.setValue(self._initial_scale)
        for widget in (self.scale_slider, self.scale_spin):
            widget.blockSignals(False)
        for spin, value in (
            (self.ui_font_size_spin, self._initial_ui_font_size),
            (self.bubble_text_scale_spin, self._initial_bubble_text_scale),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.config().set("ui_font_size", self._initial_ui_font_size)
        self.config().set("bubble_text_scale", self._initial_bubble_text_scale)
        self.config().set("stream_capture_mode", self._initial_stream_capture)
        self._sync_bubble_scale(self._initial_bubble_text_scale)
        for checkbox, value in (
            (self.always_on_top_check, self._initial_always_on_top),
            (self.click_through_check, self._initial_click_through),
            (self.stream_capture_check, self._initial_stream_capture),
            (self.multi_screen_check, self._initial_multi_screen),
            (self.edge_probe_check, self._initial_edge_probe),
            (self.visible_check, self._initial_visible),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self._apply_stream_capture(self._initial_stream_capture)
        self.hotkey_edit.setText(self._initial_hotkey)
        self._last_hotkey = self._initial_hotkey
        applier = getattr(self.host, "set_hotkey", None)
        if callable(applier):
            applier(self._initial_hotkey, persist=False)
        if self._window is not None:
            setter = getattr(self._window, "set_edge_probe_enabled", None)
            if callable(setter):
                setter(self._initial_edge_probe, persist=False)

    def keywords(self) -> list[str]:
        return [
            "外观",
            "交互",
            "缩放",
            "大小",
            "滑条",
            "百分比",
            "300",
            "置顶",
            "穿透",
            "显示",
            "隐藏",
            "跨屏",
            "屏幕",
            "位置",
            "右下角",
            "边缘",
            "探头",
            "字号",
            "字体",
            "文字",
            "气泡",
            "直播",
            "OBS",
            "捕获",
            "scale",
            "appearance",
            "screen",
            "position",
            "font",
            "bubble",
        ]


class MenuPage(SettingsPage):
    title = "菜单"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.model = getattr(host, "menu_model", None)
        self.editor = None
        self._initial_animation_icons = self._animation_icons_enabled()
        embedded = []
        for spec in embedded_page_specs(host, "menu"):
            page = build_embedded_page(spec, host)
            if page is not None:
                embedded.append((spec, page))
        if embedded:
            with self.tab("layout", "菜单编排"):
                self._build_animation_section()
                self._build_layout_section()
            for spec, page in embedded:
                self.embed_page(page, str(spec.id), str(spec.title))
        else:
            self._build_animation_section()
            self._build_layout_section()

    def _animation_icons_enabled(self) -> bool:
        config = getattr(self.host, "config", None)
        if config is None:
            return True
        value = config.get("menu_animation_icons", True)
        return True if value is None else bool(value)

    def _build_animation_section(self) -> None:
        card = self.section("播放动画")
        self.animation_icons_check = make_checkbox(self)
        self.animation_icons_check.setChecked(self._initial_animation_icons)
        self.animation_icons_check.toggled.connect(self._on_animation_icons_toggled)
        card.add_row(
            "播放动画显示预览",
            self.animation_icons_check,
            "在「播放动画」子菜单里为每个动作显示缩略图；动画很多时首次展开会稍慢。",
        )

    def _on_animation_icons_toggled(self, checked: bool) -> None:
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("menu_animation_icons", bool(checked))
        self.changed.emit()

    def _build_layout_section(self) -> None:
        if self.model is None:
            self.add_note("菜单模型不可用，无法编辑右键菜单。")
            return
        self.add_note(
            "拖动调整顺序或移入子菜单；勾选控制显示；可插入分割线、新建子菜单、改别名与图标。"
        )
        card = self.section("菜单编排")
        from .menu_editor import MenuEditor

        self.editor = MenuEditor(self.host, self.model, self)
        self.editor.setAccessibleName("菜单编排")
        card.add_widget(self.editor)

    def dirty(self) -> bool:
        if self.animation_icons_check.isChecked() != self._initial_animation_icons:
            return True
        if self.editor is not None and self.editor.is_dirty():
            return True
        return self._embedded_dirty()

    def draft(self) -> None:
        return None

    def confirm_save(self) -> None:
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("menu_animation_icons", bool(self.animation_icons_check.isChecked()))
        if self.editor is not None and self.editor.is_dirty():
            self.editor.confirm_save()
        self._embedded_confirm_save()

    def discard_changes(self) -> None:
        self.animation_icons_check.blockSignals(True)
        self.animation_icons_check.setChecked(self._initial_animation_icons)
        self.animation_icons_check.blockSignals(False)
        config = getattr(self.host, "config", None)
        if config is not None:
            config.set("menu_animation_icons", self._initial_animation_icons)
        if self.editor is not None:
            self.editor.discard()
        self._embedded_discard()

    def keywords(self) -> list[str]:
        return [
            "菜单",
            "编排",
            "显示",
            "隐藏",
            "排序",
            "子菜单",
            "分割线",
            "图标",
            "右键",
            "快捷启动",
            "启动",
            "应用",
            "播放动画",
            "预览",
            "缩略图",
            "menu",
            "layout",
            "order",
            "animation",
            "thumbnail",
            *self._embedded_keywords(),
        ]
