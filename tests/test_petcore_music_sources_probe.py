"""媒体源探针：逐进程 WASAPI 音频会话 + 播放器窗口标题（纯逻辑、离线）。

这两个模块都是 Windows 专属的"证据源"，但真正需要守住的是合并 / 过滤 / 上限 /
异常吞掉这些纯逻辑；真实的 COM 会话与桌面枚举在本机另有实测（耗时口径写在两个
模块的 docstring 里）。所以这里替掉两个**刻意留出的测试接缝**：

- ``audio_sessions._enumerate_rows`` → 直接给原始会话行
- ``window_source._enumerate_rows`` / ``window_source._exe_for_pid`` → 直接给窗口行与进程名

于是 Linux CI 也跑得绿，不需要 COM、音频设备或一块真实的桌面。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "media.music"
HOST_PKG = "petcore_music_sources_host"


def _host_package():
    if HOST_PKG in sys.modules:
        return sys.modules[HOST_PKG]
    spec = importlib.util.spec_from_file_location(
        HOST_PKG,
        MOD_DIR / "host" / "__init__.py",
        submodule_search_locations=[str(MOD_DIR / "host")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[HOST_PKG] = module
    spec.loader.exec_module(module)
    return module


_host_package()
audio_sessions = importlib.import_module(f"{HOST_PKG}.audio_sessions")
window_source = importlib.import_module(f"{HOST_PKG}.window_source")


# ---------------------------------------------------------------- 替身


def _feed_sessions(monkeypatch, rows):
    """把原始会话行喂给 audio_sessions（接缝替换，不碰 COM）。"""
    monkeypatch.setattr(audio_sessions, "_enumerate_rows", lambda: rows)


def _feed_windows(monkeypatch, rows, names=None):
    """把窗口行与进程名喂给 window_source；返回每次进程名查询的 pid 序列。"""
    monkeypatch.setattr(window_source, "_enumerate_rows", lambda: rows)
    resolved = dict(names or {})
    calls: list[int] = []

    def _exe_for_pid(pid):
        calls.append(pid)
        return resolved.get(pid, "")

    monkeypatch.setattr(window_source, "_exe_for_pid", _exe_for_pid)
    return calls


# ---------------------------------------------------------------- audio_sessions


def test_audio_snapshot_without_sessions_is_empty(monkeypatch):
    _feed_sessions(monkeypatch, [])
    assert audio_sessions.snapshot() == ()


def test_audio_snapshot_merges_same_pid_and_takes_max_peak(monkeypatch):
    _feed_sessions(
        monkeypatch,
        [
            (4242, 0, False, 0.0, "cloudmusic.exe"),
            (4242, 1, False, 0.42, ""),
        ],
    )
    sessions = audio_sessions.snapshot()
    assert len(sessions) == 1
    session = sessions[0]
    assert (session.pid, session.exe, session.state, session.muted) == (4242, "cloudmusic.exe", "active", False)
    assert session.peak == pytest.approx(0.42)


def test_audio_mute_requires_every_session_muted(monkeypatch):
    _feed_sessions(
        monkeypatch,
        [
            (10, 1, True, 0.0, "a.exe"),
            (10, 1, True, 0.0, "a.exe"),
            (20, 1, True, 0.0, "b.exe"),
            (20, 1, False, 0.0, "b.exe"),
        ],
    )
    muted = {session.pid: session.muted for session in audio_sessions.snapshot()}
    assert muted == {10: True, 20: False}


def test_audio_state_codes_map_to_three_states(monkeypatch):
    _feed_sessions(
        monkeypatch,
        [
            (1, 0, False, 0.0, "a.exe"),
            (2, 1, False, 0.0, "b.exe"),
            (3, 2, False, 0.0, "c.exe"),
        ],
    )
    states = {session.pid: session.state for session in audio_sessions.snapshot()}
    assert states == {1: "inactive", 2: "active", 3: "expired"}


def test_audio_unknown_state_code_is_not_reported_as_playing(monkeypatch):
    _feed_sessions(monkeypatch, [(1, 9, False, 0.5, "a.exe")])
    assert audio_sessions.snapshot()[0].state == "inactive"


def test_audio_drops_system_sessions_with_non_positive_pid(monkeypatch):
    _feed_sessions(
        monkeypatch,
        [
            (0, 1, False, 0.9, ""),
            (-7, 1, False, 0.9, "ghost.exe"),
            (5, 1, False, 0.1, "real.exe"),
        ],
    )
    assert [session.pid for session in audio_sessions.snapshot()] == [5]


def test_audio_peak_is_clamped_into_unit_range(monkeypatch):
    _feed_sessions(monkeypatch, [(1, 1, False, 1.7, "a.exe"), (2, 1, False, -0.3, "b.exe")])
    peaks = {session.pid: session.peak for session in audio_sessions.snapshot()}
    assert peaks == {1: 1.0, 2: 0.0}


def test_audio_snapshot_swallows_enumeration_errors_and_recovers(monkeypatch):
    def _boom():
        raise RuntimeError("COM 炸了")

    monkeypatch.setattr(audio_sessions, "_enumerate_rows", _boom)
    assert audio_sessions.snapshot() == ()
    _feed_sessions(monkeypatch, [(7, 1, False, 0.2, "a.exe")])
    assert [session.pid for session in audio_sessions.snapshot()] == [7]


def test_audio_available_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(audio_sessions, "_available", None)
    monkeypatch.setattr(audio_sessions, "sys", SimpleNamespace(platform="linux"))
    assert audio_sessions.available() is False


def test_audio_reset_clears_cached_endpoint(monkeypatch):
    monkeypatch.setattr(audio_sessions, "_manager", object())
    monkeypatch.setattr(audio_sessions, "_manager_thread", 1234)
    monkeypatch.setattr(audio_sessions, "_next_invalidate_at", 99.0)
    monkeypatch.setattr(audio_sessions, "_build_allowed_at", 99.0)
    audio_sessions.reset()
    assert audio_sessions._manager is None
    assert audio_sessions._manager_thread is None
    assert audio_sessions._next_invalidate_at == 0.0
    assert audio_sessions._build_allowed_at == 0.0


def test_audio_close_is_safe_without_initialised_com(monkeypatch):
    monkeypatch.setattr(audio_sessions._local, "initialized", False, raising=False)
    audio_sessions.close()  # 不该抛：没初始化过就不配对 CoUninitialize


# ---------------------------------------------------------------- window_source


def test_window_snapshot_filters_to_wanted_executables(monkeypatch):
    _feed_windows(
        monkeypatch,
        [(100, "歌名 - 歌手"), (200, "另一首 - 别人"), (300, "某文件夹")],
        {100: "cloudmusic.exe", 200: "foobar2000.exe", 300: "explorer.exe"},
    )
    windows = window_source.snapshot(frozenset({"CLOUDMUSIC.EXE"}))
    assert windows == (window_source.WindowInfo(pid=100, exe="cloudmusic.exe", title="歌名 - 歌手"),)


def test_window_snapshot_keeps_longest_title_per_pid(monkeypatch):
    _feed_windows(
        monkeypatch,
        [
            (100, "网易云音乐"),
            (100, "歌名 - 歌手 [网易云音乐]"),
            (100, "短"),
        ],
        {100: "cloudmusic.exe"},
    )
    windows = window_source.snapshot(frozenset({"cloudmusic.exe"}))
    assert [info.title for info in windows] == ["歌名 - 歌手 [网易云音乐]"]


def test_window_snapshot_applies_limit(monkeypatch):
    _feed_windows(
        monkeypatch,
        [(1, "a"), (2, "b"), (3, "c")],
        {1: "a.exe", 2: "b.exe", 3: "c.exe"},
    )
    windows = window_source.snapshot(frozenset({"a.exe", "b.exe", "c.exe"}), limit=2)
    assert [info.pid for info in windows] == [1, 2]


def test_window_snapshot_skips_windows_without_process_name(monkeypatch):
    _feed_windows(monkeypatch, [(100, "歌名 - 歌手"), (200, "歌名 - 歌手")], {200: "foobar2000.exe"})
    windows = window_source.snapshot(frozenset({"cloudmusic.exe", "foobar2000.exe"}))
    assert [info.pid for info in windows] == [200]


def test_window_snapshot_resolves_each_pid_once_per_sample(monkeypatch):
    calls = _feed_windows(
        monkeypatch,
        [(100, "a"), (100, "ab"), (100, "abc"), (200, "x")],
        {100: "cloudmusic.exe", 200: "cloudmusic.exe"},
    )
    window_source.snapshot(frozenset({"cloudmusic.exe"}))
    assert calls == [100, 200]


def test_window_snapshot_ignores_blank_titles_and_non_positive_pids(monkeypatch):
    _feed_windows(
        monkeypatch,
        [(0, "系统"), (100, "   "), (100, "歌名 - 歌手")],
        {0: "cloudmusic.exe", 100: "cloudmusic.exe"},
    )
    windows = window_source.snapshot(frozenset({"cloudmusic.exe"}))
    assert [(info.pid, info.title) for info in windows] == [(100, "歌名 - 歌手")]


def test_window_snapshot_without_wanted_exes_does_not_enumerate(monkeypatch):
    def _boom():
        raise AssertionError("没有目标进程时不该枚举窗口")

    monkeypatch.setattr(window_source, "_enumerate_rows", _boom)
    assert window_source.snapshot(frozenset()) == ()
    assert window_source.snapshot(frozenset({"cloudmusic.exe"}), limit=0) == ()


def test_window_snapshot_swallows_enumeration_errors(monkeypatch):
    def _boom():
        raise OSError("EnumWindows 失败")

    monkeypatch.setattr(window_source, "_enumerate_rows", _boom)
    assert window_source.snapshot(frozenset({"cloudmusic.exe"})) == ()


def test_window_available_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(window_source, "_available", None)
    monkeypatch.setattr(window_source, "sys", SimpleNamespace(platform="linux"))
    assert window_source.available() is False


# ---------------------------------------------------------------- 运行时代码纪律


#: 需要守纪律的运行期模块：整条识别/歌词链路 + 两个平台探针。
#: ``settings_page.py`` 是受信 UI（允许 QtWidgets），``__init__.py`` / ``factory.py`` 是装载入口。
_RUNTIME_MODULES = (
    "audio_sessions",
    "window_source",
    "recognizer",
    "sampling",
    "diagnostics",
    "title_clean",
    "now_playing",
    "lyrics",
    "players",
    "runtime",
)


@pytest.mark.parametrize("name", _RUNTIME_MODULES)
def test_runtime_modules_import_neither_qt_nor_host_packages(name):
    """运行期模块只许标准库 + 端口 + 惰性第三方；``petcore.contracts`` 是唯一例外。"""
    source = (MOD_DIR / "host" / f"{name}.py").read_text(encoding="utf-8")
    found = re.findall(
        # 注意顺序：`petcore` 必须排在 `pet` 前面，否则交替会先吃掉前缀、
        # 把 `petcore.contracts.http` 认成 `pet`（本用例真的这样误报过一次）。
        r"^\s*(?:from|import)\s+((?:PySide6|petcore|pet)(?:\.[\w.]+)?)",
        source,
        re.MULTILINE,
    )
    offenders = [item for item in found if not item.startswith("petcore.contracts")]
    assert offenders == []

