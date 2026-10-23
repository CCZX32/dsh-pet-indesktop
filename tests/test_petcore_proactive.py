"""主动识屏：白名单、停留、限额、去重与看门狗流程。"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

from petcore.contracts.screen import ScreenCapture, WindowInfo, WindowSample

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "ai.chat"


def _load_proactive():
    path = MOD_DIR / "host" / "proactive.py"
    spec = importlib.util.spec_from_file_location("ai_chat_proactive_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proactive = _load_proactive()


class Clock:
    def __init__(self, now: float | None = None) -> None:
        self.now = float(now if now is not None else _epoch(2026, 10, 23, 10, 0))

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _epoch(year: int, month: int, day: int, hour: int, minute: int) -> float:
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


class FakeConfig:
    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})
        self.writes: list[tuple[str, object]] = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[str(key)] = value
        self.writes.append((str(key), value))


class FakeQuiet:
    def __init__(self) -> None:
        self.active = False

    def quiet_active(self) -> bool:
        return self.active


class FakeSystem:
    def __init__(self, idle: float = 0.0) -> None:
        self.idle = idle

    def idle_seconds(self) -> float:
        return self.idle


class FakeScreen:
    def __init__(
        self,
        *,
        process: str = "chrome.exe",
        title: str = "报告",
        fingerprint: int = 0x1234,
        capture: bool = True,
        sample: bool = True,
    ) -> None:
        self.window = WindowInfo(
            hwnd=7, process=process, title=title, rect=(10, 10, 640, 480)
        )
        self.fingerprint = fingerprint
        self.capture_allowed = capture
        self.sample_allowed = sample
        self.capture_calls: list[int] = []
        self.sample_calls: list[int] = []

    def foreground_window(self):
        return self.window

    def sample_foreground(self, *, expected_hwnd: int = 0):
        self.sample_calls.append(int(expected_hwnd))
        if not self.sample_allowed:
            return None
        return WindowSample(
            hwnd=int(expected_hwnd),
            dh_hash=self.fingerprint,
            width=192,
            height=144,
            process=self.window.process,
            title=self.window.title,
            rect=self.window.rect,
        )

    def capture_foreground(self, *, expected_hwnd: int = 0):
        self.capture_calls.append(int(expected_hwnd))
        if not self.capture_allowed:
            return None
        return ScreenCapture(
            png=b"png",
            width=640,
            height=480,
            screen_name="fake",
            app_info=f"{self.window.process} | {self.window.title}",
            hwnd=int(expected_hwnd),
            dh_hash=self.fingerprint,
        )


class StubRuntime:
    def __init__(self, ports) -> None:
        self.context = SimpleNamespace(ports=ports)
        self.cues = 0
        self.asked: list[tuple] = []
        self.answers: list[tuple] = []
        self.pending: tuple | None = None

    def proactive_cue(self) -> None:
        self.cues += 1

    def proactive_ask(self, capture, app_info, *, on_done, on_fail) -> None:
        self.asked.append((capture, app_info))
        self.pending = (on_done, on_fail)

    def proactive_answer(self, text, *, app_info, sync_chat) -> None:
        self.answers.append((text, app_info, sync_chat))


def _ports(*, screen=None, config=None, quiet=None, system=None):
    return SimpleNamespace(
        screen=screen or FakeScreen(),
        config=config or FakeConfig(),
        quiet=quiet or FakeQuiet(),
        system=system or FakeSystem(0.0),
    )


def _watcher(ports, clock):
    runtime = StubRuntime(ports)
    watcher = proactive.ProactiveWatcher(
        runtime, clock=clock.time, monotonic=clock.monotonic
    )
    watcher._limiter = proactive.ProactiveLimiter(None, clock=clock.time)
    return watcher, runtime


def _enabled_config(**overrides):
    values = {
        "ai_proactive_enabled": True,
        "ai_proactive_whitelist": ["chrome.exe"],
        "ai_proactive_dwell_seconds": 45,
        "ai_proactive_min_interval_seconds": 60,
        "ai_proactive_cooldown_seconds": 300,
    }
    values.update(overrides)
    return FakeConfig(values)


# ------------------------------------------------------------------ 纯逻辑


def test_whitelist_matches_process_or_title_prefix() -> None:
    assert proactive.match_whitelist("chrome.exe", "任意标题", ["chrome.exe"])
    assert proactive.match_whitelist("CHROME.EXE", "任意标题", ["chrome.exe"])
    assert proactive.match_whitelist("chrome.exe", "任意标题", ["chrom*"])
    assert proactive.match_whitelist("foo.exe", "季度报告 - 浏览器", ["title:*报告*"])
    assert not proactive.match_whitelist("foo.exe", "季度报告", ["chrome.exe"])
    assert not proactive.match_whitelist("chrome.exe", "季度报告", ["title:报告"])
    assert not proactive.match_whitelist("chrome.exe", "季度报告", [])
    assert not proactive.match_whitelist("chrome.exe", "季度报告", ["", "   "])


def test_dwell_requires_the_same_window_for_enough_seconds() -> None:
    assert not proactive.dwell_satisfied(0.0, 100.0, 45)
    assert not proactive.dwell_satisfied(100.0, 130.0, 45)
    assert proactive.dwell_satisfied(100.0, 145.0, 45)
    assert proactive.dwell_satisfied(100.0, 999.0, 45)


def test_hamming_counts_differing_bits() -> None:
    assert proactive.hamming(0, 0) == 0
    assert proactive.hamming(0, 0b111) == 3
    assert proactive.hamming(0xFFFF, 0x0000) == 16


# ------------------------------------------------------------------ 限额


def test_limiter_enforces_daily_cap_and_cooldown(tmp_path: Path) -> None:
    clock = Clock()
    limiter = proactive.ProactiveLimiter(tmp_path / "state.json", clock=clock.time)
    kwargs = {"daily_cap": 2, "min_interval_seconds": 60, "cooldown_seconds": 300}
    assert limiter.acquire(**kwargs)
    assert not limiter.acquire(**kwargs), "最小间隔应拦住第二次"
    clock.advance(61)
    assert not limiter.acquire(**kwargs), "冷却应拦住第二次"
    clock.advance(300)
    assert limiter.acquire(**kwargs)
    clock.advance(400)
    assert not limiter.acquire(**kwargs), "日上限到了"
    clock.advance(86400)
    assert limiter.acquire(**kwargs), "跨日重新计数"


def test_limiter_pauses_for_the_day_after_three_failures(tmp_path: Path) -> None:
    clock = Clock()
    limiter = proactive.ProactiveLimiter(tmp_path / "state.json", clock=clock.time)
    kwargs = {"daily_cap": 15, "min_interval_seconds": 60, "cooldown_seconds": 300}
    for _ in range(3):
        limiter.record_failure()
        clock.advance(120)
    assert limiter.snapshot()["paused_until_date"] == "2026-10-23"
    assert not limiter.allow(**kwargs)
    clock.advance(86400)
    assert limiter.allow(**kwargs), "第二天恢复"


def test_limiter_state_survives_reload(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "state.json"
    limiter = proactive.ProactiveLimiter(path, clock=clock.time)
    limiter.acquire(daily_cap=5, min_interval_seconds=60, cooldown_seconds=300)
    again = proactive.ProactiveLimiter(path, clock=clock.time)
    assert again.snapshot()["count"] == 1


# ------------------------------------------------------------------ 看门狗


def test_watcher_requires_dwell_then_asks_once() -> None:
    clock = Clock()
    screen = FakeScreen()
    config = _enabled_config()
    watcher, runtime = _watcher(_ports(screen=screen, config=config), clock)

    watcher.tick()
    assert screen.sample_calls == [], "第一次 tick 只登记窗口，不采样"
    clock.advance(30)
    watcher.tick()
    assert screen.sample_calls == [], "停留不够不发请求"
    clock.advance(20)
    watcher.tick()
    assert screen.sample_calls == [7]
    assert screen.capture_calls == [7]
    assert runtime.cues == 1
    assert len(runtime.asked) == 1
    assert runtime.asked[0][1] == "chrome.exe | 报告"


def test_watcher_skips_when_window_changes() -> None:
    clock = Clock()
    screen = FakeScreen()
    watcher, runtime = _watcher(_ports(screen=screen, config=_enabled_config()), clock)
    watcher.tick()
    clock.advance(60)
    screen.window = WindowInfo(hwnd=8, process="chrome.exe", title="报告", rect=(0, 0, 1, 1))
    watcher.tick()
    assert screen.sample_calls == []
    assert runtime.asked == []
    clock.advance(60)
    watcher.tick()
    assert screen.sample_calls == [8]


def test_watcher_skips_similar_frames() -> None:
    clock = Clock()
    screen = FakeScreen(fingerprint=0b1111_0000)
    watcher, runtime = _watcher(
        _ports(screen=screen, config=_enabled_config()), clock
    )
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert len(runtime.asked) == 1
    runtime.pending[0]("第一次答复")
    clock.advance(400)
    screen.fingerprint = 0b1111_0001  # 只差 1 位，小于默认阈值 8
    watcher.tick()
    assert len(runtime.asked) == 1, "画面没变就不该再请求"


def test_watcher_asks_again_after_a_real_change() -> None:
    clock = Clock()
    screen = FakeScreen(fingerprint=0)
    watcher, runtime = _watcher(
        _ports(screen=screen, config=_enabled_config()), clock
    )
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert len(runtime.asked) == 1
    runtime.pending[0]("第一次答复")
    clock.advance(400)
    screen.fingerprint = 0xFFFFFFFF
    watcher.tick()
    assert len(runtime.asked) == 2


def test_watcher_dry_run_never_requests() -> None:
    clock = Clock()
    screen = FakeScreen()
    config = _enabled_config(ai_proactive_dry_run=True)
    watcher, runtime = _watcher(_ports(screen=screen, config=config), clock)
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert screen.sample_calls == [7]
    assert screen.capture_calls == [], "dry-run 不该抓大图"
    assert runtime.asked == []
    assert runtime.cues == 0
    assert watcher._limiter.snapshot().get("count", 0) == 0


def test_watcher_respects_quiet_mode() -> None:
    clock = Clock()
    quiet = FakeQuiet()
    quiet.active = True
    screen = FakeScreen()
    watcher, runtime = _watcher(
        _ports(screen=screen, config=_enabled_config(), quiet=quiet), clock
    )
    watcher.tick()
    clock.advance(120)
    watcher.tick()
    assert screen.sample_calls == []
    assert runtime.asked == []


def test_watcher_requires_idle_when_configured() -> None:
    clock = Clock()
    screen = FakeScreen()
    system = FakeSystem(idle=5.0)
    config = _enabled_config(
        ai_proactive_require_idle=True, ai_proactive_min_idle_seconds=30
    )
    watcher, runtime = _watcher(
        _ports(screen=screen, config=config, system=system), clock
    )
    watcher.tick()
    clock.advance(60)
    watcher.tick()
    assert runtime.asked == []
    system.idle = 90.0
    watcher.tick()
    assert len(runtime.asked) == 1


def test_watcher_empty_whitelist_disables_the_feature() -> None:
    clock = Clock()
    screen = FakeScreen()
    watcher, runtime = _watcher(
        _ports(screen=screen, config=_enabled_config(ai_proactive_whitelist=[])), clock
    )
    watcher.tick()
    clock.advance(120)
    watcher.tick()
    assert screen.sample_calls == []
    assert runtime.asked == []


def test_watcher_drops_frames_when_window_changed_during_sample() -> None:
    clock = Clock()
    screen = FakeScreen(sample=False)
    watcher, runtime = _watcher(_ports(screen=screen, config=_enabled_config()), clock)
    watcher.tick()
    clock.advance(60)
    watcher.tick()
    assert screen.sample_calls == [7]
    assert screen.capture_calls == []
    assert runtime.asked == []


def test_watcher_ignores_late_callbacks_after_stop() -> None:
    clock = Clock()
    screen = FakeScreen()
    watcher, runtime = _watcher(_ports(screen=screen, config=_enabled_config()), clock)
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert len(runtime.asked) == 1
    pending = runtime.pending
    watcher.stop()
    pending[0]("迟到的答复")
    assert runtime.answers == [], "停用后的回调不许再冒泡"


def test_watcher_reports_failures_and_answers() -> None:
    clock = Clock()
    screen = FakeScreen()
    watcher, runtime = _watcher(_ports(screen=screen, config=_enabled_config()), clock)
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    watcher._failed(watcher._generation, "network")
    assert watcher._limiter.snapshot()["consecutive_failures"] == 1
    clock.advance(400)
    screen.fingerprint = 0xABCD
    watcher.tick()
    assert len(runtime.asked) == 2
    watcher._done(watcher._generation, "答复", "chrome.exe | 报告")
    assert runtime.answers == [("答复", "chrome.exe | 报告", True)]


def test_watcher_stays_silent_when_disabled_mid_flight() -> None:
    clock = Clock()
    screen = FakeScreen()
    config = _enabled_config()
    watcher, runtime = _watcher(_ports(screen=screen, config=config), clock)
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert len(runtime.asked) == 1
    config.set("ai_proactive_enabled", False)
    runtime.pending[0]("关掉之后的答复")
    assert runtime.answers == []


def test_watcher_does_nothing_when_disabled() -> None:
    clock = Clock()
    screen = FakeScreen()
    config = _enabled_config(ai_proactive_enabled=False)
    watcher, runtime = _watcher(_ports(screen=screen, config=config), clock)
    watcher.tick()
    clock.advance(120)
    watcher.tick()
    assert screen.sample_calls == []
    assert runtime.asked == []


def test_watcher_recovers_from_a_stuck_request() -> None:
    clock = Clock()
    screen = FakeScreen()
    watcher, runtime = _watcher(_ports(screen=screen, config=_enabled_config()), clock)
    watcher.tick()
    clock.advance(46)
    watcher.tick()
    assert len(runtime.asked) == 1
    # 请求永远不回调：3 分钟后忙碌标记自愈，下一次心跳可以继续采样。
    clock.advance(proactive.REQUEST_TIMEOUT_S + 10)
    watcher.tick()
    assert watcher._busy is False
    assert watcher._limiter.snapshot()["consecutive_failures"] == 1
    clock.advance(400)
    screen.fingerprint = 0xFFFF
    watcher.tick()
    assert len(runtime.asked) == 2
