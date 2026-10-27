"""音乐运行时：轮询三源采样 → 判定 → 唱歌动画 / 歌词气泡 / 菜单命令（无 Qt）。

一秒一拍（``POLL_MS``）。**所有系统调用只跑在常驻后台线程**（``start()`` 起
``music-smtc``）：主分支实测在主线程查 SMTC 会永久阻塞窗口，所以 GUI 线程这一拍
只做「唤醒采样线程」；上一拍没回来就跳过（不排队、不堆积），结果经
``scheduler.call_later(0)`` 回到 GUI 线程再动动画与气泡。

## 三件事各有一条状态机

1. **识别**（``recognizer.decide``）：SMTC 为主源、音频会话判"在不在出声"、
   已登记播放器的窗口标题兜底。**读失败与"没在放"是两回事**：失败只记诊断，
   不动歌词、不动动画；"没在放"按暂停处理（冻结本地时钟），
   ``music_sing_grace_seconds`` 之后才解除唱歌循环。
2. **歌词**：每首曲子取一次词；失败按 ``LYRIC_RETRY_SECONDS`` 冷却重试，
   上限 ``LYRIC_MAX_ATTEMPTS`` 次并在第一次失败时说清原因。**同一行只冒一次**
   （``petcore/AGENTS.md`` 的硬规则），两句之间至少 ``MIN_BUBBLE_SECONDS``；
   ``say()`` 失败（隐藏 / 设置窗打开 / 让路）**不推进**行号，下一拍还试这一句。
3. **命令**：传输控制（``pause/next/prev/stop``）与打开播放器；SMTC 不可用时
   每条命令都**说清原因**（没有会话 / 播放器不支持 / 缺组件），不静默失败。

## 几条刻意的取舍

- **不因一次缺席清空歌词**：旧实现一次采样失败就 ``_forget_track()``，于是同一
  首歌被当成新歌重新联网取词、重放第一句、重启动画。现在只有"换了一首歌"才替换
  曲目状态，缺席只冻结时钟。
- **唱歌失败不永久放弃**：按 2^n 拍退避重试（上限 ``SING_BACKOFF_MAX_SECONDS``），
  切歌/开关变化立即重置。角色包没有「悠闲哼歌」时，补上素材后下一拍就能唱。
- **多宠逐只 lease**：``ports.pets`` 存在时按 slot 分别 ``play_animation`` /
  ``release_loop``，切宠不会再出现"A 的循环留在 A 身上、释放打到 B"。
- **每拍一个令牌**：迟到的采样结果直接丢弃，不覆盖更新的判定。

配置一律经 ``HostPorts.config`` **只读**读取（运行时不许持有/改写配置对象）；
歌词偏移是本次运行的会话状态，初始值来自 ``music_lyric_offset_seconds``。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import audio_sessions, now_playing, players, recognizer, sampling, window_source
from . import lyrics as lyrics_mod

#: 播放时让桌宠哼歌的动画名（角色包里 ``random/悠闲哼歌``）。
SING_ANIM = "悠闲哼歌"
#: 轮询间隔：与歌词/唱歌链路的既有口径一致，兼顾开销与切歌响应。
POLL_MS = 1000
#: 唱歌失败后的退避：第 n 次失败等 ``2^n`` 拍，封顶该值（秒）。**不永久放弃**。
SING_BACKOFF_MAX_SECONDS = 30.0
#: 曲目开始后先观察几拍再唱：纯音乐的歌词（占位文案 / lrclib 的 instrumental 标记）
#: 通常第一拍就到了，先等一拍能少唱一次"对纯音乐唱歌"。
INSTRUMENTAL_PROBE_TICKS = 1
#: 取词**在飞**时最多等几拍再唱。只在该曲真的有一次取词在途时生效：缓存命中/没网
#: 立刻失败（`_fetch_key` 被清）时不等，所以普通曲目的首句延迟不会变成"每次都等 3 秒"。
LYRIC_PROBE_MAX_TICKS = 3
#: 两句歌词气泡之间的最小间隔（秒）。
MIN_BUBBLE_SECONDS = 2.0
#: 取词失败后的冷却（秒），以及每曲最多尝试次数。
LYRIC_RETRY_SECONDS = 60.0
LYRIC_MAX_ATTEMPTS = 3
#: 「歌词对齐」每次的步长与循环区间（秒）。
OFFSET_STEP = 0.5
OFFSET_MIN = -3.0
OFFSET_MAX = 3.0
#: 「没在放」的确认拍数：缺席的宽限至少这么久，单拍抖动不许让唱歌循环闪断。
ABSENT_CONFIRM_TICKS = 2

DEFAULTS = {
    "music_enabled": True,
    "music_sing_enabled": True,
    "music_sing_grace_seconds": 5.0,
    "music_lyric_enabled": True,
    "music_lyric_lead_seconds": 0.3,
    "music_lyric_cache_limit": 80,
    "music_lyric_offset_seconds": 0.0,
    "music_browser_media_enabled": False,
    "music_player_paths": {},
    "music_player": "",
    "music_filter_enabled": False,
    "music_filter_extra_ids": "",
    "music_title_format": "",
}


def next_offset(current: float) -> float:
    """「歌词对齐」的下一档：+0.5 秒，超过上界回到下界。"""
    value = round(float(current) + OFFSET_STEP, 1)
    if value > OFFSET_MAX + 1e-6:
        return OFFSET_MIN
    return value


def _spawn_thread(work) -> None:
    threading.Thread(target=work, name="music-runtime", daemon=True).start()


@dataclass(frozen=True, slots=True)
class _Request:
    """一拍采样的输入（后台线程读它，GUI 线程写它）。"""

    browser_media_enabled: bool
    tracked_app_id: str
    allowed_ids: frozenset[str]
    title_format: str
    targets: frozenset[str]
    seq: int


class MusicRuntime:
    """轮询器 + 命令集合；所有外部依赖都留了可替换的接缝（单测用替身）。"""

    def __init__(self, context):
        self.context = context
        self.commands = {
            "pause": lambda: self.transport("pause"),
            "next": lambda: self.transport("next"),
            "prev": lambda: self.transport("prev"),
            "stop": lambda: self.transport("stop"),
            "lyric_align": self.lyric_align,
        }
        for key in players.player_keys():
            self.commands[f"open_{key}"] = (lambda player_key=key: self.open_player(player_key))

        # ---- 接缝（测试替换这几项，生产走模块函数） ----
        self.sample_smtc = now_playing.read_sample
        self.sample_audio = audio_sessions.snapshot
        self.sample_windows = window_source.snapshot
        self.decide = recognizer.decide
        # 传输控制：**必须是实例属性**。写成类属性会让 `self.control_playback(...)`
        # 变成绑定方法、把 self 塞进 action 位（四个播放命令会 100% 抛 TypeError，
        # 再被 except 吞成"系统媒体控制调用失败"）。
        self.control_playback = now_playing.transport
        self.fetch_lyrics = lyrics_mod.fetch_lyrics
        self.launch_player = players.launch
        self.background = _spawn_thread
        self.clock = time.monotonic

        self._timer: str | None = None
        self._worker: threading.Thread | None = None
        self._wake = threading.Event()
        self._closing = threading.Event()
        self._generation = 0
        self._started = False
        self._stopped = False
        self._pending: _Request | None = None
        self._inflight = False
        #: 每拍递增的采样令牌；落地时丢弃比已落地更旧的包（迟到/乱序）。
        self._seq = 0
        self._delivered_seq = 0
        self._app_id = ""
        self._track: recognizer.Track | None = None
        self._track_key: tuple[str, str] | None = None
        self._title = ""
        self._lines: tuple[lyrics_mod.LyricLine, ...] = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key: tuple[str, str] | None = None
        self._fetch_attempts = 0
        self._lyric_retry_at: float | None = None
        self._lyric_reported = False
        self._lyric_source = ""
        self._lyric_score = 0.0
        self._anchor_at: float = 0.0
        self._anchor_position = 0.0
        self._paused_at: float | None = None
        self._last_bubble_at: float | None = None
        self._probe_ticks = 0
        self._lyric_wait_ticks = 0
        #: 已经报过"认不出这首歌"的可执行名（同一台播放器只提示一次）。
        self._unknown_reported: str = ""
        #: ``{slot: presentation}``；``None`` 表示"单宠"（端口不支持 for_slot）。
        self._leases: dict[int | None, object] = {}
        self._sing_failures = 0
        self._next_sing_attempt = 0.0
        self._silent_since: float | None = None
        self._offset: float | None = None
        self.last_decision: object = None
        self.last_sample: sampling.Sample | None = None

    # ---------------------------------------------------------------- 配置

    @property
    def instrumental(self) -> bool:
        """当前曲目是否已被判定为纯音乐（纯音乐不唱、不显示歌词）。"""
        return self._instrumental

    @property
    def singing(self) -> bool:
        """唱歌动画当前是否由本运行时持着（``release_loop`` 尚未发出）。"""
        return bool(self._leases)

    def _config_value(self, key: str, default):
        port = getattr(self.context.ports, "config", None)
        if port is None:
            return default
        try:
            value = port.get(key, default)
        except Exception:
            return default
        return default if value is None else value

    def _flag(self, key: str, default: bool) -> bool:
        return bool(self._config_value(key, default))

    def _number(self, key: str, default: float, *, low: float, high: float) -> float:
        try:
            value = float(self._config_value(key, default))
        except (TypeError, ValueError):
            value = float(default)
        return max(low, min(high, value))

    def _grace_seconds(self) -> float:
        return self._number("music_sing_grace_seconds", DEFAULTS["music_sing_grace_seconds"], low=0.0, high=120.0)

    def _silence_limit(self, status: str) -> float:
        """多久的"没声音"才解除唱歌循环。

        ``paused``（播放器明确暂停）用用户配置的宽限；``absent``（什么都看不到：切歌
        瞬间、SMTC 抖动、播放器被关掉）**至少**观察 ``ABSENT_CONFIRM_TICKS`` 拍——
        否则用户把宽限设成 0 时，一次采样抖动就会让循环闪断重来。
        """
        grace = self._grace_seconds()
        if status == recognizer.STATUS_ABSENT:
            return max(grace, ABSENT_CONFIRM_TICKS * POLL_MS / 1000.0)
        return grace

    def _lead_seconds(self) -> float:
        return self._number("music_lyric_lead_seconds", DEFAULTS["music_lyric_lead_seconds"], low=-2.0, high=3.0)

    def _title_format(self) -> str:
        return str(self._config_value("music_title_format", "") or "").strip()

    def lyric_state_text(self) -> str:
        """给诊断用的一句话：歌词现在处在哪一步（命中源 / 分数 / 第几行 / 失败次数）。"""
        if self._instrumental:
            return "纯音乐（不出歌词、不唱）"
        if self._lines:
            where = (
                f"第 {self._lyric_index + 1} 行" if self._lyric_index >= 0 else "还没到第一句"
            )
            score = f" score={self._lyric_score:.2f}" if self._lyric_score else ""
            return f"{self._lyric_source or '未知源'}命中{score} · {where} / 共 {len(self._lines)} 行"
        if self._track is None:
            return "还没有识别到曲目"
        if self._fetch_attempts:
            return (
                f"取词失败 {self._fetch_attempts} 次"
                f"（上限 {LYRIC_MAX_ATTEMPTS} 次，冷却 {LYRIC_RETRY_SECONDS:.0f} 秒）"
            )
        return "还没开始取词"

    def lyric_offset(self) -> float:
        """当前歌词偏移（秒）：本次运行的会话状态，初值来自配置。"""
        if self._offset is None:
            self._offset = self._number(
                "music_lyric_offset_seconds", DEFAULTS["music_lyric_offset_seconds"], low=OFFSET_MIN, high=OFFSET_MAX
            )
        return self._offset

    def _allowed_ids(self) -> frozenset[str]:
        """「只识别已配置播放器」的识别名集合；空集合表示不过滤。"""
        if not self._flag("music_filter_enabled", False):
            return frozenset()
        paths = self._config_value("music_player_paths", {})
        extras = str(self._config_value("music_filter_extra_ids", "") or "")
        return now_playing.allowed_app_ids(paths if isinstance(paths, dict) else {}, extras=extras)

    def _preferred_app_id(self) -> str:
        """配置里的默认播放器：多会话同播时优先跟随它。"""
        key = str(self._config_value("music_player", "") or "").strip()
        return players.player_exe(key) if key else ""

    def _targets(self) -> frozenset[str]:
        """窗口标题源允许观察的可执行名（已知播放器 ∪ 用户配置 ∪ 额外识别名）。"""
        paths = self._config_value("music_player_paths", {})
        extras = str(self._config_value("music_filter_extra_ids", "") or "")
        return players.recognition_targets(paths if isinstance(paths, dict) else {}, extras)

    def _cache(self) -> lyrics_mod.LyricsCache | None:
        storage = getattr(self.context.ports, "storage", None)
        if storage is None:
            return None
        try:
            base = storage.data_dir("media.music") / "lyrics"
        except Exception:
            return None
        limit = int(self._number("music_lyric_cache_limit", DEFAULTS["music_lyric_cache_limit"], low=1, high=2000))
        return lyrics_mod.LyricsCache(base, limit=limit)

    # ---------------------------------------------------------------- 轮询

    def poll(self) -> None:
        """一拍：把三源采样交给后台线程，回来后再动动画/歌词。

        上一拍还没回来就跳过这一拍（不排队、不堆积）；采样线程不在（测试路径或
        线程起不来）时同步采样。
        """
        if self._stopped:
            return
        if not self._flag("music_enabled", True):
            self._release()
            self._forget_track()
            return
        # 令牌必须在两条路径（后台线程 / 同步兜底）上都有效：先自增再建请求，
        # 否则同步路径的 seq 恒为 0，迟到判断形同虚设。
        self._seq += 1
        request = _Request(
            browser_media_enabled=self._flag("music_browser_media_enabled", False),
            tracked_app_id=self._app_id or self._preferred_app_id(),
            allowed_ids=self._allowed_ids(),
            title_format=self._title_format(),
            targets=self._targets(),
            seq=self._seq,
        )
        if self._started:
            self._start_worker()
            if self._closing.is_set():
                return
        worker = self._worker
        if worker is not None and worker.is_alive():
            if self._inflight:
                return
            self._inflight = True
            self._pending = request
            self._wake.set()
            return
        self._consume(self._collect(request), request)

    def _collect(self, request: _Request) -> sampling.Sample:
        """三源采样（编排在 ``sampling.collect``，这里只注入运行时自己的探针接缝）。"""
        return sampling.collect(
            browser_media_enabled=request.browser_media_enabled,
            tracked_app_id=request.tracked_app_id,
            allowed_ids=request.allowed_ids,
            targets=request.targets,
            smtc=self.sample_smtc,
            audio=self.sample_audio,
            windows=self.sample_windows,
        )

    def _decide(self, sample: sampling.Sample, request: _Request):
        try:
            return self.decide(
                sample,
                allowed_ids=request.allowed_ids,
                title_format=request.title_format,
            )
        except Exception:
            return recognizer.Decision(
                status=recognizer.STATUS_ERROR, reasons=("识别判定失败。",)
            )

    def _worker_loop(self, closing, wake, generation: int) -> None:
        try:
            while not closing.is_set():
                if not wake.wait(1.0):
                    continue
                wake.clear()
                if closing.is_set():
                    break
                request = self._pending
                if request is None:
                    continue
                sample = self._collect(request)
                self._post(
                    lambda sample=sample, request=request: self._consume(sample, request),
                    generation,
                )
        finally:
            # 线程退出时关掉本线程的常驻事件循环，别把未关闭的 loop 留给 GC。
            now_playing.close_thread_loop()
            audio_sessions.close()

    # ---------------------------------------------------------------- 判定落地

    def _consume(self, sample: sampling.Sample, request: _Request) -> None:
        """在 GUI 线程落地一次采样（迟到/过期的包直接丢弃）。"""
        self._inflight = False
        if self._stopped or request.seq < self._delivered_seq:
            return
        self._delivered_seq = request.seq
        self.last_sample = sample
        decision = self._decide(sample, request)
        self._on_decision(decision, sample)

    def _on_decision(self, decision, sample: sampling.Sample) -> None:
        self.last_decision = decision
        now = self.clock()
        status = str(getattr(decision, "status", ""))
        if status == recognizer.STATUS_ERROR:
            # 读失败：不动歌词、不动动画；宽限期照常推进（长时间读不到就自然停下）。
            self._on_silence(now, status)
            return
        app_id = str(getattr(decision, "app_id", "") or "")
        if app_id:
            self._app_id = app_id
        track = getattr(decision, "track", None)
        if not bool(getattr(decision, "playing", False)):
            if not track and status == recognizer.STATUS_ABSENT:
                # 没有曲目也没有在播：保留上一首的歌词，只走宽限。
                self._on_silence(now, status)
                return
            if track is not None:
                self._adopt_track(track, now, playing=False)
            self._on_silence(now, status)
            return

        self._silent_since = None
        if self._paused_at is not None:
            # 本地时钟模式下暂停过：把基准顺延，恢复后歌词不跳句。
            self._anchor_at += max(0.0, now - self._paused_at)
            self._paused_at = None
        if track is None:
            # 只唱不取词：认得出"在放歌"但认不出是哪首（窗口标题解析不了）。
            self._say_unknown_once(str(getattr(decision, "exe", "") or ""))
            self._tick_singing(now, playing=True)
            return
        self._adopt_track(track, now, playing=True)
        self._maybe_fetch_lyrics(now)
        self._tick_singing(now, playing=True)
        self._sync_lyrics(track, now)

    def _say_unknown_once(self, exe: str) -> None:
        """认不出曲名时说一次（同一台播放器不重复）：用户要能分清"没歌"与"认不出"。"""
        if exe and exe == self._unknown_reported:
            return
        self._unknown_reported = exe
        label = exe or "这台播放器"
        self._say_sung(f"这首歌我认不出来（{label}），先陪你哼着", subtitle="")

    def _adopt_track(self, track, now: float, *, playing: bool) -> None:
        """把判定里的曲目落到运行时状态：换歌才重建，同一首只更新位置。"""
        key = track.key()
        if key != self._track_key:
            self._begin_track(track, now)
        else:
            self._title = str(getattr(track, "title", "") or self._title)
            position = getattr(track, "position", None)
            if position is not None:
                self._anchor_at = now
                self._anchor_position = float(position)
        if not playing and self._paused_at is None:
            self._paused_at = now

    def _begin_track(self, track, now: float) -> None:
        self._track = track
        self._track_key = track.key()
        self._title = str(track.title or "")
        self._lines = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key = None
        self._fetch_attempts = 0
        self._lyric_retry_at = None
        self._lyric_reported = False
        self._anchor_at = now
        self._anchor_position = float(getattr(track, "position", None) or 0.0)
        self._paused_at = None
        self._last_bubble_at = None
        self._sing_failures = 0
        self._next_sing_attempt = 0.0
        # 纯音乐先别唱：歌词（占位文案 / instrumental 标记）通常第一拍就到。
        self._probe_ticks = (
            INSTRUMENTAL_PROBE_TICKS if self._flag("music_lyric_enabled", True) else 0
        )
        self._lyric_wait_ticks = 0

    def _on_silence(self, now: float, status: str) -> None:
        if self._silent_since is None:
            self._silent_since = now
        if self._leases and (now - self._silent_since) >= self._silence_limit(status):
            self._release()

    def _forget_track(self) -> None:
        self._track = None
        self._track_key = None
        self._lines = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key = None
        self._fetch_attempts = 0
        self._lyric_retry_at = None
        self._lyric_source = ""
        self._lyric_score = 0.0
        self._anchor_at = 0.0
        self._anchor_position = 0.0
        self._paused_at = None
        self._probe_ticks = 0

    # ---------------------------------------------------------------- 唱歌

    def _presentation(self):
        return getattr(self.context.ports, "presentation", None)

    def _targets_for_pets(self) -> list[tuple[int | None, object]]:
        """每只宠一个呈现端口；端口不支持按 slot 路由时退回「当前活动宠」。"""
        base = self._presentation()
        if base is None:
            return []
        for_slot = getattr(base, "for_slot", None)
        if not callable(for_slot):
            return [(None, base)]
        registry = getattr(self.context.ports, "pets", None)
        handles = ()
        if registry is not None:
            try:
                handles = tuple(registry.pets() or ())
            except Exception:
                handles = ()
        slots = [int(getattr(handle, "slot", 0)) for handle in handles]
        if not slots:
            return [(None, base)]
        targets: list[tuple[int | None, object]] = []
        for slot in slots:
            try:
                targets.append((slot, for_slot(slot)))
            except Exception:
                continue
        return targets or [(None, base)]

    def _awaiting_lyrics(self) -> bool:
        """当前曲目是否有一次取词真的在飞（决定要不要为"别对纯音乐唱"多等几拍）。"""
        if not self._flag("music_lyric_enabled", True):
            return False
        if self._lines or self._instrumental or self._track_key is None:
            return False
        return self._fetch_key == self._track_key and self._fetch_attempts > 0

    def _tick_singing(self, now: float, *, playing: bool) -> None:
        if not playing:
            self._on_silence(now, recognizer.STATUS_PAUSED)
            return
        self._silent_since = None
        if not self._flag("music_sing_enabled", True) or self._instrumental:
            self._release()
            return
        targets = self._targets_for_pets()
        current = {slot for slot, _port in targets}
        # 宠关掉了/切走了：按 slot 释放，别让 A 的循环留在 A 身上。
        for slot in [slot for slot in self._leases if slot not in current]:
            self._release_slot(slot)
        if self._probe_ticks > 0:
            self._probe_ticks -= 1
            return
        if self._awaiting_lyrics() and self._lyric_wait_ticks < LYRIC_PROBE_MAX_TICKS:
            # 取词还没回来：等一下再看是不是纯音乐（纯音乐不该唱）。有上限，
            # 而且只在真的有取词在飞时生效，不会让普通曲目永远等不到。
            self._lyric_wait_ticks += 1
            return
        if targets and current and current <= set(self._leases):
            return
        if now < self._next_sing_attempt:
            return
        self._lease(targets, now)

    def _lease(self, targets, now: float) -> None:
        started: dict[int | None, object] = {}
        for slot, port in targets:
            if slot in self._leases:
                continue  # 已经在唱的宠别重启动画（多宠时新开一只会把别人的循环打断重来）
            try:
                ok = bool(port.play_animation(SING_ANIM, loop=True))
            except Exception:
                ok = False
            if ok:
                started[slot] = port
        if started:
            self._leases.update(started)
            self._sing_failures = 0
            self._next_sing_attempt = 0.0
            return
        self._sing_failures += 1
        # 2^n 拍退避，封顶 SING_BACKOFF_MAX_SECONDS。**永不永久放弃**：角色包补上
        # 「悠闲哼歌」后，最迟半分钟内就能唱起来（旧实现是 4 拍后彻底静默）。
        delay = min(SING_BACKOFF_MAX_SECONDS, float(2 ** min(self._sing_failures, 5)))
        self._next_sing_attempt = now + delay

    def _release_slot(self, slot) -> None:
        port = self._leases.pop(slot, None)
        if port is None:
            return
        try:
            port.release_loop()
        except Exception:
            return

    def _release(self) -> None:
        self._silent_since = None
        self._sing_failures = 0
        self._next_sing_attempt = 0.0
        for slot in list(self._leases):
            self._release_slot(slot)
        self._leases.clear()

    # ---------------------------------------------------------------- 歌词

    def _maybe_fetch_lyrics(self, now: float) -> None:
        if not self._flag("music_lyric_enabled", True):
            return
        if self._lines or self._instrumental or self._track_key is None:
            return
        if self._fetch_key == self._track_key:
            return  # 已有一轮在飞/已完成
        if self._fetch_attempts >= LYRIC_MAX_ATTEMPTS:
            return
        if self._lyric_retry_at is not None and now < self._lyric_retry_at:
            return
        self._start_fetch(self._track)

    def _start_fetch(self, track) -> None:
        if track is None:
            return
        key = track.key()
        if key is None or self._fetch_key == key:
            return
        http = getattr(self.context.ports, "http", None)
        if http is None:
            return
        cache = self._cache()
        self._fetch_key = key
        self._fetch_attempts += 1
        title, artist = track.title, track.artist
        album, duration = track.album, track.duration
        generation = self._generation

        def work() -> None:
            try:
                # 专辑与时长只用于候选打分（区分原唱/翻唱/现场版），不参与请求。
                result = self.fetch_lyrics(
                    http,
                    title,
                    artist,
                    album=album,
                    duration=duration,
                    timeout=lyrics_mod.DEFAULT_TIMEOUT,
                    cache=cache,
                )
            except lyrics_mod.LyricsError as exc:
                result = exc
            except Exception:
                result = lyrics_mod.LyricsError("歌词获取失败：未知原因")
            self._post(lambda: self._apply_lyrics(key, result), generation)

        try:
            self.background(work)
        except Exception:
            self._fetch_key = None
            return

    def _post(self, callback, generation: int) -> None:
        def deliver():
            if self._stopped or generation != self._generation:
                self._inflight = False
                return
            if self._flag("music_enabled", True):
                callback()
            else:
                self._inflight = False

        scheduler = getattr(self.context.ports, "scheduler", None)
        if scheduler is None:
            deliver()
            return
        try:
            scheduler.call_later(0, deliver)
        except Exception:
            # 调度器已关闭时不在 worker 上触碰 GUI，但必须放开在飞标志，
            # 否则音乐链路会永久停摆（旧实现只在成功路径复位）。
            self._inflight = False
            return

    def _apply_lyrics(self, key, result) -> None:
        if key != self._track_key:
            return
        if isinstance(result, lyrics_mod.LyricsError):
            # 失败不拉黑整首：冷却后重试，第一次失败说清原因（不再静默）。
            self._fetch_key = None
            self._lyric_retry_at = self.clock() + LYRIC_RETRY_SECONDS
            if not self._lyric_reported:
                self._lyric_reported = True
                self._say_sung(str(result), subtitle=self._subtitle(), duration_ms=5000, force=False)
            return
        self._lines = tuple(result.lines)
        self._instrumental = bool(result.instrumental)
        self._lyric_source = str(getattr(result, "source", "") or "")
        self._lyric_score = float(getattr(result, "score", 0.0) or 0.0)
        self._lyric_index = -1
        self._lyric_wait_ticks = 0
        self._fetch_attempts = 0
        if self._instrumental:
            self._release()
            if self._title:
                self._say_sung(f"正在听《{self._title}》", subtitle="")

    def _subtitle(self) -> str:
        """气泡副标题（主分支口径）：有曲名就常驻「我在唱《…》」。"""
        return f"我在唱《{self._title}》" if self._title else ""

    def _say_sung(self, text: str, *, subtitle: str, duration_ms: int = 4000, force: bool = False) -> bool:
        """带副标题的气泡；旧版 presentation 端口不接受 subtitle 时退回纯文本。"""
        presentation = self._presentation()
        if presentation is None:
            return False
        try:
            shown = presentation.say(
                text,
                duration_ms=duration_ms,
                force=force,
                subtitle=subtitle,
            )
        except TypeError:
            try:
                shown = presentation.say(text, duration_ms=duration_ms, force=force)
            except Exception:
                return False
        except Exception:
            return False
        return shown is not False

    def _position(self, track, now: float) -> float:
        """播放位置：播放器上报就用真值，否则从观察到切曲的时刻本地累加。"""
        position = getattr(track, "position", None)
        if position is not None:
            self._anchor_at = now
            self._anchor_position = float(position)
            return self._anchor_position
        return self._anchor_position + max(0.0, now - self._anchor_at)

    def _sync_lyrics(self, track, now: float) -> None:
        if not self._flag("music_lyric_enabled", True) or not self._lines:
            return
        presentation = self._presentation()
        if presentation is None:
            return
        index = lyrics_mod.line_at(
            self._lines,
            self._position(track, now),
            lead=self._lead_seconds(),
            offset=self.lyric_offset(),
        )
        if index < 0 or index == self._lyric_index:
            return
        text = self._lines[index].text.strip()
        if not text:
            return
        if self._last_bubble_at is not None and (now - self._last_bubble_at) < MIN_BUBBLE_SECONDS:
            return
        if not self._say_sung(
            text,
            subtitle=self._subtitle(),
            duration_ms=lyrics_mod.line_duration_ms(self._lines, index),
            force=False,
        ):
            # 气泡没显示出去（隐藏/设置窗打开/让路）：不推进行号，下一拍再试。
            return
        self._lyric_index = index
        self._last_bubble_at = now

    # ---------------------------------------------------------------- 命令

    def lyric_align(self) -> None:
        """把歌词偏移 +0.5 秒并在气泡里报出来（循环于 -3.0 ~ +3.0）。"""
        self._offset = next_offset(self.lyric_offset())
        self._lyric_index = -1
        self._say_forced(f"歌词偏移 {self._offset:+.1f} 秒（正数=歌词提前；本次运行有效）")

    def transport(self, action: str) -> None:
        """播放控制命令：**后台线程**调用，结果回 GUI 线程冒泡。

        菜单命令是在 GUI 线程被点的，而 SMTC 调用实测可能把主线程永久阻塞（见模块
        头）。旧实现直接在这里同步调，等于把一次点击押在 WinRT 上。
        """
        if not self._flag("music_enabled", True):
            self._say_forced("音乐控制已关闭：设置 → 扩展管理 → 音乐")
            return
        allowed = self._allowed_ids()
        kwargs = {"tracked_app_id": self._app_id}
        if allowed:
            kwargs["allowed_ids"] = allowed
        generation = self._generation

        def work() -> None:
            try:
                ok, reason = self.control_playback(action, **kwargs)
            except Exception:
                ok, reason = False, "系统媒体控制调用失败，请稍后重试。"
            finally:
                # 一次性线程：SMTC 调用会在本线程建一个常驻事件循环，退出前收掉。
                now_playing.close_thread_loop()
            self._post(
                lambda: self._report_transport(action, bool(ok), str(reason or "")),
                generation,
            )

        try:
            self.background(work)
        except Exception:
            self._report_transport(action, False, "系统媒体控制不可用")

    def _report_transport(self, action: str, ok: bool, reason: str) -> None:
        if ok:
            self._say_forced(f"已{now_playing.ACTION_LABELS.get(action, action)}")
        else:
            self._say_forced(reason or "系统媒体控制不可用")

    def open_player(self, player_key: str) -> None:
        if not self._flag("music_enabled", True):
            self._say_forced("音乐控制已关闭：设置 → 扩展管理 → 音乐")
            return
        try:
            _ok, message = self.launch_player(self._config_value("music_player_paths", {}), player_key)
        except Exception:
            message = f"启动{players.player_label(player_key)}失败"
        self._say_forced(message)

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> None:
        self._started = True
        self._stopped = False
        self._start_worker()
        scheduler = getattr(self.context.ports, "scheduler", None)
        if scheduler is None or self._timer is not None:
            return
        try:
            self._timer = scheduler.call_every(POLL_MS, self.poll)
        except Exception:
            self._timer = None

    def _start_worker(self) -> None:
        """常驻采样线程：所有系统调用只在这条线程上跑（GUI 线程一次都不碰）。"""
        worker = self._worker
        if worker is not None and worker.is_alive():
            return
        self._closing = threading.Event()
        self._wake = threading.Event()
        self._inflight = False
        worker = threading.Thread(
            target=self._worker_loop,
            args=(self._closing, self._wake, self._generation),
            name="music-smtc", daemon=True,
        )
        self._worker = worker
        worker.start()

    def stop(self) -> None:
        self._stopped = True
        self._generation += 1
        timer, self._timer = self._timer, None
        self._release()
        self._forget_track()
        scheduler = getattr(self.context.ports, "scheduler", None)
        if scheduler is not None and timer:
            try:
                scheduler.cancel(timer)
            except Exception:
                pass
        self._closing.set()
        self._wake.set()
        self._inflight = False

    def close(self) -> None:
        self.stop()

    # ---------------------------------------------------------------- 输出

    def _say_forced(self, text: str) -> None:
        presentation = self._presentation()
        if presentation is None:
            return
        try:
            presentation.say(str(text), duration_ms=4000, force=True)
        except Exception:
            return
