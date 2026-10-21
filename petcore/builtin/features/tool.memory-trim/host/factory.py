from __future__ import annotations

import os
import sys

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_checkbox


def _foreground_pid() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def trim_memory(*, skip_foreground: bool = True, min_size_mb: float = 50.0) -> tuple[int, int]:
    if sys.platform != "win32":
        return 0, 0
    try:
        import ctypes

        import psutil
    except Exception:
        return 0, 0

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    process_set_quota = 0x0100
    process_query_information = 0x0400
    foreground = _foreground_pid()
    trimmed = skipped = 0
    own = os.getpid()
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            pid = int(process.info["pid"])
            if pid in (0, 4, own) or (skip_foreground and pid == foreground):
                skipped += 1
                continue
            info = process.info.get("memory_info")
            if info is not None and info.rss / (1024 * 1024) < min_size_mb:
                skipped += 1
                continue
            handle = kernel32.OpenProcess(
                process_set_quota | process_query_information, False, pid
            )
            if not handle:
                skipped += 1
                continue
            try:
                if psapi.EmptyWorkingSet(handle):
                    trimmed += 1
                else:
                    skipped += 1
            finally:
                kernel32.CloseHandle(handle)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            skipped += 1
    return trimmed, skipped


class MemoryRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"trim": self.trim}

    def trim(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is not None and not bool(config.get("memory_trim_enabled", True)):
            return
        trimmed, skipped = trim_memory()
        presentation = self.context.ports.presentation
        if presentation is None:
            return
        if sys.platform != "win32":
            presentation.notify("回收内存", "仅在 Windows 上可用。", force=True)
        elif trimmed <= 0:
            presentation.notify(
                "回收内存",
                f"没有可回收的进程（跳过 {skipped} 个：前台、自己或体积太小）。",
                force=True,
            )
        else:
            presentation.notify(
                "回收内存",
                f"已回收 {trimmed} 个进程（跳过 {skipped} 个）。",
                force=True,
            )

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class MemoryPage(SettingsPage):
    title = "回收内存"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("memory_trim_enabled", True))
        card = self.section("Windows 工作集")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用回收内存", self.enabled, "只作用于其它进程；跳过前台、自己和系统关键进程。")
        self.add_note("非 Windows 平台不执行任何操作。回收内存是提示性操作，不保证系统立即释放。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("memory_trim_enabled", self.enabled.isChecked())
        self.changed.emit()

    def dirty(self) -> bool:
        return self.enabled.isChecked() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.enabled.isChecked()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial)
        self.enabled.blockSignals(False)
        self.config().set("memory_trim_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["回收", "内存", "工作集", "memory", "trim"]


def create_host(_context):
    return FeatureDefinition(
        owner="tool.memory-trim",
        contributions=(
            Contribution(
                kind="menu",
                id="trim",
                data={"label": "回收内存", "command": "trim", "order": 84, "icon": "clear"},
            ),
            Contribution(
                kind="settings_page",
                id="memory",
                data={"host_page": "about", "title": "回收内存", "order": 720, "icon": "clear"},
            ),
        ),
        runtime_factory=MemoryRuntime,
        settings_factory=MemoryPage,
    )
