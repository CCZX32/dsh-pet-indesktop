"""音乐运行时：轮询 SMTC → 唱歌动画 / 歌词气泡 / 菜单命令（无 Qt）。

一秒一拍（``POLL_MS``）。**SMTC 采样只跑在常驻后台线程**（``start()`` 起
``music-smtc``）：主分支实测主线程查 SMTC 会永久阻塞窗口，所以 GUI 线程这一拍
只做「唤醒采样线程」；上一拍没回来就跳过（不排队、不堆积），采样结果经
``scheduler.call_later(0)`` 回到 GUI 线程再动动画与气泡。三件事各管一条：

1. **唱歌动画**：进入"在播"且没被纯音乐否决时 ``presentation.play_animation(
   SING_ANIM, loop=True)``；失败下一拍重试（首次 + 最多 ``SING_MAX_RETRIES``
   次），用尽后安静放弃。静音/暂停超过 ``music_sing_grace_seconds`` 才
   ``release_loop()``（短暂的歌间空隙不该让桌宠站起来又坐下）。
2. **歌词**：每首曲子最多取一次词（后台线程 + ``HttpPort``，失败不重试），之后
   按播放位置推进；每句最多一个气泡、且两句之间至少 ``MIN_BUBBLE_SECONDS``。
   ``music_lyric_lead_seconds`` 是提前量，菜单「歌词对齐」调的是本次运行的偏移。
   播放器不上报进度时用本地时钟累加，暂停期间时钟冻结。
3. **命令**：传输控制（``pause/next/prev/stop``）与打开播放器。SMTC 不可用时
   每条命令都**说清原因**（没有会话 / 播放器不支持 / 缺组件），不静默失败。

配置一律经 ``HostPorts.config`` **只读**读取（运行时不许持有/改写配置对象）；
歌词偏移是本次运行的会话状态，初始值来自 ``music_lyric_offset_seconds``。
"""

from __future__ import annotations

import threading
import time

from . import lyrics as lyrics_mod
from . import now_playing, players

#: 播放时让桌宠哼歌的动画名（角色包里 ``random/悠闲哼歌``）。
SING_ANIM = "悠闲哼歌"
#: 轮询间隔：与歌词/唱歌链路的既有口径一致，兼顾开销与切歌响应。
POLL_MS = 1000
#: ``play_animation`` 失败后的重试次数（下一拍再试），用尽后安静放弃。
SING_MAX_RETRIES = 3
#: ``play_animation`` 的总尝试次数：首次 + ``SING_MAX_RETRIES`` 次重试。
SING_MAX_ATTEMPTS = 1 + SING_MAX_RETRIES
#: 两句歌词气泡之间的最小间隔（秒）。
MIN_BUBBLE_SECONDS = 2.0
#: 「歌词对齐」每次的步长与循环区间（秒）。
OFFSET_STEP = 0.5
OFFSET_MIN = -3.0
OFFSET_MAX = 3.0

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
}


def next_offset(current: float) -> float:
    """「歌词对齐」的下一档：+0.5 秒，超过上界回到下界。"""
    value = round(float(current) + OFFSET_STEP, 1)
    if value > OFFSET_MAX + 1e-6:
        return OFFSET_MIN
    return value


