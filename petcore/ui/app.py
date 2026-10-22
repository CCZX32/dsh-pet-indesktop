from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from .. import paths
from ..api.credentials import KeyringCredentials
from ..api.store import ApiStore
from ..account.service import AccountService
from ..config import Config
from ..content.collect import collect_characters as _collect
from ..log import setup_logging
from ..platform import hotkey_spec
from ..platform.hotkeys import GlobalHotkeyService
from ..platform.session import SessionWatcher
from ..platform.worker import WorkerHost
from ..mods.feature import FeatureManager
from .menu import install_core_menu
from .menu_layout import (
    DEFAULT_LAYOUT_ID,
    merge_user_layout,
    migrate_default_size_visibility,
    migrate_legacy,
    migrate_p8_menu,
    migrate_p9_menu,
    resolve,
)
from .chat import ChatController
from .menu_model import MenuItem, MenuModel
from .pet_manager import PetManager, SHARED_KEYS
from .pet_window import PetWindow
from .tray import TrayIcon

logger = logging.getLogger("petcore.ui.app")

#: 全局快捷键：配置键 + 动作（AI 三条都走 ai.chat 的 feature command）。
HOTKEY_CONFIGS = {
    "toggle_pet": "hotkey_toggle_pet",
    "open_chat": "hotkey_open_chat",
    "look_screen": "hotkey_look_screen",
    "screen_capture": "hotkey_screen_capture",
}
HOTKEY_COMMANDS = {
    "open_chat": ("ai.chat", "open"),
    "look_screen": ("ai.chat", "look_screen"),
    "screen_capture": ("ai.chat", "screen_capture"),
}


def _mod_diagnostics(result) -> list[str]:
    diagnostics = getattr(result, "diagnostics", None) or []
    return [str(item) for item in diagnostics]


def _invoke_feature_command(command, slot: int | None) -> object:
    """调用扩展命令；命令声明了 ``slot`` 参数就带上发起者。"""
    if slot is None:
        return command()
    try:
        parameters = inspect.signature(command).parameters
    except (TypeError, ValueError):
        return command()
    if "slot" in parameters:
        return command(slot=int(slot))
    return command()


class _PresentationAdapter:
    def __init__(self, host, target_window=None):
        self._host = host
        self._target_window = target_window

    def _window(self):
        if self._target_window is not None:
            return self._target_window
        active = getattr(self._host, "_active_window", None) or getattr(
            self._host, "window", None
        )
        pets = getattr(self._host, "pets", None)
        if pets is not None and callable(getattr(pets, "each", None)):
            visible = [window for window in pets.each() if window.isVisible()]
            if active is not None and active.isVisible():
                return active
            if visible:
                return visible[0]
            return active
        return active

    def for_window(self, window):
        """Return a presentation port bound to one pet window."""
        return _PresentationAdapter(self._host, window)

    def say(self, text: str, *, duration_ms: int = 4000, force: bool = False) -> None:
        if not force:
            quiet = getattr(self._host, "quiet", None)
            if quiet is not None and quiet.quiet_active():
                return
        window = self._window()
        if window is not None:
            window.say(text, duration_ms)

    def play_animation(self, name: str) -> bool:
        window = self._window()
        return bool(window is not None and window.play_animation(name))

    def show_image(
        self, path, caption: str = "", *, duration_ms: int = 4000, scale: float = 1.0
    ) -> bool:
        window = self._window()
        return bool(
            window is not None
            and window.show_image(path, caption, duration_ms, image_scale=scale)
        )

    def play_event(self, group: str, variant: str | int | None = None) -> bool:
        window = self._window()
        return bool(window is not None and window.play_event(group, variant))

    def notify(self, title: str, message: str, *, force: bool = False) -> None:
        self.say(f"{title}：{message}" if title else message, force=force)

    def current_character(self) -> str:
        window = self._window()
        return str(getattr(window, "character_id", "") if window is not None else "")


