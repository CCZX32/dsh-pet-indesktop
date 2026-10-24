"""Closing a settings window must not leave a timer calling a deleted QObject."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("delete_on_close", [False, True])
def test_subwindow_teardown_survives_owner_destruction(delete_on_close):
    code = r"""
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget
import shiboken6
from pet.app import AppShell
app = QApplication([])
owner = QWidget()
dialog = QDialog(owner)
dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, DELETE_ON_CLOSE)
dialog.show()
app.processEvents()
instance = SimpleNamespace(modern_settings_dialog=dialog)
shell = AppShell.__new__(AppShell)
shell._close_instance_subwindows(instance)
assert instance.modern_settings_dialog is None
# Parent ownership can destroy the child before a zero-delay callback runs.
owner.deleteLater()
QCoreApplication.sendPostedEvents(owner, QEvent.Type.DeferredDelete)
assert not shiboken6.isValid(dialog)
app.processEvents()
successor = QDialog()
successor.show()
app.processEvents()
successor.deleteLater()
QCoreApplication.sendPostedEvents(successor, QEvent.Type.DeferredDelete)
app.processEvents()
print("teardown-and-reopen: OK")
""".replace("DELETE_ON_CLOSE", repr(delete_on_close))
    proc = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1"),
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "teardown-and-reopen: OK" in proc.stdout


def test_settings_discard_then_next_window_in_fresh_process():
    """The actual two-test order that crashed with 0xC0000005, without Qt patches."""
    prefix = "tests/test_settings_stale_form_exit.py::"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short",
         prefix + "test_discarding_the_settings_close_lets_the_pet_exit",
         prefix + "test_app_quit_waits_for_the_settings_window"],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1"),
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "2 passed" in proc.stdout
