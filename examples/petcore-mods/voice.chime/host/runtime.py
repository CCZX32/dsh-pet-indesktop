"""语音报时运行时：调度 tick、免打扰、气泡/动画与 60 秒预合成。

**本模块不 import PySide6，也不合成音频**：合成、缓存、播放与失败分类都在
core（``HostPorts.speech``）；这里只决定「什么时候说、说什么、说不说得出来」。
调度回调由 ``scheduler.call_every`` 保证在 GUI 线程执行，``speak`` 的回调同样
回到 GUI 线程（``CoreSpeechPort`` 用 ``call_later(0)`` 排队），因此气泡与动画
不需要自己跨线程。

失败一律变成用户可见的强制气泡（``force=True``），不静默：合成失败最常见的原因
是网络、密钥或后端不可用，用户看不到声音时至少要知道为什么。
"""

from __future__ import annotations

import threading
from datetime import datetime

from petcore.contracts.speech import SpeechError, SpeechRequest

from . import quotes, schedule

#: 轮询间隔：报时精度是分钟，25 秒足够且一天不到 3500 次空转。
TICK_INTERVAL_MS = 25_000
#: 报时气泡展示时长。
BUBBLE_DURATION_MS = 8_000
#: 距下一报时点 ≤ 该秒数时提前合成进缓存，到点即出声。
PRECACHE_WINDOW_S = 60.0
#: 默认报时动画（空串表示不动画；配置里写成 ``False`` 同样视为关闭）。
DEFAULT_ANIMATION = "悠闲哼歌"

#: 失败分类 → 用户能看懂的一句话（稳定分类见 ``contracts.speech``）。
ERROR_TEXT = {
    "unavailable": "语音后端不可用（检查扩展与音频设备）",
    "network": "网络连接失败",
    "timeout": "请求超时",
    "auth": "密钥未配置或已失效",
    "rate_limit": "请求过于频繁",
    "protocol": "服务返回的内容无法识别",
    "cache": "缓存读写失败",
}


def _reason_text(error) -> str:
    reason = str(getattr(error, "reason", "") or "unavailable")
    return ERROR_TEXT.get(reason, "语音合成失败")