class CoreHost:
    def __init__(self, app: QApplication, config: Config, root: Path, mod_dirs):
        self.app = app
        self.config = config
        self.root = root
        self.mod_dirs = mod_dirs
        self.api_store = ApiStore(self.root)
        self.api_credentials = KeyringCredentials()
        self.account = AccountService(self.api_store, self.api_credentials)
        self.chat = ChatController(self, self.root)
        from .screen import ScreenAskController

        self.screen_ask = ScreenAskController(self, self.root)
        self.menu_model = MenuModel()
        self.load_result = None
        self._characters: list = []
        self.window: PetWindow | None = None
        self.pets: PetManager | None = None
        self._active_window: PetWindow | None = None
        self.tray: TrayIcon | None = None
        self.settings_dialog = None
        self.hotkeys: GlobalHotkeyService | None = None
        self.diagnostics: list[str] = []
        self.menu_diagnostics: list[str] = []
        self.features: FeatureManager | None = None
        self.quiet = None
        self.worker_host = WorkerHost()
        from .ports import QuietMode

        self.quiet = QuietMode()
        self.load_content()

    def presentation_port(self):
        return _PresentationAdapter(self)

    def attach_window(self, window: PetWindow) -> None:
        self.window = window
        self._active_window = window
        from .ports import build_ports

        ports = build_ports(self, window)
        self.features = FeatureManager(ports, host=self)
        self.diagnostics.extend(self.features.load_builtin_features())
        self.diagnostics.extend(self.features.load_builtin_demo())
        # 是否允许加载已由 loader 判定（全局开关或安装器授信的 `.trusted` 包），
        # 这里只认 ``mod.enabled``，否则随安装包投放的扩展永远激活不了。
        user_mods_roots = tuple(path.resolve() for path in paths.user_mods_dirs(self.root))
        for mod in getattr(self.load_result, "mods", ()) or ():
            if mod.kind != "feature" or not mod.enabled:
                continue
            mod_path = mod.path.resolve()
            if not any(
                mod_path == base or base in mod_path.parents for base in user_mods_roots
            ):
                continue
            if mod.manifest.execution != "host-only":
                self.diagnostics.append(f"{mod.id}: worker feature is not supported yet")
                continue
            if not mod.manifest.entrypoint:
                self.diagnostics.append(f"{mod.id}: missing entrypoint")
                continue
            self.diagnostics.extend(
                self.features.load(
                    pack=mod.path,
                    owner=mod.id,
                    entrypoint=mod.manifest.entrypoint,
                    config={},
                )
            )
        for message in self.diagnostics:
            logger.warning("feature/mod diagnostic: %s", message)
        self._register_feature_menus()

    def _register_feature_menus(self) -> None:
        if self.features is None:
            return
        for feature, contribution in self.features.menu_contributions():
            label = str(contribution.data.get("label") or contribution.id)
            command_id = str(contribution.data.get("command") or contribution.id)
            order = int(contribution.data.get("order") or 500)
            icon_name = str(contribution.data.get("icon") or "")
            checked = contribution.data.get("checked")
            self.menu_model.register(
                MenuItem(
                    id=f"{feature.owner}:{contribution.id}",
                    label=label,
                    owner=feature.owner,
                    order=order,
                    icon=icon_name,
                    checked=checked if callable(checked) else None,
                    callback=(
                        lambda owner=feature.owner, command=command_id: self._run_feature_command(
                            owner, command
                        )
                    ),
                )
            )

    def _run_feature_command(self, owner: str, command_id: str) -> None:
        if self.features is None:
            return
        command = self.features.command(owner, command_id)
        if command is None:
            logger.warning("feature command missing: %s/%s", owner, command_id)
            return
        try:
            command()
        except Exception:
            logger.exception("feature command failed: %s/%s", owner, command_id)

    def run_feature_command(
        self, owner: str, command_id: str, *, slot: int | None = None
    ) -> bool:
        """菜单/热键的统一入口：扩展缺失时明确提示，不静默失败。

        ``slot`` 是发起命令的桌宠；扩展命令若声明了 ``slot`` 参数就带上它，
        子宠菜单里的 AI 对话/截图提问才会落在子宠自己的窗口与会话上。
        """
        command = None
        if self.features is not None:
            command = self.features.command(owner, command_id)
        if command is None:
            self._notify_missing_feature(owner)
            return False
        try:
            _invoke_feature_command(command, slot)
        except Exception:
            logger.exception("feature command failed: %s/%s", owner, command_id)
            self._notify(slot, "扩展执行失败，详情见日志")
            return False
        return True

    def _notify_missing_feature(self, owner: str) -> None:
        label = "AI 扩展" if owner == "ai.chat" else f"扩展 {owner}"
        self._notify(None, f"{label}未安装：可在「扩展管理 → 插件市场」安装")

    def _notify(self, slot: int | None, message: str) -> None:
        window = self.window
        if slot is not None and self.pets is not None:
            window = self.pets.window_for_slot(int(slot)) or window
        window = window or self._active_window
        say = getattr(window, "say", None)
        if callable(say):
            try:
                say(message, 6000)
            except Exception:
                logger.debug("notify failed", exc_info=True)

    def settings_pages(self):
        return self.features.settings_pages() if self.features is not None else []

    def load_content(self) -> None:
        self._characters, result = _collect(
            root=self.root,
            mod_dirs=self.mod_dirs,
            frameseq_mode=str(self.config.get("frameseq") or "auto"),
            allow_feature_mods=bool(self.config.get("allow_feature_mods")),
        )
        self.load_result = result
        self.diagnostics = _mod_diagnostics(result)

    def characters(self) -> list:
        return list(self._characters)

    def character_for(self, character_id: str):
        for character in self._characters:
            if character.id == character_id:
                return character
        return self._characters[0]

    def build_menu(self, parent=None):
        if isinstance(parent, PetWindow):
            self._active_window = parent
        self.reload_menu(parent if isinstance(parent, PetWindow) else None)
        return self.menu_model.build(parent)

    def reload_menu(self, window: PetWindow | None = None) -> None:
        target = window or self._active_window or self.window
        if target is None:
            return
        install_core_menu(self.menu_model, target)
        self.menu_model.set_font_size(int(self.config.get("ui_font_size") or 13))
        raw = self.config.get("menu_layout")
        if isinstance(raw, dict):
            changed = migrate_p8_menu(raw)
            changed = migrate_p9_menu(raw) or changed
            if changed:
                self.config.set("menu_layout", raw)
                self.config.save()
        if not isinstance(raw, dict):
            hidden = self.config.get("menu_hidden") or []
            order = self.config.get("menu_order") or []
            if hidden or order:
                raw = migrate_legacy(hidden, order)
                self.config.set("menu_layout", raw)
                self.config.save()
            else:
                raw = None
        elif migrate_default_size_visibility(raw):
            self.config.set("menu_layout", raw)
            self.config.save()
        resolved = resolve(
            raw,
            registered=self.menu_model.registered_ids(),
            available=self.menu_model.available_ids(),
        )
        if resolved.source == "user" and any(
            item.startswith(("default-action-added:", "mod-action-added:"))
            for item in resolved.diagnostics
        ):
            self._persist_merged_menu_layout(raw)
        self.menu_model.apply_layout(resolved.nodes)
        self.menu_diagnostics = list(resolved.diagnostics)

    def _persist_merged_menu_layout(self, raw: dict) -> bool:
        """Write merged defaults back so the fix survives the next reload.

        Only ``nodes`` changes: ``layout_id``/``schema_version`` and every node
        the user ordered or hid stay as they are.
        """
        merged, notes = merge_user_layout(raw, registered=self.menu_model.registered_ids())
        if not any(
            note.startswith(("default-action-added:", "mod-action-added:")) for note in notes
        ):
            return False
        merged["layout_id"] = str(raw.get("layout_id") or DEFAULT_LAYOUT_ID)
        merged["schema_version"] = raw.get("schema_version", 1)
        try:
            self.config.set("menu_layout", merged)
            self.config.save()
        except OSError:
            logger.warning("failed to persist the merged menu layout", exc_info=True)
            return False
        return True

    def apply_live_settings(self) -> None:
        pets = getattr(self, "pets", None)
        targets = pets.each() if pets is not None else ([self.window] if getattr(self, "window", None) else [])
        for window in targets:
            self._apply_live_to(window)
        self._apply_live_fonts()
        chat = getattr(self, "chat", None)
        apply_appearance = getattr(chat, "apply_appearance", None)
        if callable(apply_appearance):
            try:
                apply_appearance()
            except Exception:
                logger.exception("failed to refresh chat appearance")

    def _apply_live_fonts(self) -> None:
        """界面字号实时生效：菜单下次构建生效，打开中的设置页立即重排。"""
        size = int(self.config.get("ui_font_size") or 13)
        model = getattr(self, "menu_model", None)
        if model is not None:
            model.set_font_size(size)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is None or getattr(dialog, "_disposed", False):
            return
        refresh = getattr(dialog, "refresh_style", None)
        if callable(refresh):
            try:
                refresh()
            except RuntimeError:
                logger.debug("settings dialog is already gone", exc_info=True)
            return
        from .settings.style import is_dark, stylesheet

        try:
            dialog.setStyleSheet(stylesheet(is_dark(), size))
        except RuntimeError:
            logger.debug("settings dialog is already gone", exc_info=True)

    def _apply_live_to(self, window) -> None:
        window_config = getattr(window, "config", None)
        # Global values are read from the process config; pet-local values are
        # read from the window's own profile.  The old implementation copied
        # every key from the primary profile, which made a child settings
        # window silently edit the wrong pet.
        global_config = self.config
        pet_config = window_config or self.config
        if window_config is not None:
            for key in SHARED_KEYS:
                if key in global_config.data:
                    window_config.set(key, global_config.get(key))
        character = str(pet_config.get("character") or "")
        if character and character != getattr(window, "character_id", ""):
            window.set_character(character, persist=False)
        scale = float(pet_config.get("scale") or 0.72)
        state = getattr(window, "state", None)
        current_scale = float(getattr(state, "scale", scale))
        if abs(scale - current_scale) > 1e-9:
            window.set_scale(scale, persist=False)
        on_top = bool(pet_config.get("always_on_top"))
        if on_top != bool(getattr(window, "always_on_top", on_top)):
            window.set_always_on_top(on_top, persist=False)
        click_through = bool(global_config.get("click_through"))
        if click_through != bool(getattr(window, "click_through", click_through)):
            window.set_click_through(click_through, persist=False)
        edge_probe = bool(pet_config.get("edge_probe_enabled"))
        if hasattr(window, "set_edge_probe_enabled"):
            window.set_edge_probe_enabled(edge_probe, persist=False)
        stream = bool(global_config.get("stream_capture_mode"))
        if stream != bool(getattr(window, "stream_capture_mode", stream)):
            window.set_stream_capture_mode(stream, persist=False)

    def install_hotkeys(self) -> None:
        if self.hotkeys is None:
            self.hotkeys = GlobalHotkeyService(self.app)
            self.hotkeys.install()
        for kind, key in HOTKEY_CONFIGS.items():
            self.set_hotkey(str(self.config.get(key) or ""), persist=False, kind=kind)

    def set_hotkey(
        self, text: str, *, persist: bool = True, kind: str = "toggle_pet"
    ) -> tuple[bool, str]:
        key = HOTKEY_CONFIGS.get(str(kind))
        if key is None:
            return False, "未知的快捷键类型"
        normalized = hotkey_spec.normalize(text)
        if persist:
            self.config.set(key, normalized)
            self.config.save()
        if self.hotkeys is None:
            return True, ""
        ok, message = self.hotkeys.apply(
            normalized, self._hotkey_callback(kind), name=str(kind)
        )
        if not ok:
            logger.warning("无法注册全局快捷键 %s(%s)：%s", normalized, kind, message)
        return ok, message

    def _hotkey_callback(self, kind: str):
        if kind == "toggle_pet":
            return self._toggle_pet_visible
        command = HOTKEY_COMMANDS.get(str(kind))
        if command is None:
            return lambda: None
        owner, command_id = command
        return lambda: self.run_feature_command(owner, command_id)

    def _toggle_pet_visible(self) -> None:
        if self.pets is not None:
            visible = not self.pets.primary.isVisible() if self.pets.primary is not None else True
            self.pets.set_visible_all(visible)
            return
        if self.window is not None:
            self.window.set_visible(not self.window.isVisible())

    def open_settings(self, initial_page: str | None = None, *, window=None) -> None:
        from .settings.dialog import SettingsDialog

        dialog = self.settings_dialog
        target = window or self._active_window or self.window
        if dialog is not None and getattr(dialog, "target_window", None) is not target:
            # One non-modal dialog remains the single source of truth.  Commit
            # the old target before rebuilding it for the pet that was clicked.
            dialog.close()
            if self.settings_dialog is dialog:
                self.settings_dialog = None
            dialog.deleteLater()
            dialog = None
        if dialog is None:
            dialog = SettingsDialog(self, initial_page=initial_page, target_window=target)
            dialog.finished.connect(lambda _result, d=dialog: self._settings_closed(d))
            self.settings_dialog = dialog
        elif initial_page:
            dialog.select_page(initial_page)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _settings_closed(self, dialog) -> None:
        if self.settings_dialog is dialog:
            self.settings_dialog = None
        dialog.deleteLater()

    def reload_mods(self) -> None:
        if self.features is not None:
            for owner in list(self.features.features):
                self.menu_model.unregister_owner(owner)
            self.features.stop()
            self.features = None
        self.load_content()
        targets = self.pets.each() if self.pets is not None else ([self.window] if self.window else [])
        for window in targets:
            target = window.config.get("character") or self.config.get("character")
            window.reload_characters(self.character_for(target))
            window.config.set("character", target)
        if self.window is not None:
            self.attach_window(self.window)
            self.reload_menu()
        if self.tray is not None:
            self.tray.refresh()

    def open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))

    def set_all_visible(self, visible: bool) -> None:
        pets = getattr(self, "pets", None)
        if pets is not None:
            pets.set_visible_all(bool(visible))
        elif getattr(self, "window", None) is not None:
            self.window.set_visible(bool(visible))
        if getattr(self, "tray", None) is not None:
            QTimer.singleShot(0, self.tray.refresh)

    def toggle_all_visible(self) -> None:
        pets = getattr(self, "pets", None)
        windows = pets.each() if pets is not None else ([self.window] if self.window else [])
        visible = any(window.isVisible() for window in windows if window is not None)
        self.set_all_visible(not visible)

    def build_tray_menu(self, _parent=None):
        """托盘右键菜单：隐藏后只靠鼠标也能把桌宠叫回来。"""
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        self.populate_tray_menu(menu)
        # 每次弹出前原地重建动作（不替换 QMenu 对象，避免 Qt 正要显示时菜单被销毁）。
        menu._petcore_refresh = lambda: self.populate_tray_menu(menu)
        menu.aboutToShow.connect(menu._petcore_refresh)
        return menu

    def populate_tray_menu(self, menu) -> None:
        menu.clear()
        pets = getattr(self, "pets", None)
        windows = pets.each() if pets is not None else ([self.window] if self.window else [])
        visible = any(window.isVisible() for window in windows if window is not None)
        toggle = menu.addAction("隐藏桌宠" if visible else "显示桌宠")
        toggle.triggered.connect(lambda _checked=False: self.toggle_all_visible())
        click_through = menu.addAction("鼠标穿透")
        click_through.setCheckable(True)
        click_through.setChecked(self.all_click_through())
        click_through.setToolTip("鼠标点击穿过桌宠；关闭也要从这里操作")
        click_through.triggered.connect(
            lambda checked=False: self.set_all_click_through(bool(checked))
        )
        if len(windows) > 1:
            all_visible = menu.addAction("显示全部")
            all_visible.triggered.connect(lambda _checked=False: self.set_all_visible(True))
            all_hidden = menu.addAction("隐藏全部")
            all_hidden.triggered.connect(lambda _checked=False: self.set_all_visible(False))

        menu.addSeparator()
        settings = menu.addAction("桌宠设置")
        settings.triggered.connect(lambda _checked=False: self.open_settings())
        data = menu.addAction("打开数据目录")
        data.triggered.connect(lambda _checked=False: self.open_data_dir())
        reload_action = menu.addAction("重新加载扩展")
        reload_action.triggered.connect(lambda _checked=False: self.reload_mods())

        if pets is not None and len(windows) > 1:
            menu.addSeparator()
            for slot, window in sorted(pets.windows.items()):
                label = "主桌宠" if slot == 0 else f"桌宠 {slot}"
                submenu = menu.addMenu(label)
                state = submenu.addAction(
                    "隐藏" if window.isVisible() else "显示"
                )
                state.triggered.connect(
                    lambda _checked=False, w=window: self._toggle_one(w)
                )
                corner = submenu.addAction("回到右下角")
                corner.triggered.connect(lambda _checked=False, w=window: w.return_corner())
                if slot != 0:
                    quit_one = submenu.addAction("退出这只")
                    quit_one.triggered.connect(
                        lambda _checked=False, w=window: w.quit_from_menu()
                    )

        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(lambda _checked=False: self.quit_app())

    def _toggle_one(self, window) -> None:
        window.set_visible(not window.isVisible())
        tray = getattr(self, "tray", None)
        if tray is not None:
            QTimer.singleShot(0, tray.refresh)

    def _windows(self):
        pets = getattr(self, "pets", None)
        if pets is not None:
            try:
                return [window for window in pets.each() if window is not None]
            except Exception:
                logger.debug("listing pets failed", exc_info=True)
        return [self.window] if self.window is not None else []

    def all_click_through(self) -> bool:
        """全部桌宠都开了鼠标穿透才算勾选（部分开启按未勾选处理）。"""
        windows = self._windows()
        if not windows:
            return False
        return all(bool(getattr(window, "click_through", False)) for window in windows)

    def set_all_click_through(self, value: bool) -> None:
        """托盘菜单唯一的「鼠标穿透」开关：一次作用到所有桌宠。"""
        windows = self._windows()
        for window in windows:
            setter = getattr(window, "set_click_through", None)
            if not callable(setter):
                continue
            try:
                setter(bool(value))
            except Exception:
                logger.exception("failed to set click-through on %r", window)
        target = getattr(self, "_active_window", None) or self.window
        say = getattr(target, "say", None)
        if callable(say):
            message = (
                "已开启鼠标穿透，可从托盘菜单关闭"
                if value
                else "已关闭鼠标穿透"
            )
            try:
                say(message, 5000)
            except Exception:
                logger.debug("click-through notice failed", exc_info=True)
        # 不在托盘动作里 refresh：菜单弹出期间 clear() 会删掉正在发信号的 QAction。
        # 勾选状态由下一次 aboutToShow 的原地重建刷新。

    def close_dialogs(self) -> None:
        for attribute in ("settings_dialog",):
            dialog = getattr(self, attribute, None)
            if dialog is None:
                continue
            try:
                dialog.close()
            except Exception:
                logger.debug("failed to close dialog", exc_info=True)
            if getattr(self, attribute, None) is dialog:
                setattr(self, attribute, None)

    def quit_app(self) -> None:
        self.close_dialogs()
        self.worker_host.shutdown_all()
        if self.features is not None:
            self.features.stop()
            self.features = None
        self.app.quit()


