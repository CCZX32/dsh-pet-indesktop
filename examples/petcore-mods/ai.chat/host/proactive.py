"""主动识屏：白名单 → 停留 → 去重 → 限额 → 只冒气泡。

与「看看屏幕」的区别：后者由用户点一次、每次都发请求；这里由 Core 的定时器
每 8 秒看一眼前台窗口，只有「同一个窗口停了够久、画面确实变了、额度还够」才
发一次视觉请求，答复只冒气泡，不主动打开对话窗。

纯逻辑（白名单/停留/限额/指纹比较）与看门狗都在本文件，不碰 Qt；抓图与哈希由
Core 的 ``ScreenPort`` 提供（mod 不 import ``petcore.platform``）。
"""

from __future__ import annotations

import fnmatch
import json
import logging
import time
from pathlib import Path

LOG = logging.getLogger("petcore.mod.ai.chat.proactive")

#: 心跳：主分支同口径 8 秒一次。
TICK_INTERVAL_MS = 8000
#: 先兆气泡时长（先冒「让我看看……」，再等模型）。
PRE_CUE_MS = 2500
PRE_CUE_TEXT = "让我看看……"
#: 连续失败多少次后当日熔断（只写日志，不打扰用户）。
FAILURE_LIMIT = 3
#: 一次请求最多占住「忙碌」多久；线程意外卡死时靠它自愈，不让功能永久停摆。
REQUEST_TIMEOUT_S = 180.0
STATE_FILE = "proactive_state.json"

#: 端口缺值时的兜底，与 ``petcore.config.DEFAULTS`` 保持一致。
DEFAULTS = {
    "enabled": False,
    "whitelist": [],
    "dwell_seconds": 45,
    "change_threshold": 8,
    "daily_cap": 15,
    "cooldown_seconds": 300,
    "min_interval_seconds": 60,
    "require_idle": False,
    "min_idle_seconds": 30,
    "dry_run": False,
    "pre_cue": True,
    "sync_chat": True,
}


def match_whitelist(process: str, title: str, rules) -> bool:
    """进程名/标题白名单：无前缀只匹配进程名，``title:`` 前缀只匹配窗口标题。

    匹配是大小写不敏感的 ``fnmatch``（支持 ``*`` 与 ``?``）。空规则表返回
    ``False``——白名单为空时功能完全不工作，不是「全窗口都看」。
    """
    name = str(process or "").lower()
    caption = str(title or "").lower()
    for raw in rules or ():
        rule = str(raw or "").strip()
        if not rule:
            continue
        if rule.lower().startswith("title:"):
            pattern = rule[6:].strip().lower()
            if pattern and fnmatch.fnmatchcase(caption, pattern):
                return True
            continue
        if fnmatch.fnmatchcase(name, rule.lower()):
            return True
    return False


def dwell_satisfied(entered_at: float, now: float, dwell_seconds: float) -> bool:
    """同一个窗口已经停留够 ``dwell_seconds`` 秒。"""
    if entered_at <= 0:
        return False
    return (float(now) - float(entered_at)) >= max(0.0, float(dwell_seconds))


def hamming(first: int, second: int) -> int:
    return int(first ^ second).bit_count()


class ProactiveLimiter:
    """每日上限 + 最小请求间隔 + 冷却 + 连续失败熔断。

    状态落在 mod 自己的数据目录（``proactive_state.json``），原子写；文件损坏
    时按「今天还没用过」重新计数，不阻塞功能。
    """

    def __init__(self, path: Path | None, *, clock=time.time) -> None:
        self.path = Path(path) if path is not None else None
        self._clock = clock
        self._state = self._load()

    # ---------------------------------------------------------------- 持久化
    def _load(self) -> dict:
        if self.path is None:
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            LOG.warning("proactive state write failed", exc_info=True)

    # ---------------------------------------------------------------- 日期
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self._clock()))

    def _roll_day(self) -> None:
        today = self._today()
        if str(self._state.get("date") or "") != today:
            self._state["date"] = today
            self._state["count"] = 0

    # ---------------------------------------------------------------- 判定
    def allow(
        self,
        *,
        daily_cap: int,
        min_interval_seconds: float,
        cooldown_seconds: float,
    ) -> bool:
        """只判定，不改状态（抓图前先问一次，省一次无谓的截屏）。"""
        now = float(self._clock())
        self._roll_day()
        if str(self._state.get("paused_until_date") or "") == self._today():
            return False
        if int(self._state.get("count") or 0) >= max(1, int(daily_cap)):
            return False
        last_request = float(self._state.get("last_request") or 0.0)
        if last_request and now - last_request < max(0.0, min_interval_seconds):
            return False
        last_trigger = float(self._state.get("last_trigger") or 0.0)
        if last_trigger and now - last_trigger < max(0.0, cooldown_seconds):
            return False
        return True

    def acquire(
        self,
        *,
        daily_cap: int,
        min_interval_seconds: float,
        cooldown_seconds: float,
    ) -> bool:
        """判定并立刻盖戳（调用方拿到 True 就必须发请求）。"""
        if not self.allow(
            daily_cap=daily_cap,
            min_interval_seconds=min_interval_seconds,
            cooldown_seconds=cooldown_seconds,
        ):
            return False
        now = float(self._clock())
        self._state["count"] = int(self._state.get("count") or 0) + 1
        self._state["last_request"] = now
        self._state["last_trigger"] = now
        self._save()
        return True

    def record_success(self) -> None:
        if not self._state.get("consecutive_failures"):
            return
        self._state["consecutive_failures"] = 0
        self._save()

    def record_failure(self) -> None:
        failures = int(self._state.get("consecutive_failures") or 0) + 1
        self._state["consecutive_failures"] = failures
        if failures >= FAILURE_LIMIT:
            self._state["paused_until_date"] = self._today()
            self._state["consecutive_failures"] = 0
            LOG.warning(
                "proactive paused for today after %s consecutive failures", failures
            )
        self._save()

    # ---------------------------------------------------------------- 测试
    def snapshot(self) -> dict:
        return dict(self._state)


