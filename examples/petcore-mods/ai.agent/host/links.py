"""联动状态机：六态 → 联动动作 / 过程气泡 / 完成通知 / 音效。

无 Qt、无文件 IO：runtime 把解析后的事件喂进 ``handle()``，呈现经由注入的
``bridge`` 完成。时钟与延后调用都可注入，因此整条状态机可以脱离事件循环测试。

``bridge`` 需要提供：

* ``prefs() -> LinkPrefs``：每次判定现取，设置改完立即生效；
* ``visible() -> bool``：隐藏态不切动画；
* ``animations() -> tuple[str, ...]``：当前角色的动作名；
* ``play_animation(name)`` / ``reset_idle()`` / ``say(text, important=False)``；
* ``play_sound(kind)``：``kind`` 为 ``start`` / ``done`` / ``error``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .protocol import BUSY_STATES, AgentEvent, activity_text

#: 联动动作池：主动作严格交替，每第 3 次插播一个「摸鱼」动作（同主分支）。
MAIN_ANIMATIONS = ("写代码", "吃Token")
BREAK_ANIMATIONS = ("轻快记录", "漂浮踏步")
MAIN_KEYWORDS = ("代码", "工作", "写", "打字", "敲")
BREAK_KEYWORDS = ("记录", "踏步", "伸懒腰")

#: busy → 非 busy 的稳定确认窗口：过滤 working→idle→working 抖动。
DONE_CONFIRM_MS = 800
#: 同一 Agent 完成通知的最小间隔（最后一道保险）。
DONE_COOLDOWN_S = 5.0
#: 过程气泡节流：同 Agent / 全局 / 同一文案。
ACTIVITY_MIN_INTERVAL_S = 10.0
ACTIVITY_GLOBAL_MIN_S = 8.0
ACTIVITY_SAME_LABEL_S = 60.0
#: 音效冷却（默认值，可被配置覆盖）。
SOUND_COOLDOWN_S = 2.0

ERROR_TEXT = "好像遇到报错了…"
ATTENTION_TEXT = "这边需要你看一眼～"
DONE_TEXT = "干完活啦～"
DONE_ERROR_TEXT = "这轮好像没能跑完…"
START_TEXT = "开始干活啦～"


@dataclass(frozen=True, slots=True)
class LinkPrefs:
    """一次判定读到的配置快照。"""

    animation: bool = True
    activity: bool = True
    done: bool = True
    sound: bool = False
    min_interval: float = 2.0
    sound_cooldown: float = SOUND_COOLDOWN_S


class LinkEngine:
    def __init__(
        self,
        bridge,
        *,
        schedule: Callable[[int, Callable[[], None]], object],
        cancel: Callable[[object], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bridge = bridge
        self._schedule = schedule
        self._cancel = cancel
        self._clock = clock
        # (agent, writer) → 写者各自的原始状态。多实例 DSH 各写一份，
        # 一个实例回待机不能把另一个实例的忙判成待机。
        self._raw: dict[tuple[str, str], str] = {}
        # agent → (上次生效的折叠状态, 时刻)，只用于动画/普通气泡节流。
        self._applied: dict[str, tuple[str, float]] = {}
        self._done_handle: dict[str, object] = {}
        self._done_cooldown: dict[str, float] = {}
        self._last_activity: dict[str, tuple[str, float]] = {}
        self._activity_global_last = 0.0
        self._sound_at: dict[tuple[str, str], float] = {}
        self._link_seq = 0

    # ------------------------------------------------------------ 查询

    def states(self) -> dict[str, str]:
        """各 Agent 的折叠状态（设置页诊断用）。"""
        agents = {agent for agent, _writer in self._raw}
        return {agent: self._fold(agent) for agent in sorted(agents)}

    def any_busy(self) -> bool:
        return any(state in BUSY_STATES for state in self.states().values())

    def reset(self) -> None:
        for handle in self._done_handle.values():
            self._cancel(handle)
        self._done_handle.clear()
        self._raw.clear()
        self._applied.clear()
        self._link_seq = 0

    def close(self) -> None:
        self.reset()

    # ------------------------------------------------------------ 入口

    def handle(self, event: AgentEvent, *, writer: str = "default") -> None:
        if not event.state:
            return
        agent = event.agent or "agent"
        key = (agent, writer or "default")
        prev_raw = self._raw.get(key, "")
        folded_before = self._fold(agent)
        self._raw[key] = event.state
        folded_after = self._fold(agent)
        now = self._clock()

        self._maybe_activity(agent, event, now)

        if event.state in BUSY_STATES:
            if prev_raw not in BUSY_STATES:
                self._sound(agent, "start", now)
            self._on_busy(agent, folded_before, now)
        elif event.state == "error":
            if prev_raw in BUSY_STATES:
                self._schedule_done(agent, cause="error")
            else:
                self._important(ERROR_TEXT)
                self._sound(agent, "error", now)
        elif event.state == "attention":
            if prev_raw not in BUSY_STATES:
                self._important(ATTENTION_TEXT)
        if folded_before in BUSY_STATES and folded_after not in BUSY_STATES:
            self._schedule_done(agent, cause=self._failure_cause(agent))
        if folded_before not in BUSY_STATES and folded_after in BUSY_STATES:
            self._cancel_done(agent)

    # ------------------------------------------------------------ 内部

    def _fold(self, agent: str) -> str:
        states = [state for (name, _writer), state in self._raw.items() if name == agent]
        if not states:
            return ""
        if any(state in BUSY_STATES for state in states):
            return "working"
        for candidate in ("error", "attention", "sleeping", "idle"):
            if candidate in states:
                return candidate
        return ""

    def _failure_cause(self, agent: str) -> str:
        states = [state for (name, _writer), state in self._raw.items() if name == agent]
        return "error" if "error" in states else "done"

    def _prefs(self) -> LinkPrefs:
        prefs = self._bridge.prefs()
        return prefs if isinstance(prefs, LinkPrefs) else LinkPrefs()

    def _throttled(self, agent: str, now: float) -> bool:
        prefs = self._prefs()
        last = self._applied.get(agent)
        return bool(last is not None and (now - last[1]) < prefs.min_interval)

    def _on_busy(self, agent: str, folded_before: str, now: float) -> None:
        prefs = self._prefs()
        if folded_before in BUSY_STATES and self._throttled(agent, now):
            return
        self._applied[agent] = ("working", now)
        if not prefs.animation or not self._bridge.visible():
            return
        name = self._next_animation()
        if name:
            self._bridge.play_animation(name)

    def _next_animation(self) -> str:
        acts = tuple(self._bridge.animations() or ())
        if not acts:
            return ""
        main = [name for name in MAIN_ANIMATIONS if name in acts]
        if not main:
            main = [name for name in acts if any(key in name for key in MAIN_KEYWORDS)]
        brk = [name for name in BREAK_ANIMATIONS if name in acts]
        if not brk:
            brk = [name for name in acts if any(key in name for key in BREAK_KEYWORDS)]
        if not main and not brk:
            main = list(acts)
        self._link_seq += 1
        if brk and self._link_seq % 3 == 0:
            return brk[(self._link_seq // 3 - 1) % len(brk)]
        pool = main or brk
        return pool[(self._link_seq - 1) % len(pool)]

    def _maybe_activity(self, agent: str, event: AgentEvent, now: float) -> None:
        if event.state not in BUSY_STATES:
            return
        text = activity_text(event)
        if not text:
            return
        prefs = self._prefs()
        if not prefs.activity:
            return
        last = self._last_activity.get(agent)
        if last is not None:
            last_text, last_at = last
            if now - last_at < ACTIVITY_MIN_INTERVAL_S:
                return
            if last_text == text and now - last_at < ACTIVITY_SAME_LABEL_S:
                return
        if now - self._activity_global_last < ACTIVITY_GLOBAL_MIN_S:
            return
        self._last_activity[agent] = (text, now)
        self._activity_global_last = now
        self._bridge.say(text)

    def _important(self, text: str) -> None:
        self._bridge.say(text, important=True)

    def _sound(self, agent: str, kind: str, now: float) -> None:
        prefs = self._prefs()
        if not prefs.sound:
            return
        key = (agent, kind)
        last = self._sound_at.get(key)
        if last is not None and now - last < max(0.0, prefs.sound_cooldown):
            return
        self._sound_at[key] = now
        self._bridge.play_sound(kind)

    def _schedule_done(self, agent: str, *, cause: str) -> None:
        self._cancel_done(agent)
        prefs = self._prefs()
        if not prefs.done:
            return
        now = self._clock()
        if now - self._done_cooldown.get(agent, 0.0) < DONE_COOLDOWN_S:
            return
        self._done_handle[agent] = self._schedule(
            DONE_CONFIRM_MS, lambda agent=agent, cause=cause: self._finish(agent, cause)
        )

    def _cancel_done(self, agent: str) -> None:
        handle = self._done_handle.pop(agent, None)
        if handle is not None:
            self._cancel(handle)

    def _finish(self, agent: str, cause: str) -> None:
        self._done_handle.pop(agent, None)
        if self._fold(agent) in BUSY_STATES:
            # 确认窗口里又忙起来了：这轮没结束，不报完成。
            return
        now = self._clock()
        self._done_cooldown[agent] = now
        prefs = self._prefs()
        if not prefs.done:
            return
        if cause == "error":
            self._bridge.say(DONE_ERROR_TEXT, important=True)
            self._sound(agent, "error", now)
            return
        self._bridge.say(DONE_TEXT, important=True)
        self._sound(agent, "done", now)
        if self._bridge.visible():
            self._bridge.reset_idle()