def _install_tray(host: CoreHost) -> TrayIcon:
    icon = paths.legacy_asset_root() / "icon.ico"
    tray = TrayIcon(
        host.build_tray_menu,
        icon,
        host.toggle_all_visible,
        None,
    )
    tray.show()
    return tray


def _wire_screens(app: QApplication, manager) -> None:
    def refresh(*_args) -> None:
        QTimer.singleShot(0, manager.handle_screens_changed)

    for screen in app.screens():
        screen.geometryChanged.connect(refresh)
        screen.logicalDotsPerInchChanged.connect(refresh)
    app.screenAdded.connect(lambda screen: (screen.geometryChanged.connect(refresh), refresh()))
    app.screenRemoved.connect(refresh)
    app.primaryScreenChanged.connect(refresh)


def run(config: Config, *, root: Path, mod_dirs, instance: str | None = None) -> int:
    setup_logging(paths.logs_dir(root))
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(f"dsh-pet-core-{instance}" if instance else "dsh-pet-core")
    app.setQuitOnLastWindowClosed(False)
    palette = app.palette()
    accent = QColor("#0a84ff")
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        palette.setColor(accent_role, accent)
    app.setPalette(palette)
    icon_path = paths.legacy_asset_root() / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    lock = QLockFile(str(root / "petcore.lock"))
    lock.setStaleLockTime(0)
    root.mkdir(parents=True, exist_ok=True)
    if not lock.tryLock(100):
        logger.warning("another petcore instance is already running")
        return 0

    host = CoreHost(app, config, root, mod_dirs)
    manager = PetManager(host, root, config)
    host.pets = manager
    character = host.character_for(str(config.get("character") or ""))
    window = manager.create_primary(character)
    host.window = window
    host.attach_window(window)
    manager.restore()
    host.reload_menu()
    host.tray = _install_tray(host)
    host.install_hotkeys()
    if str(config.get("frameseq") or "auto") != "off":
        from ..media.provision import start_background_provision

        start_background_provision(host)

    watcher = SessionWatcher(manager.shutdown, app)
    watcher.install()
    _wire_screens(app, manager)

    def finish() -> None:
        if host.hotkeys is not None:
            host.hotkeys.uninstall()
        host.close_dialogs()
        manager.shutdown()
        host.worker_host.shutdown_all()
        if host.features is not None:
            host.features.stop()
        if host.tray is not None:
            host.tray.hide()
        watcher.remove()

    app.aboutToQuit.connect(finish)
    return app.exec()