class ProactiveWatcher:
    """8 秒心跳的看门狗；配置每 tick 现读，设置保存即生效。"""

    def __init__(self, runtime, *, clock=time.time, monotonic=time.monotonic) -> None:
        self.runtime = runtime
        self._clock = clock
        self._monotonic = monotonic
        self._handle = ""
        self._generation = 0
        self._entered_hwnd = 0
        self._entered_at = 0.0
        self._baseline: int | None = None
        self._busy = False
        self._busy_since = 0.0
        self._limiter = ProactiveLimiter(None, clock=clock)

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        ports = self.runtime.context.ports
        scheduler = getattr(ports, "scheduler", None)
        if scheduler is None:
            return
        storage = getattr(ports, "storage", None)
        path = None
        if storage is not None:
            try:
                path = Path(storage.data_dir("ai.chat")) / STATE_FILE
            except Exception:
                path = None
        self._limiter = ProactiveLimiter(path, clock=self._clock)
        self._generation += 1
        schedule = getattr(scheduler, "call_every", None)
        if not callable(schedule):
            return
        try:
            self._handle = schedule(TICK_INTERVAL_MS, self.tick)
        except Exception:
            self._handle = ""
            LOG.warning("proactive timer could not start", exc_info=True)

    def stop(self) -> None:
        self._generation += 1
        self._busy = False
        scheduler = getattr(self.runtime.context.ports, "scheduler", None)
        handle, self._handle = self._handle, ""
        if scheduler is not None and handle:
            try:
                scheduler.cancel(handle)
            except Exception:
                pass
        self.reset_session()

    def reset_session(self) -> None:
        self._entered_hwnd = 0
        self._entered_at = 0.0
        self._baseline = None

    # ---------------------------------------------------------------- 配置
    def config(self) -> dict:
        port = getattr(self.runtime.context.ports, "config", None)
        values = dict(DEFAULTS)
        if port is None:
            return values
        for key in DEFAULTS:
            try:
                value = port.get(f"ai_proactive_{key}", None)
            except Exception:
                value = None
            if value is not None:
                values[key] = value
        rules = values.get("whitelist")
        values["whitelist"] = [
            str(rule).strip() for rule in rules if str(rule).strip()
        ] if isinstance(rules, list) else []
        return values

    # ---------------------------------------------------------------- 心跳
    def tick(self) -> None:
        config = self.config()
        if not config["enabled"] or not config["whitelist"]:
            self.reset_session()
            return
        if self._busy:
            if self._monotonic() - self._busy_since < REQUEST_TIMEOUT_S:
                return
            LOG.warning("proactive request timed out; clearing the busy flag")
            self._busy = False
            self._limiter.record_failure()
            return
        ports = self.runtime.context.ports
        quiet = getattr(ports, "quiet", None)
        if quiet is not None and self._quiet_active(quiet):
            return
        info = self._foreground_window()
        if info is None or not getattr(info, "rect", None):
            self.reset_session()
            return
        if not match_whitelist(
            getattr(info, "process", ""), getattr(info, "title", ""), config["whitelist"]
        ):
            self.reset_session()
            return
        now = self._monotonic()
        hwnd = int(getattr(info, "hwnd", 0) or 0)
        if hwnd != self._entered_hwnd:
            self._entered_hwnd = hwnd
            self._entered_at = now
            self._baseline = None
            return
        if not dwell_satisfied(self._entered_at, now, config["dwell_seconds"]):
            return
        if config["require_idle"] and self._idle_seconds() < config["min_idle_seconds"]:
            return
        if not self._limiter.allow(
            daily_cap=config["daily_cap"],
            min_interval_seconds=config["min_interval_seconds"],
            cooldown_seconds=config["cooldown_seconds"],
        ):
            return
        sample = self._sample_foreground(hwnd)
        if sample is None:
            return
        fingerprint = int(getattr(sample, "dh_hash", 0) or 0)
        if (
            fingerprint
            and self._baseline is not None
            and hamming(self._baseline, fingerprint) < int(config["change_threshold"])
        ):
            return
        if config["dry_run"]:
            LOG.info(
                "proactive dry-run: process=%s hwnd=%s dhash=%016x",
                getattr(info, "process", ""),
                hwnd,
                fingerprint,
            )
            self._baseline = fingerprint or None
            return
        capture = self._capture_foreground(hwnd)
        if capture is None:
            return
        if not self._limiter.acquire(
            daily_cap=config["daily_cap"],
            min_interval_seconds=config["min_interval_seconds"],
            cooldown_seconds=config["cooldown_seconds"],
        ):
            return
        # 基线固定用「缩略图采样」的指纹：下一轮 heartbeat 也只算这个口径，
        # 拿大图的哈希当基线会让每轮都被判成「变了」。
        self._baseline = fingerprint or None
        self._busy = True
        self._busy_since = self._monotonic()
        generation = self._generation
        app_info = (
            str(getattr(capture, "app_info", "") or "")
            or str(getattr(sample, "app_info", "") or "")
            or self._app_label(info)
        )
        if config["pre_cue"]:
            self.runtime.proactive_cue()
        try:
            self.runtime.proactive_ask(
                capture,
                app_info,
                on_done=lambda text: self._done(generation, text, app_info),
                on_fail=lambda reason: self._failed(generation, reason),
            )
        except Exception:
            self._busy = False
            self._limiter.record_failure()
            LOG.warning("proactive request could not start", exc_info=True)

    # ---------------------------------------------------------------- 回调
    def _done(self, generation: int, text: str, app_info: str) -> None:
        self._busy = False
        if generation != self._generation:
            return
        config = self.config()
        if not config.get("enabled"):
            return
        self._limiter.record_success()
        sync = bool(config.get("sync_chat", True))
        self.runtime.proactive_answer(text, app_info=app_info, sync_chat=sync)

    def _failed(self, generation: int, reason: str) -> None:
        self._busy = False
        if generation != self._generation:
            return
        self._limiter.record_failure()
        LOG.info("proactive request failed: %s", str(reason)[:120])

    # ---------------------------------------------------------------- 端口
    def _foreground_window(self):
        screen = getattr(self.runtime.context.ports, "screen", None)
        getter = getattr(screen, "foreground_window", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            LOG.debug("foreground window lookup failed", exc_info=True)
            return None

    def _sample_foreground(self, hwnd: int):
        screen = getattr(self.runtime.context.ports, "screen", None)
        getter = getattr(screen, "sample_foreground", None)
        if callable(getter):
            try:
                return getter(expected_hwnd=hwnd)
            except Exception:
                LOG.debug("foreground sample failed", exc_info=True)
                return None
        # 旧端口（没有 sample_foreground）退回整抓：哈希口径变了会多请求一次，
        # 但仍能把基线对齐到下一次采样。
        return self._capture_foreground(hwnd)

    def _capture_foreground(self, hwnd: int):
        screen = getattr(self.runtime.context.ports, "screen", None)
        getter = getattr(screen, "capture_foreground", None)
        if not callable(getter):
            return None
        try:
            return getter(expected_hwnd=hwnd)
        except Exception:
            LOG.debug("foreground capture failed", exc_info=True)
            return None

    def _idle_seconds(self) -> float:
        system = getattr(self.runtime.context.ports, "system", None)
        getter = getattr(system, "idle_seconds", None)
        if not callable(getter):
            return 0.0
        try:
            return float(getter())
        except Exception:
            return 0.0

    @staticmethod
    def _quiet_active(quiet) -> bool:
        getter = getattr(quiet, "quiet_active", None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:
            return False

    @staticmethod
    def _app_label(info) -> str:
        parts = [
            str(part)
            for part in (getattr(info, "process", ""), getattr(info, "title", ""))
            if part
        ]
        return " | ".join(parts)