def _spawn_thread(work) -> None:
    threading.Thread(target=work, name="music-runtime", daemon=True).start()


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
        self.read_playback = now_playing.read_playback
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
        self._pending: tuple[bool, str] = (False, "")
        self._inflight = False
        self._app_id = ""
        self._title = ""
        self._track_key: tuple[str, str] | None = None
        self._lines: tuple[lyrics_mod.LyricLine, ...] = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key: tuple[str, str] | None = None
        self._anchor_at: float = 0.0
        self._anchor_position = 0.0
        self._paused_at: float | None = None
        self._last_bubble_at: float | None = None
        self._sing_active = False
        self._sing_attempts = 0
        self._silent_since: float | None = None
        self._offset: float | None = None

    # ---------------------------------------------------------------- 配置

    @property
    def instrumental(self) -> bool:
        """当前曲目是否已被判定为纯音乐（纯音乐不唱、不显示歌词）。"""
        return self._instrumental

    @property
    def singing(self) -> bool:
        """唱歌动画当前是否由本运行时持着（``release_loop`` 尚未发出）。"""
        return self._sing_active

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

    def _lead_seconds(self) -> float:
        return self._number("music_lyric_lead_seconds", DEFAULTS["music_lyric_lead_seconds"], low=-2.0, high=3.0)

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
        """一拍：把 SMTC 采样交给后台线程，回来后再动动画/歌词。

        SMTC 查询实测可能在主线程永久阻塞（主分支的现场结论），所以这里**不在
        GUI 线程读**：有采样线程时只唤醒它，结果经 ``scheduler.call_later(0)``
        回到 GUI 线程再处理。上一拍还没回来就跳过这一拍（不排队、不堆积）。
        """
        if self._stopped:
            return
        if not self._flag("music_enabled", True):
            self._release()
            self._forget_track()
            return
        browser = self._flag("music_browser_media_enabled", False)
        tracked = self._app_id or self._preferred_app_id()
        allowed = self._allowed_ids()
        if self._started:
            self._start_worker()
            if self._closing.is_set():
                return
        worker = self._worker
        if worker is not None and worker.is_alive():
            if self._inflight:
                return
            self._inflight = True
            self._pending = (browser, tracked, allowed)
            self._wake.set()
            return
        self._on_playback(self._read(browser, tracked, allowed))

    def _on_playback(self, playback) -> None:
        self._inflight = False
        now = self.clock()
        if playback is None:
            self._on_silence(now)
            self._forget_track()
            return
        self._app_id = playback.app_id or self._app_id
        if not playback.playing:
            # 暂停不等于换曲：保留已取到的歌词，停在当前这句。
            if self._paused_at is None:
                self._paused_at = now
            self._on_silence(now)
            return
        self._silent_since = None
        if self._paused_at is not None:
            # 本地时钟模式下暂停过：把基准顺延，恢复后歌词不跳句。
            self._anchor_at += max(0.0, now - self._paused_at)
            self._paused_at = None
        if playback.key() != self._track_key:
            self._begin_track(playback, now)
        self._sync_singing()
        # 歌词在曲中才打开开关时补一次取词（每曲仍只取一次）。
        if not self._lines and not self._instrumental and self._fetch_key != self._track_key:
            self._start_fetch(playback)
        self._sync_lyrics(playback, now)

    def _read(
        self,
        browser_media_enabled: bool,
        tracked_app_id: str,
        allowed_ids: frozenset[str] | None = None,
    ):
        kwargs = {
            "browser_media_enabled": bool(browser_media_enabled),
            "tracked_app_id": str(tracked_app_id or ""),
        }
        if allowed_ids:
            kwargs["allowed_ids"] = allowed_ids
        try:
            return self.read_playback(**kwargs)
        except Exception:
            return None

    def _preferred_app_id(self) -> str:
        """配置里的默认播放器：多会话同播时优先跟随它。"""
        key = str(self._config_value("music_player", "") or "").strip()
        return players.player_exe(key) if key else ""

    def _on_silence(self, now: float) -> None:
        if not self._sing_active:
            return
        if self._silent_since is None:
            self._silent_since = now
        if now - self._silent_since >= self._grace_seconds():
            self._release()

    def _forget_track(self) -> None:
        self._track_key = None
        self._lines = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key = None
        self._anchor_at = 0.0
        self._anchor_position = 0.0
        self._paused_at = None

    def _begin_track(self, playback: now_playing.Playback, now: float) -> None:
        self._track_key = playback.key()
        self._title = str(playback.title or "")
        self._lines = ()
        self._instrumental = False
        self._lyric_index = -1
        self._fetch_key = None
        self._anchor_at = now
        self._anchor_position = float(playback.position or 0.0)
        self._paused_at = None
        self._last_bubble_at = None
        self._start_fetch(playback)

    # ---------------------------------------------------------------- 唱歌

    def _sync_singing(self) -> None:
        if not self._flag("music_sing_enabled", True) or self._instrumental:
            if self._sing_active:
                self._release()
            return
        if self._sing_active or self._sing_attempts >= SING_MAX_ATTEMPTS:
            return
        presentation = self._presentation()
        if presentation is None:
            return
        self._sing_attempts += 1
        try:
            started = bool(presentation.play_animation(SING_ANIM, loop=True))
        except Exception:
            started = False
        if started:
            self._sing_active = True
            self._sing_attempts = 0

    def _release(self) -> None:
        self._silent_since = None
        self._sing_attempts = 0
        if not self._sing_active:
            return
        self._sing_active = False
        presentation = self._presentation()
        if presentation is None:
            return
        try:
            presentation.release_loop()
        except Exception:
            return

    # ---------------------------------------------------------------- 歌词

    def _start_fetch(self, playback: now_playing.Playback) -> None:
        if not self._flag("music_lyric_enabled", True):
            return
        key = self._track_key
        if key is None or self._fetch_key == key:
            return
        http = getattr(self.context.ports, "http", None)
        if http is None:
            return
        cache = self._cache()
        self._fetch_key = key
        title, artist = playback.title, playback.artist
        generation = self._generation

        def work() -> None:
            try:
                result = self.fetch_lyrics(http, title, artist, timeout=lyrics_mod.DEFAULT_TIMEOUT, cache=cache)
            except lyrics_mod.LyricsError as exc:
                result = exc
            except Exception:
                result = lyrics_mod.LyricsError("歌词获取失败：未知原因")
            self._post(lambda: self._apply_lyrics(key, result), generation)

        try:
            self.background(work)
        except Exception:
            return

    def _post(self, callback, generation: int) -> None:
        def deliver():
            if not self._stopped and generation == self._generation:
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
            # 调度器已关闭时不在 worker 上触碰 GUI。
            return

    def _apply_lyrics(self, key, result) -> None:
        if key != self._track_key:
            return
        if isinstance(result, lyrics_mod.LyricsError):
            return
        self._lines = tuple(result.lines)
        self._instrumental = bool(result.instrumental)
        self._lyric_index = -1
        if self._instrumental and self._sing_active:
            self._release()
        if self._instrumental and self._title:
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
            presentation.say(
                text,
                duration_ms=duration_ms,
                force=force,
                subtitle=subtitle,
            )
        except TypeError:
            try:
                presentation.say(text, duration_ms=duration_ms, force=force)
            except Exception:
                return False
        except Exception:
            return False
        return True

    def _position(self, playback: now_playing.Playback, now: float) -> float:
        """播放位置：播放器上报就用真值，否则从观察到切曲的时刻本地累加。"""
        if playback.position is not None:
            self._anchor_at = now
            self._anchor_position = float(playback.position)
            return self._anchor_position
        return self._anchor_position + max(0.0, now - self._anchor_at)

    def _sync_lyrics(self, playback: now_playing.Playback, now: float) -> None:
        if not self._flag("music_lyric_enabled", True) or not self._lines:
            return
        presentation = self._presentation()
        if presentation is None:
            return
        index = lyrics_mod.line_at(
            self._lines,
            self._position(playback, now),
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
        self._lyric_index = index
        if not self._say_sung(
            text,
            subtitle=self._subtitle(),
            duration_ms=lyrics_mod.line_duration_ms(self._lines, index),
            force=False,
        ):
            return
        self._last_bubble_at = now

    # ---------------------------------------------------------------- 命令

    def lyric_align(self) -> None:
        """把歌词偏移 +0.5 秒并在气泡里报出来（循环于 -3.0 ~ +3.0）。"""
        self._offset = next_offset(self.lyric_offset())
        self._lyric_index = -1
        self._say_forced(f"歌词偏移 {self._offset:+.1f} 秒（正数=歌词提前；本次运行有效）")

    def transport(self, action: str) -> None:
        if not self._flag("music_enabled", True):
            self._say_forced("音乐控制已关闭：设置 → 扩展管理 → 音乐")
            return
        allowed = self._allowed_ids()
        kwargs = {"tracked_app_id": self._app_id}
        if allowed:
            kwargs["allowed_ids"] = allowed
        try:
            ok, reason = self.control_playback(action, **kwargs)
        except Exception:
            ok, reason = False, "系统媒体控制调用失败，请稍后重试。"
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
        """常驻采样线程：SMTC 查询只在这条线程上跑（GUI 线程一次都不碰）。"""
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

    def _worker_loop(self, closing, wake, generation: int) -> None:
        try:
            while not closing.is_set():
                if not wake.wait(1.0):
                    continue
                wake.clear()
                if closing.is_set():
                    break
                browser, tracked, allowed = self._pending
                playback = self._read(browser, tracked, allowed)
                self._post(lambda sample=playback: self._on_playback(sample), generation)
        finally:
            # 线程退出时关掉本线程的常驻事件循环，别把未关闭的 loop 留给 GC。
            now_playing.close_thread_loop()

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

    def _presentation(self):
        return getattr(self.context.ports, "presentation", None)

    def _say_forced(self, text: str) -> None:
        presentation = self._presentation()
        if presentation is None:
            return
        try:
            presentation.say(str(text), duration_ms=4000, force=True)
        except Exception:
            return