class ChimeRuntime:
    def __init__(self, context) -> None:
        self.context = context
        self.commands = {"now": self.speak_now}
        self._handle: str | None = None
        self._last_fired = ""
        self._precache_thread: threading.Thread | None = None
        self._precache_lock = threading.Lock()
        self._stopped = False

    # ------------------------------------------------------------ 配置
    def _get(self, key: str, default):
        config = getattr(self.context.ports, "config", None)
        if config is None:
            return default
        try:
            value = config.get(key, default)
        except Exception:  # noqa: BLE001 - 配置异常不该让报时停摆
            return default
        return default if value is None else value

    def _enabled(self) -> bool:
        return bool(self._get("voice_chime_enabled", False))

    def _schedule(self) -> str:
        return schedule.normalize_schedule(self._get("voice_chime_schedule", "hourly"))

    def _times(self) -> tuple[str, ...]:
        return schedule.parse_times(self._get("voice_chime_times", []))

    def _show_bubble(self) -> bool:
        return bool(self._get("voice_chime_show_bubble", True))

    def _animation(self) -> str:
        value = self._get("voice_chime_anim", DEFAULT_ANIMATION)
        if value is False or value is None:
            return ""
        return str(value).strip()

    def _pool(self) -> tuple[str, ...]:
        return quotes.pool(self._get("voice_chime_quotes", []))

    def _request(self, text: str) -> SpeechRequest:
        try:
            rate = float(self._get("voice_chime_rate", 1.0))
        except (TypeError, ValueError):
            rate = 1.0
        try:
            volume = float(self._get("voice_chime_volume", 1.0))
        except (TypeError, ValueError):
            volume = 1.0
        return SpeechRequest(
            text=text,
            provider=str(self._get("voice_chime_provider", "") or "").strip(),
            voice=str(self._get("voice_chime_voice", "") or "").strip(),
            rate=max(0.5, min(2.0, rate)),
            volume=max(0.0, min(1.0, volume)),
        )

    # ------------------------------------------------------------ 端口取值
    def _presentation(self):
        return getattr(self.context.ports, "presentation", None)

    def _speech(self):
        return getattr(self.context.ports, "speech", None)

    def _quiet(self) -> bool:
        quiet = getattr(self.context.ports, "quiet", None)
        if quiet is None:
            return False
        try:
            return bool(quiet.quiet_active())
        except Exception:  # noqa: BLE001 - 免打扰端口异常按「不静音」处理
            return False

    # ------------------------------------------------------------ 调度
    def tick(self, now: datetime | None = None) -> None:
        """一次调度判定；``now`` 只为测试注入固定时刻，生产路径由 tick 现读。"""
        if self._stopped or not self._enabled():
            return
        moment = now or datetime.now()
        schedule_key = self._schedule()
        times = self._times()
        slot = schedule.is_due(moment, schedule_key, times, self._last_fired)
        if not slot:
            self._maybe_precache(moment, schedule_key, times)
            return
        # 先盖章再出声：免打扰期间被丢弃的报时不补播（时间敏感的提醒过期没意义）。
        self._last_fired = slot
        self._deliver(moment, schedule_key, times)

    def _tick(self) -> None:
        self.tick()

    def speak_now(self) -> None:
        """菜单「立即报时」：手动触发不占调度槽位，允许与自动报时同分钟并存。"""
        presentation = self._presentation()
        if not self._enabled():
            if presentation is not None:
                presentation.say(
                    "语音报时已关闭：设置 → 扩展管理 → 语音报时",
                    duration_ms=5_000,
                    force=True,
                )
            return
        self._deliver(datetime.now(), self._schedule(), self._times())

    def _deliver(self, moment: datetime, schedule_key: str, times) -> None:
        if self._quiet():
            return
        presentation = self._presentation()
        speech = self._speech()
        quote = schedule.pick_quote(self._pool(), moment, schedule_key, times)
        if speech is None:
            if presentation is not None:
                presentation.say(
                    "语音端口不可用：请更新 core 后再试",
                    duration_ms=6_000,
                    force=True,
                )
            return
        self._play_animation(presentation)
        try:
            speech.speak(
                self._request(quotes.spoken_text(moment, quote)),
                on_done=self._on_done,
                on_error=self._on_error,
            )
        except Exception as exc:  # noqa: BLE001 - 端口异常同样要变成可见气泡
            self._on_error(SpeechError("unavailable", type(exc).__name__))
        if self._show_bubble() and presentation is not None:
            presentation.say(
                quotes.bubble_text(moment, quote),
                duration_ms=BUBBLE_DURATION_MS,
                force=True,
            )

    def _play_animation(self, presentation) -> None:
        name = self._animation()
        if not name or presentation is None:
            return
        try:
            presentation.play_animation(name, loop=False)
        except Exception:  # noqa: BLE001 - 动画是装饰，失败不影响报时
            pass

    def _on_done(self, _result) -> None:
        return

    def _on_error(self, error) -> None:
        presentation = self._presentation()
        if presentation is None:
            return
        presentation.say(
            f"语音合成失败：{_reason_text(error)}",
            duration_ms=6_000,
            force=True,
        )

    # ------------------------------------------------------------ 预合成
    def _maybe_precache(self, moment: datetime, schedule_key: str, times) -> None:
        """距下一报时点 ≤ 60 秒时，后台合成该次报时音频写进 core 缓存。

        只起一个线程：上一轮合成还在飞（网络慢）时直接放弃，下一拍（25 秒内）
        还会再判一次；窗口有 60 秒，够用且不会堆线程。
        """
        if self._quiet():
            return
        speech = self._speech()
        if speech is None:
            return
        remaining = schedule.seconds_until_due(moment, schedule_key, times)
        if remaining is None or remaining > PRECACHE_WINDOW_S:
            return
        target = schedule.next_due(moment, schedule_key, times)
        if target is None:
            return
        quote = schedule.pick_quote(self._pool(), target, schedule_key, times)
        request = self._request(quotes.spoken_text(target, quote))
        with self._precache_lock:
            running = self._precache_thread
            if running is not None and running.is_alive():
                return
            thread = threading.Thread(
                target=self._precache_work,
                args=(speech, request),
                name="voice-chime-precache",
                daemon=True,
            )
            self._precache_thread = thread
            thread.start()

    @staticmethod
    def _precache_work(speech, request: SpeechRequest) -> None:
        """后台线程：只合成，不出声、不弹气泡；失败由到点的即时合成兜底。"""
        try:
            speech.synthesize(request)
        except Exception:  # noqa: BLE001 - 预合成失败是常态（离线/无密钥）
            return

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        self._stopped = False
        if self._handle is not None:
            return
        scheduler = getattr(self.context.ports, "scheduler", None)
        if scheduler is None:
            return
        self._handle = scheduler.call_every(TICK_INTERVAL_MS, self._tick)

    def stop(self) -> None:
        self._stopped = True
        scheduler = getattr(self.context.ports, "scheduler", None)
        if self._handle is not None and scheduler is not None:
            try:
                scheduler.cancel(self._handle)
            except Exception:  # noqa: BLE001 - 调度器已收摊
                pass
        self._handle = None

    def close(self) -> None:
        self.stop()
