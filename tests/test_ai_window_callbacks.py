"""Packaged AI window → Core notification / owner settings, through real Qt UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from pet.ai_bindings import register_ai_pet_view
from pet.app import AppShell
from pet.config import Config
from pet.settings_mod_domain import close_extension_settings
from pet.settings_widgets import SettingRow
from tests.ai_package_fakes import OWNER, MemoryVault, build_package, dispose_qobject

app = QApplication.instance() or QApplication([])


def pump(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    assert predicate(), "Qt operation did not converge"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return build_package(tmp_path_factory.mktemp("ai-callbacks") / "built")


@pytest.fixture
def installed(built, tmp_path, monkeypatch):
    vault = MemoryVault()
    monkeypatch.setattr("pet.credentials.secure_backend", lambda: vault)
    monkeypatch.setenv("PET_RENDER_TOPOLOGY", "legacy")
    quit_policy = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)  # Same policy as the production pet process.
    config = Config(base=tmp_path)
    config.set("settings_process_isolation", False)
    shell = AppShell(app, config, enable_chat=False)
    runtime = shell.feature_runtime
    manager = runtime.attach_official(OWNER)
    assert manager.submit("import_disabled", built, auto_apply=True)
    pump(lambda: not manager.busy)
    assert manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
    pump(lambda: not manager.busy)
    mount = runtime.mounts.runtimes[OWNER]
    try:
        yield shell, manager, mount
    finally:
        dialog = shell.instance.modern_settings_dialog
        if dialog is not None:
            close_extension_settings(dialog)
            dialog.mod_host.shutdown()
            dialog.hide()
            dialog.deleteLater()
        for toast in tuple(shell._toast_windows):
            toast.close()
        dispose_qobject(mount)
        runtime.close()
        register_ai_pet_view(None)
        app.setQuitOnLastWindowClosed(quit_policy)


def click_settings_link(window, *, keyboard=False):
    label = window.provider_label
    assert 'href="api-settings"' in label.text(), label.text()
    if keyboard:
        window.activateWindow()
        pump(lambda: window.isActiveWindow())
        label.setFocus(Qt.FocusReason.TabFocusReason)
        assert label.hasFocus()
        QTest.keyClick(label, Qt.Key.Key_Tab)  # Select the label's link before activating it.
        QTest.keyClick(label, Qt.Key.Key_Return)
    else:
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)


@pytest.mark.parametrize("keyboard", [False, True], ids=["mouse", "keyboard"])
def test_missing_key_opens_its_own_settings_and_preserves_input_and_drafts(installed, keyboard):
    shell, _manager, mount = installed
    before = json.dumps(shell.config.chat_settings().to_dict(), sort_keys=True)
    window = mount.chat()
    window.input.setPlainText("保留这条尚未发送的问题")
    messages = list(window.session.messages)
    window.send_message()
    assert window.input.toPlainText() == "保留这条尚未发送的问题"
    assert window.session.messages == messages
    assert not window.service.busy
    click_settings_link(window, keyboard=keyboard)
    pump(lambda: shell.instance.modern_settings_dialog is not None)
    dialog = shell.instance.modern_settings_dialog
    assert dialog.isVisible()
    assert dialog.sidebar.currentItem().text() == "扩展管理"
    panel = dialog.mod_panel
    assert panel.owner == OWNER
    key = panel.component.page.key
    assert key.isVisibleTo(dialog)
    key.setText("callback-test-secret")
    click_settings_link(window)
    assert dialog.mod_panel is panel
    assert key.text() == "callback-test-secret", "Repeated navigation discarded the draft"
    QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
    assert not panel.dirty()
    provider = mount.runtime.config.chat_settings().active_config
    assert mount.runtime.config.resolve_provider_secret(provider) == "callback-test-secret"
    assert "callback-test-secret" not in (mount.runtime.config.dir / "configuration.json").read_text()
    assert json.dumps(shell.config.chat_settings().to_dict(), sort_keys=True) == before


@pytest.mark.parametrize("state", ["enabled", "disabled", "closed"])
def test_authentication_notification_routes_to_owner_settings_only_while_live(installed, state):
    shell, manager, mount = installed
    received = threading.Event()

    class Unauthorized(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = b'{"error":{"message":"invalid API key"}}'
            self.send_response(401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            received.set()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Unauthorized)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        config = mount.runtime.config
        settings = config.chat_settings()
        provider = settings.active_config
        provider.base_url = f"http://127.0.0.1:{server.server_port}"
        provider.api_key_ref = config.save_provider_secret(provider, "test-only-key")
        config.set_chat_settings(settings)
        config.save()
        window = mount.chat()
        background = QWidget()
        background.show()
        background.activateWindow()
        pump(lambda: background.isActiveWindow())
        window.hide()
        window.input.setPlainText("exercise the local 401 endpoint")
        window.send_message()
        pump(received.is_set)
        pump(lambda: window.service.is_drained)
        assert shell._toast_windows, "The package did not reach the Core notifier"
        toast = shell._toast_windows[-1]
        assert toast.isVisible()
        if state == "disabled":
            assert manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
            pump(lambda: not manager.busy)
        elif state == "closed":
            mount.close()
        QTest.mouseClick(toast, Qt.MouseButton.LeftButton)
        if state == "enabled":
            pump(lambda: shell.instance.modern_settings_dialog is not None)
            assert shell.instance.modern_settings_dialog.mod_panel.owner == OWNER
        else:
            assert shell.instance.modern_settings_dialog is None
            assert not window.isVisible()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=10)
        assert not worker.is_alive()


def test_settings_process_cold_start_selects_the_ai_owner_without_importing_pet_app(installed, tmp_path):
    script = textwrap.dedent('''
        import sys, traceback
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from pet.__main__ import _exec_settings
        from pet.config import Config
        app = QApplication([])
        def inspect():
            try:
                dialog = next(w for w in app.topLevelWidgets() if hasattr(w, "mod_panel_owner"))
                assert dialog.mod_panel_owner == "official.ai-chat", dialog.mod_panel_owner
                assert dialog.mod_panel.component.page.key.isVisibleTo(dialog)
                assert "pet.app" not in sys.modules
                print("owner settings visible; pet.app not imported", flush=True)
                app.exit(0)
            except Exception:
                traceback.print_exc()
                app.exit(1)
        QTimer.singleShot(0, inspect)
        raise SystemExit(_exec_settings(app, Config(base=sys.argv[1]), include_ai=False,
                                      initial_page="extension:official.ai-chat"))
    ''')
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "owner settings visible" in result.stdout


def test_existing_settings_process_navigates_and_preserves_the_owner_draft(installed, tmp_path):
    shell, _manager, mount = installed
    shell.config.set("settings_process_isolation", True)
    window = mount.chat()
    window.input.setPlainText("保留这条尚未发送的问题")
    window.send_message()
    script = textwrap.dedent('''
        import json, sys, traceback
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from pet.__main__ import _exec_settings
        from pet.config import Config
        root = Path(sys.argv[1])
        app = QApplication([])
        phase, original = 0, None
        def publish(name, value):
            temp = root / (name + ".tmp")
            temp.write_text(json.dumps(value), encoding="utf-8")
            temp.replace(root / name)
        def inspect():
            global phase, original
            try:
                dialog = next(w for w in app.topLevelWidgets() if hasattr(w, "mod_panel_owner"))
                if phase == 0:
                    assert dialog.sidebar.currentItem().text() == "常规"
                    dialog.showMaximized()
                    publish("settings-ready.json", {})
                    phase = 1
                elif dialog.sidebar.currentItem().text() == "扩展管理" and dialog.mod_panel_owner == "official.ai-chat":
                    assert "pet.app" not in sys.modules
                    assert dialog.isMaximized(), "Navigation changed the existing window state"
                    panel = dialog.mod_panel
                    assert panel.component.page.key.isVisibleTo(dialog)
                    if phase == 1:
                        original = panel
                        panel.component.page.key.setText("unsaved-test-draft")
                        dialog.select_page("常规")
                        publish("settings-first.json", {"owner": panel.owner})
                        phase = 2
                    else:
                        assert panel is original
                        assert panel.component.page.key.text() == "unsaved-test-draft"
                        publish("settings-second.json", {"owner": panel.owner, "draft_retained": True})
                        app.quit()
            except Exception:
                traceback.print_exc()
                app.exit(1)
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(inspect)
        timer.start()
        raise SystemExit(_exec_settings(app, Config(base=root), include_ai=False))
    ''')
    with (tmp_path / "settings-child.log").open("w") as log:
        child = subprocess.Popen([sys.executable, "-u", "-c", script, str(tmp_path)],
                                 stdout=log, stderr=subprocess.STDOUT,
                                 env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        try:
            pump(lambda: (tmp_path / "settings-ready.json").exists() or child.poll() is not None)
            assert child.poll() is None, (tmp_path / "settings-child.log").read_text()
            click_settings_link(window)
            pump(lambda: (tmp_path / "settings-first.json").exists() or child.poll() is not None)
            assert (tmp_path / "settings-first.json").exists(), (tmp_path / "settings-child.log").read_text()
            click_settings_link(window)
            pump(lambda: child.poll() is not None)
            assert child.returncode == 0, (tmp_path / "settings-child.log").read_text()
            assert json.loads((tmp_path / "settings-second.json").read_text())["draft_retained"]
            assert shell.instance.modern_settings_dialog is None
            assert not shell._toast_windows, "Successful navigation must not show the busy notice"
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


def test_navigation_waits_for_the_settings_process_to_acquire_its_lock(installed):
    from PySide6.QtCore import QLockFile

    from pet.settings_extension_navigation import AiSettingsReceiver, AiSettingsRequest

    shell, _manager, _mount = installed
    shell.instance.open_modern_settings()
    dialog = shell.instance.modern_settings_dialog
    failures = []
    request = AiSettingsRequest(shell.config.dir, lambda: failures.append(True))
    # The click can happen after process launch but before the child acquires its lock.
    lock = QLockFile(str(shell.config.dir / "settings.lock"))
    assert lock.tryLock(0)
    receiver = AiSettingsReceiver(shell.config.dir, dialog)
    try:
        pump(lambda: request.finished)
        assert not failures
        pump(lambda: dialog.mod_panel_owner == OWNER)
    finally:
        receiver.close()
        lock.unlock()


@pytest.mark.parametrize("payload", [b"unknown-route\n", b"ai-settings\n" + b"x" * 256])
def test_navigation_receiver_refuses_unknown_or_oversized_commands(installed, payload):
    from PySide6.QtCore import QLockFile
    from PySide6.QtNetwork import QLocalSocket

    from pet.settings_extension_navigation import AiSettingsReceiver

    shell, _manager, _mount = installed
    shell.instance.open_modern_settings()
    dialog = shell.instance.modern_settings_dialog
    lock = QLockFile(str(shell.config.dir / "settings.lock"))
    assert lock.tryLock(0)
    receiver = AiSettingsReceiver(shell.config.dir, dialog)
    assert receiver.server.isListening()
    socket = QLocalSocket()
    connected = []
    socket.connected.connect(lambda: (connected.append(True), socket.write(payload)))
    try:
        socket.connectToServer(receiver.server.fullServerName())
        pump(lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert connected
        assert dialog.sidebar.currentItem().text() == "常规"
        assert dialog.mod_panel is None
        assert bytes(socket.readAll()) == b""
    finally:
        socket.abort()
        receiver.close()
        lock.unlock()


def test_navigation_unavailable_reports_failure_once_and_finishes(tmp_path):
    from pet.settings_extension_navigation import AiSettingsRequest

    failures = []
    request = AiSettingsRequest(tmp_path, lambda: failures.append(True), timeout_ms=200)
    pump(lambda: request.finished)
    app.processEvents()
    assert failures == [True]


@pytest.mark.parametrize("state", ["disabled", "enabled"], ids=["saved-off", "saved-on"])
def test_notification_uses_the_preference_saved_during_a_request(installed, state):
    shell, _manager, mount = installed
    received, release = threading.Event(), threading.Event()

    class Unauthorized(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.set()
            if not release.wait(timeout=40):
                return
            body = b'{"error":{"message":"invalid API key"}}'
            self.send_response(401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Unauthorized)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    background = QWidget()
    try:
        config = mount.runtime.config
        settings = config.chat_settings()
        provider = settings.active_config
        provider.base_url = f"http://127.0.0.1:{server.server_port}"
        provider.api_key_ref = config.save_provider_secret(provider, "test-only-key")
        config.set_chat_settings(settings)
        config.set("system_notifications_enabled", state == "disabled")
        config.save()
        window = mount.chat()
        background.show()
        background.activateWindow()
        pump(background.isActiveWindow)
        window.hide()
        window.input.setPlainText("change the notification preference during this request")
        window.send_message()
        pump(received.is_set)
        shell.instance.open_modern_settings(initial_page="extension:official.ai-chat")
        pump(lambda: shell.instance.modern_settings_dialog is not None)
        panel = shell.instance.modern_settings_dialog.mod_panel
        panel.component.page.system_notify_check.setChecked(state == "enabled")
        QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
        assert not panel.dirty()
        # A later unsaved draft must neither change notification behavior nor be lost.
        panel.component.page.key.setText("unsaved-test-draft")
        panel.component.page.system_notify_check.setChecked(state != "enabled")
        release.set()
        pump(lambda: window.service.is_drained)
        assert bool(shell._toast_windows) == (state == "enabled")
        assert panel.component.page.key.text() == "unsaved-test-draft"
        assert panel.dirty()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=10)
        background.close()


def test_deep_linked_extension_rows_never_enter_the_core_search_index(installed):
    """带 extension: 深链接冷启动后收走面板，搜索框不许撞已删除的 C++ 行。

    面板要被收走是正常操作（MOD 中心对同一扩展再点一次「设置」、包停用/卸载、
    宿主转 fault 都会 dispose + deleteLater）。这些行若在构造期被收进
    ``_search_rows`` 快照，收走之后每次按键都会抛
    ``libshiboken: Internal C++ object (SettingRow) already deleted``。
    """
    shell, _manager, _mount = installed
    shell.instance.open_modern_settings(initial_page="extension:official.ai-chat")
    pump(lambda: shell.instance.modern_settings_dialog is not None)
    dialog = shell.instance.modern_settings_dialog
    assert dialog.mod_panel_owner == OWNER
    panel_rows = set(dialog.mod_panel.findChildren(SettingRow))
    assert panel_rows, "扩展面板应当自带设置行"
    assert not panel_rows & set(dialog._search_rows), "扩展面板的行不许进 Core 搜索索引"
    close_extension_settings(dialog)
    pump(lambda: not isValid(next(iter(panel_rows))))
    dialog._search_settings("api")  # 修复前：RuntimeError: Internal C++ object already deleted


def test_a_successful_send_restores_the_provider_header(installed):
    """配置错误提示占用过表头；请求通过后必须还原，而不是一直挂着「打开 API 设置」。"""
    shell, _manager, mount = installed
    window = mount.chat()
    window.input.setPlainText("先撞一次缺 Key")
    window.send_message()
    assert 'href="api-settings"' in window.provider_label.text()
    config = mount.runtime.config
    settings = config.chat_settings()
    provider = settings.active_config
    provider.base_url = "http://127.0.0.1:1"
    provider.api_key_ref = config.save_provider_secret(provider, "test-only-key")
    config.set_chat_settings(settings)
    config.save()
    window.input.setPlainText("配好 Key 再发一次")
    window.send_message()
    assert 'href="api-settings"' not in window.provider_label.text()
    assert window.provider_label.text() == window.settings.active_config.model
    window.service.stop()
    pump(lambda: window.service.is_drained)


def test_navigation_failure_is_reported_instead_of_a_premature_ok(installed):
    """面板没挂上（草稿门取消 / 目标包无设置界面）时，点击方必须拿到失败。

    应答若在导航之前发出，点击方只会看到窗口被拉到前台、面板空白，而且
    永远等不到 App 层的失败提示。
    """
    from PySide6.QtCore import QLockFile

    from pet.settings_extension_navigation import AiSettingsReceiver, AiSettingsRequest

    shell, _manager, _mount = installed
    shell.instance.open_modern_settings()
    dialog = shell.instance.modern_settings_dialog
    assert dialog.mod_panel is None
    failures = []
    lock = QLockFile(str(shell.config.dir / "settings.lock"))
    assert lock.tryLock(0)
    receiver = AiSettingsReceiver(shell.config.dir, dialog)
    original = dialog.select_page
    dialog.select_page = lambda label: False if str(label).startswith("extension:") else original(label)
    try:
        request = AiSettingsRequest(shell.config.dir, lambda: failures.append(True))
        pump(lambda: request.finished, timeout=15)
        app.processEvents()
        assert failures == [True], "面板没挂上时点击方必须拿到失败"
    finally:
        dialog.select_page = original
        receiver.close()
        lock.unlock()
