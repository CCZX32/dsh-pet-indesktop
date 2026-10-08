# -*- coding: utf-8 -*-
"""语音报时：调度服务 + edge-tts 合成 + QtMultimedia 播放（GUI 线程）。

架构（参考 pet/todo_reminder.py 与 pet/click_sound.py）：
- 模块顶层不 import Qt：QObject / QTimer / QtMultimedia 均在方法内惰性导入，
  保证纯逻辑层（voice_chime.py）可在无 Qt 环境测试；
- VoiceChimeService 不继承 QObject，持有无主 QTimer，由 AppShell 持有引用
  保证生命周期（同 TodoReminderService）；
- 报时调度 tick（20s）→ voice_chime.is_chime_minute 判定 + 槽位盖戳幂等；
- 文本双轨：语音用中文口播文本（build_chime_sentence，同时作为合成输入与
  缓存键），气泡用阿拉伯数字文本（build_bubble_sentence），两者解耦；
- 合成在后台线程跑 edge_tts（asyncio），完成后经 QObject 信号（queued）
  桥回 GUI 线程，用 QMediaPlayer + QAudioOutput 播放；
- edge_tts **懒加载**：模块顶层只做 find_spec 探测（不 import 本体），真正的
  import 推迟到 _TTSWorker 的合成线程里第一次合成时——edge_tts 首次 import
  实测 ~1.4s 且常驻内存，而语音报时默认关闭、服务可能整个不 start，顶层 import
  等于让每个用户白付这笔钱；
- 音频缓存于 config.dir/voice_chime_cache，按“文本+音色+语速+音调”哈希
  去重，同句不重复合成；
- 预合成降延迟：距下一报时点 ≤ 60s 时提前在后台线程合成该次报时音频并
  写缓存，到点直接播缓存实现近零延迟；预合成未及时完成则回退即时合成。
- 免打扰（含全屏等效）期间不出声：报时语音与节日语音在**合成入口**
  （``_fire``）、**回放出口**（``_handle_synthesized``）与 **``speak()`` 的
  排队入口**（免打扰期间不入队，不留到免打扰结束后补播）过同一道闸
  （``_quiet_muted``，判据仍是 ``quiet_mode``），预合成一并跳过（省一次
  TTS 网络请求），被丢弃的只有声音——气泡语义不变（照旧进暂存队列）；
  点击自言自语属交互应答（issue #208），在调用侧显式豁免（豁免随队携带）。
- **通道真空闲 = 无合成在飞（``_busy`` False）∧ 播放器未接管
  （``_player_engaged``）**——本模块唯一的占用判据（``_channel_idle``）。两个补播
  队列（``_queued_fire`` 到点报时、``_pending_speech`` 外部播报）共用它：不空闲就
  **原样留队**，等下一拍（合成完成 / EndOfMedia 终止 / 合成超时自愈）再来。凡是
  **合成完成却没起播**的结局（预合成、免打扰丢弃、合成失败、已停止）都没有
  EndOfMedia 媒体终止事件，正是靠这三拍里的另外两拍兜住：豁免的那条照常出声，
  尊重免打扰的那条被 ``_fire`` 的闸现读再丢一次。
- **代次作废旧合成**：回调协议（path/text/error）没有任务身份，故每次起合成与
  watchdog 释放时递增 ``_synthesis_generation``，worker 回调由闭包带回动身时的
  代次（信号首参）。代次不符 = 超时自愈已把这次合成作废，``_on_synthesized``
  整条丢弃、一个字段都不碰——否则旧任务的回调会取走**新任务**的 role / 免打扰
  口径 / busy 锁，让该静音的旧语音出声、应豁免的新语音被静音。
- **播放时刻重判接管**：合成期间别的音频可以合法起播（报时走缓存例外，不看占用），
  所以 ``_handle_synthesized`` 的两个播放出口在**动手播放那一刻**再判一次
  ``_player_engaged()``：被接管就不 ``setSource``，改为回队（报时回 ``_queued_fire``、
  外部播报回 ``_pending_speech``），等下一拍按上面的不变量出队。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .voice_chime import (
    DEFAULT_VOICE,
    VOICE_OPTIONS,
    build_bubble_sentence,
    build_chime_sentence,
    cache_key,
    chime_slot,
    clean_voice,
    edge_pitch_arg,
    edge_rate_arg,
    next_chime_in_seconds,
    normalize_chime_config,
    voice_label,
)

logger = logging.getLogger(__name__)

# 缓存清理最小间隔（秒）：报时/试听/设置保存都会触发 apply_config，而缓存目录
# 全量 glob+stat 属纯 IO 开销；节流到 5 分钟一次即可满足 200 文件上限的收敛。
_PRUNE_MIN_INTERVAL_S = 300.0
# 合成回调超时（秒）：worker 线程若异常未回调，_busy 会永久置位导致报时静默，
# 超过该时限在调度 tick 中复位（正常合成 3-8s 完成，45s 余量充足）。
_SYNTH_TIMEOUT_S = 45.0

# 合成线程里 edge_tts 导入失败时的回调错误码：GUI 侧据此走 _notify_missing_tts
# 降级（"请 pip install edge-tts"），而不是笼统的"合成失败"。
EDGE_TTS_MISSING = "edge-tts-missing"


def _edge_tts_available() -> bool:
    """**不 import 本体**地探测 edge-tts 是否可用（惰性探测）。

    ``importlib.util.find_spec`` 只问 import 系统找不找得到包，不执行模块代码，
    因此不付 edge_tts 的 ~1.4s 导入成本、也不占常驻内存。真正的 import 推迟到
    :class:`_TTSWorker` 的合成线程里第一次合成时；万一探测通过而 import 失败
    （半装/被禁用），worker 会在回调里带回错误码 :data:`EDGE_TTS_MISSING`，走
    同一套降级文案。
    """
    try:
        return importlib.util.find_spec("edge_tts") is not None
    except (ImportError, ValueError):
        # 父包缺失 / sys.modules 里被置 None 等异常形态：一律按不可用处理。
        return False


# 惰性探测结果（模块顶层，但不 import 本体）。测试可 monkeypatch 本标志。
_EDGE_TTS_AVAILABLE = _edge_tts_available()

# 合成失败的重试与间隔：微软这个接口在**连发**时会偶发返回空音频（实机：同一批
# en-US 音色间隔 6 秒逐个重试全部成功，连发则整批 NoAudioReceived）。
EDGE_RETRY_TIMES = 2
EDGE_RETRY_DELAY_S = 1.5
# 在线音色表缓存时长：厂家会下架音色，配置里存的是「当时有效」的值
VOICE_LIST_TTL_S = 6 * 3600

#: 同一条音色替换提示每个进程只弹一次（避免每次报时都刷屏）
_VOICE_SUBSTITUTION_NOTICES: set[str] = set()

_live_voices: frozenset[str] | None = None
_live_voices_at = 0.0
_voice_lock = threading.Lock()


def _bundled_voices() -> frozenset[str]:
    """内置（随包发布）音色集合——拿不到在线表时的校验集。"""
    return frozenset(value for value, _label in VOICE_OPTIONS)


def known_voices() -> frozenset[str]:
    """当前可用于校验的音色集合：有在线缓存就用在线表，否则退回内置清单。**不联网。**"""
    with _voice_lock:
        return _live_voices if _live_voices else _bundled_voices()


def refresh_voice_list(*, force: bool = False, timeout: float = 10.0) -> frozenset[str] | None:
    """拉一次微软在线音色表并缓存（**会联网**，只该在后台合成线程里调）。

    失败/超时返回 ``None`` 并保留旧缓存——联网失败不该让报时跟着失败。
    """
    global _live_voices, _live_voices_at
    now = time.time()
    with _voice_lock:
        if not force and _live_voices and now - _live_voices_at < VOICE_LIST_TTL_S:
            return _live_voices
    try:
        import edge_tts

        raw = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=timeout))
        voices = frozenset(str(item.get("ShortName") or "") for item in raw if item)
    except Exception as exc:  # noqa: BLE001 —— 拉不到不是错误，用旧的就够
        logger.debug("拉取在线音色表失败（沿用内置/旧表）：%s", exc)
        return None
    voices = frozenset(name for name in voices if name)
    if not voices:
        return None
    with _voice_lock:
        _live_voices = voices
        _live_voices_at = now
    return voices


def resolve_voice(configured) -> tuple[str, str]:
    """把配置音色解析成「这次真要用哪把嗓子」，必要时换成默认音色并给出说明。

    厂家会下架音色，而用户配置里存的是当时有效的值：配上已下架的音色时接口返回的
    是空音频（``NoAudioReceived``），用户只会觉得「声音没了」。这里**不联网**——
    用在线表缓存（没有就用内置清单）判定，联网刷新在后台合成线程里做。
    """
    voice = clean_voice(configured)
    if not _EDGE_TTS_AVAILABLE or voice in known_voices():
        return voice, ""
    note = (
        f"音色「{voice_label(voice)}」已不在微软在线音色表里（多半被下架了），"
        f"本次改用默认音色「{voice_label(DEFAULT_VOICE)}」；"
        "可在 设置 → 语音 → 语音报时 → 音色 里换一个可用的。"
    )
    return DEFAULT_VOICE, note


def _cache_hit(path: Path) -> bool:
    """缓存命中判定：文件存在**且非空**。

    只判 ``exists()`` 不够——失败的合成会留下 0 字节/半截文件（``edge_tts.save``
    先建文件再写），那会被当成「已有缓存」，于是播出一声静音且不再重新合成
    （实机在缓存目录里抓到过一串 0 字节 mp3）。
    """
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


class _TTSWorker(threading.Thread):
    """后台线程：edge-tts 合成 mp3 后经回调返回。

    线程不直接碰 Qt 对象；完成后把结果交给 owner 提供的回调（owner 在
    GUI 线程，回调触发 queued 信号桥接）。
    """

    def __init__(self, text: str, voice: str, rate: str, pitch: str, out_path: Path, on_done) -> None:
        super().__init__(daemon=True)
        self._text = text
        self._voice = voice
        self._rate = rate
        self._pitch = pitch
        self._out_path = out_path
        self._on_done = on_done

    def run(self) -> None:  # noqa: D102
        # 在线音色表顺手刷新（有网就更新缓存，失败无所谓）——只在这个后台线程里联网
        refresh_voice_list()
        # 主音色反复失败（下架 / 限流 / 参数被拒）时退到默认音色再试一轮
        candidates = [self._voice]
        if self._voice != DEFAULT_VOICE:
            candidates.append(DEFAULT_VOICE)
        errors: list[str] = []
        for candidate in candidates:
            for attempt in range(1, EDGE_RETRY_TIMES + 1):
                try:
                    asyncio.run(self._synthesize(candidate))
                except ImportError:
                    # edge_tts 本该在 _synthesize 里惰性导入（见 _edge_tts_available）：
                    # 探测通过但真导入失败（半装 / 被禁用）时也走这里，回 GUI 侧同一套
                    # "请 pip install edge-tts" 降级，而不是笼统的合成失败。
                    logger.warning("edge-tts 不可导入，降级为仅气泡提示")
                    self._on_done(str(self._out_path), self._text, EDGE_TTS_MISSING)
                    return
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{candidate} 第{attempt}次: {type(exc).__name__}: {exc}")
                    logger.warning("edge-tts 合成失败（%s 第%d次）：%s", candidate, attempt, exc)
                    self._discard_partial()
                    if attempt < EDGE_RETRY_TIMES and candidate != candidates[-1]:
                        time.sleep(EDGE_RETRY_DELAY_S)
                    continue
                if self._out_path.exists() and self._out_path.stat().st_size > 0:
                    if candidate != self._voice:
                        logger.warning(
                            "音色 %s 合成失败，已改用默认音色 %s", self._voice, candidate
                        )
                    self._on_done(str(self._out_path), self._text, "")
                    return
                # 服务端「成功」但没给音频（0 字节）：也算失败，别留下空缓存
                errors.append(f"{candidate} 第{attempt}次: 服务端未返回音频（空文件）")
                self._discard_partial()
        self._on_done(
            str(self._out_path), self._text, "edge-tts 合成失败 → " + "；".join(errors[-4:])
        )

    def _discard_partial(self) -> None:
        """删掉失败留下的半截产物：留在缓存目录会被下一次当成「已有缓存」。"""
        try:
            self._out_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("清理半截合成产物失败：%s", self._out_path)

    async def _synthesize(self, voice: str) -> None:
        # 惰性导入：只在真的要合成的后台线程里付这笔 import 成本。
        import edge_tts

        communicate = edge_tts.Communicate(
            self._text,
            voice,
            rate=self._rate,
            pitch=self._pitch,
        )
        await communicate.save(str(self._out_path))


class _AudioBridge:
    """QObject 信号桥：后台线程合成完成 → queued 信号回 GUI 线程。

    _Signals 实例本身即 QObject，随服务存活到进程退出；历史遗留的无主
    QObject（_obj）与其 destroy() 从未被调用，删除以免误导生命周期判断。

    信号对象在 GUI 线程创建（_fire 由 GUI 线程调用），PySide6 依其线程亲和
    把跨线程 emit 排到 GUI 线程执行——已在实机测过：后台 emit、槽在 GUI
    线程运行（不要把这里改成普通 Python 回调绕开信号）。
    """

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Signals(QObject):
            # generation 在首位：合成的任务身份，迟到回调靠它作废（见 _on_synthesized）。
            synthesized = Signal(int, str, str, str)  # generation, path, text, error

        self.signals = _Signals()

    def callback_for(self, generation: int):
        """给**这一次**合成做回调载体：闭包捕获动身时的代次。

        返回的是 worker 认识的三参回调 ``(path, text, error)``——代次不进 worker
        协议，而是由闭包在 emit 时补进信号的首参，从而跨线程带到 GUI 线程的槽里
        （跨线程只有 queued 信号这一条路，代次必须随信号走，不能事后查表）。
        """
        def done(path: str, text: str, error: str) -> None:
            # 从后台线程调用：Qt 自动 queued 到 GUI 线程
            self.signals.synthesized.emit(generation, path, text, error)

        return done


class VoiceChimeService:
    """语音报时服务（AppShell 持有，GUI 线程）。

    配置键（config.py 平铺顶层键）：
      voice_chime_enabled / voice_chime_schedule / voice_chime_custom_times /
      voice_chime_voice / voice_chime_rate / voice_chime_pitch / voice_chime_volume /
      voice_chime_show_bubble / voice_chime_show_quote
    """

    TICK_INTERVAL_MS = 20_000
    BUBBLE_DURATION_MS = 8000
    MAX_CACHE_FILES = 200
    # 预合成窗口：距下一报时点 ≤ 60s 时提前在后台合成并写缓存，到点直接播。
    PRECACHE_WINDOW_S = 60

    def __init__(self, app) -> None:
        from PySide6.QtCore import QTimer

        self._app = app
        config = getattr(app, "config", None)
        self._cache_dir = Path(getattr(config, "dir", Path("."))) / "voice_chime_cache"
        # 契约形状（enabled/schedule/custom_times/voice/rate/pitch/volume）：
        # 与 _on_tick/_fire 读取的键一致，勿用带 voice_chime_ 前缀的镜像默认值。
        self._cfg: dict = normalize_chime_config(None)
        self._last_slot: str | None = None
        self._busy = False
        # monotonic 时间戳：_busy_since 用于合成卡死自愈，_last_prune_at 用于
        # 缓存清理节流（两者都只做"多久没做过了"的判断，不参与业务语义）。
        self._busy_since = 0.0
        self._last_prune_at = 0.0
        self._synthesis_role = "play"  # play | precache：区分合成完成回调的用途
        # 本次合成是否尊重免打扰（True = 免打扰期间丢弃结果）。与 _synthesis_role
        # 同生命周期：合成开始时置位、回调里消费后复位为默认值。
        self._synthesis_respect_quiet = True
        # 本次合成的时间戳：只在"播放时刻通道被接管、报时项回队"时原样带回
        # _queued_fire（气泡文本随队携带，该字段本身对播放无影响）。同生命周期。
        self._synthesis_now: datetime | None = None
        # 合成**代次**：每次起合成与 watchdog 释放时递增，worker 回调由闭包带回
        # 动身时的代次——回调协议只有 path/text/error，没有任务身份，代次就是身份。
        # 迟到的旧任务回调据此整条丢弃（见 _on_synthesized），不再串到新任务上。
        self._synthesis_generation = 0
        # 预合成状态：目标槽位 / 语音文本 / 气泡文本 / 缓存文件（到点命中即零延迟播放）
        self._precache_slot: str | None = None
        self._precache_text: str | None = None
        self._precache_bubble: str | None = None
        self._precache_path: str | None = None
        # 即时合成中的气泡文本：合成完成回调里与语音文本配对展示（二者解耦）
        self._pending_bubble: str | None = None
        # 停止作废标记：stop()（关闭开关/退出）后，飞行中的合成结果不再回放
        self._stopped = False
        # 外部播报（节日提醒）经 speak() 复用本服务的音频通道：通道忙时进深度 1
        # 待播队列，当前一段播完再播——不打断、不叠音。None 表示无待播。
        self._pending_speech: str | None = None
        # 排队的那一条是否尊重免打扰（False = 交互应答，出队时即便在免打扰也照常
        # 出声）。与 _pending_speech 同生命周期：入队时随文本一起置位，出队消费后
        # 复位为默认值 True。
        self._pending_respect_quiet = True
        # 媒体终止态枚举；_ensure_player 成功时填充，未创建播放器时为空元组。
        self._terminal_statuses: tuple = ()
        # 让位钩子：由 AppShell 注入 Callable[[str], bool]，入参是本分钟的报时槽位，
        # 返回 True 表示该槽位让位给节日提醒（报时本分钟不说）。None = 无人让位。
        # 用注入而不是让报时反查节日服务，是为了保持本模块对外零依赖。
        self.yield_slot = None
        self._bridge: _AudioBridge | None = None
        self._player = None
        self._audio_out = None
        # 合成在飞时被 busy 门拦下的待补播报（_fire 排队，_on_synthesized 补播）
        self._queued_fire: tuple | None = None
        self._timer = QTimer()
        self._timer.setInterval(self.TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        self.apply_config()
        self._on_tick()
        self._timer.start()

    def stop(self) -> None:
        """停止调度；正在播放的音频一并停住，飞行中的合成结果作废（见 _on_synthesized）。"""
        self._stopped = True
        # 正在出声的这一段必须立刻停：关掉开关/退出后继续放完，用户听到的就是
        # "关不掉"；退出路径上播放器还可能正被析构。
        player = self._player
        if player is not None:
            try:
                player.stop()
            except Exception:
                logger.debug("停止语音播放失败（播放器可能已析构）", exc_info=True)
        # 待播队列同样作废：关掉开关/退出后不该再补播一条排队的语音。
        self._pending_speech = None
        self._queued_fire = None
        self._timer.stop()

    def is_running(self) -> bool:
        """调度 tick 是否在跑（AppShell 的懒启停门控据此决定重启还是只刷配置）。"""
        return bool(self._timer.isActive())

    def apply_config(self) -> None:
        """重读配置（设置保存、右键开关后调用）。

        统一走纯逻辑层 normalize_chime_config：清洗/钳制规则只有一处实现，
        且 config.json 被手改成非法值时回落默认值而不是抛异常（本方法在
        start()（开机）与「立即报时」路径上执行，抛异常等于语音报时在启动期
        直接失败）。
        """
        config = getattr(self._app, "config", None)
        self._cfg = normalize_chime_config(config if config is not None else {})
        # 配置变更后预合成缓存可能失效（音色/语速/台词开关/时间点变化），丢弃。
        self._precache_slot = None
        self._precache_text = None
        self._precache_bubble = None
        self._precache_path = None
        self._prune_cache()

    # ------------------------------------------------------------ 对外入口
    def say_now(self, text: str = "") -> None:
        """手动报时（右键菜单「立即报时」/ 设置页试听共用）。

        text 留空时按当前时间组装“报时文本 + 台词/歌词”（台词每天整套换新、日内
        按序取用）；气泡用阿拉伯数字文本、语音保持中文数字口播，二者解耦。手动触发
        不占用调度槽位（与自动报时允许同分钟并存，由用户主动发起）。
        """
        self.apply_config()
        now = datetime.now()
        stripped = text.strip()
        if stripped:
            self._fire(stripped, now, stripped)
            return
        self._fire(build_chime_sentence(now, self._cfg), now, build_bubble_sentence(now, self._cfg))

    def speak(self, text: str, *, log_tag: str = "外部播报", respect_quiet: bool = True) -> bool:
        """向本服务（进程内唯一的音频通道）提交一段**纯语音**播报，不含气泡。

        供节日提醒等功能复用：合成、缓存、播放与报时**共用同一套**，因此结构上
        不可能与报时叠音。通道不空闲（合成中、正在出声，或刚起播而媒体仍在加载）
        时不打断，进深度 1 的待播队列，当前一段播完后自动播；队列已有待播时后来的
        覆盖前面的（只留最新一条，避免堆积出已过期的内容）。

        排队同样受免打扰契约约束，且契约**随队携带**：尊重免打扰的那条（默认）
        在入队时就过闸——免打扰期间**丢弃、不入队**（与 ``_fire`` 同语义，不留到
        免打扰结束后补播一条过期提醒）；显式豁免的那条（交互应答）把
        ``respect_quiet`` 一起存进队列，出队时用它去过 ``_fire`` 的闸——入队时没开
        免打扰、出队前才开的，出队那一拍仍会被闸丢弃（免打扰状态是现读的，不是
        入队快照）。

        气泡刻意不在这里做：节日提醒有自己的一套气泡（含 show_quote 开关与更长
        的展示时长），若再走报时的 ``_bubble`` 会被 ``voice_chime_show_bubble``
        二次影响，也会出现"两个气泡"。

        ``respect_quiet`` 默认 True = 免打扰（含全屏等效）期间丢弃这段语音（判据
        见 ``_quiet_muted``）。提醒类播报（节日提醒）用默认值；**交互应答**（点击
        自言自语）显式传 False——它回应用户刚做的动作，与 issue #208 里"点击台词
        照常冒"同口径。默认取 True 是刻意的：新调用方漏传时是"免打扰期间不出声"，
        而不是"免打扰期间突然响一声"。

        返回 False 仅表示文本为空；edge-tts 不可用时只记日志、不出声（调用方的
        气泡照常）。
        """
        stripped = (text or "").strip()
        if not stripped:
            return False
        # 唯一占用判据（通道真空闲 = 无合成在飞 ∧ 播放器未接管）：不空闲就排队。
        if not self._channel_idle():
            if respect_quiet and self._quiet_muted():
                # 入队即丢弃（与 _fire 的「丢弃不补播」同语义）：排队的节日语音在
                # 免打扰结束后出队补播，等于把一条过期提醒翻出来。
                logger.debug("免打扰期间静音，丢弃本次排队语音：%s", stripped[:20])
                return True
            self._pending_speech = stripped
            self._pending_respect_quiet = respect_quiet
            logger.info("%s：音频通道忙，已排队待播", log_tag)
            return True
        self._fire(stripped, datetime.now(), None, show_bubble=False, role="speak",
                   respect_quiet=respect_quiet)
        return True

    def play_file(self, path: str, *, log_tag: str = "本地语音") -> bool:
        """直接播放一个**本地音频文件**（预缓存台词走这条路：零延迟、不联网）。

        与 ``speak()`` 共用同一个播放器（进程内唯一音频通道），所以同样不会与
        报时叠音。区别是刻意**不排队**：预缓存的是点击台词，点击那一刻已经过去
        了，晚几秒才冒出来反而突兀——通道忙就直接放弃这次出声（返回 False），
        由调用方决定是否回退到在线合成。

        **不走免打扰静音闸**：本入口只有点击自言自语在用（交互应答，同
        ``speak(respect_quiet=False)``），见 :meth:`speak` 的说明。
        """
        target = Path(path)
        if not target.is_file():
            return False
        # 唯一占用判据（同 speak 的入口门）：刚起播也算被占，否则会顶掉那一段。
        if not self._channel_idle():
            logger.info("%s：音频通道忙，本次本地播报跳过：%s", log_tag, target.name)
            return False
        return self._play_only(str(target))

    # ------------------------------------------------------------ 调度
    def _on_tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        # 兜底自愈：合成线程若异常未回调，_busy 会永久置位（后续语音只能不断入队、
        # 通道再也不出声）。tick 是 20s 周期的常驻入口，超时即复位。
        # **必须在 enabled 判定之前**：报时开关关掉、只剩节日提醒 / 点击自言时
        # 本服务照样在跑同一个通道（AppShell 的懒创建门控），那时 watchdog 若被
        # enabled 短路掉，唯一的自愈入口就永远执行不到，通道永不恢复。
        self._release_stale_busy()
        if not self._cfg.get("enabled"):
            return
        slot = chime_slot(now, self._cfg)
        if slot:
            if slot == self._last_slot:
                return
            # 让位检查必须在盖戳之前，且让位同样要消费该槽位——否则本分钟后续
            # tick（20s 一次）会反复询问，并在让位条件变化时补报，产生意外发声。
            # 用 getattr 取钩子：部分构造的服务对象（测试替身走 object.__new__）
            # 没有该属性，不该因此让 tick 抛异常。
            yield_slot = getattr(self, "yield_slot", None)
            if callable(yield_slot) and yield_slot(slot):
                self._last_slot = slot
                logger.info("报时让位给节日提醒：%s", slot)
                return
            self._last_slot = slot
            precache_bubble = self._precache_bubble  # 消费前取用（consume 会清空预合成状态）
            sentence = self._consume_precache(slot)
            bubble = precache_bubble if sentence is not None else None
            self._precache_bubble = None
            if sentence is None:
                sentence = build_chime_sentence(now, self._cfg)
                bubble = build_bubble_sentence(now, self._cfg)
            self._fire(sentence, now, bubble)
            return
        # 未命中：尝试为下一报时点预合成（距下一报时点 ≤ 窗口秒数）。
        self._maybe_precache(now)

    def _maybe_precache(self, now: datetime) -> None:
        """距下一报时点 ≤ 60s 时，提前在后台合成该次报时音频并写缓存。"""
        # 过期清理：预合成目标槽位已过（如配置变更/服务长时间暂停后恢复）。
        if self._precache_slot is not None:
            slot_time = self._precache_slot[:16]  # YYYY-MM-DDTHH:MM
            if now.strftime("%Y-%m-%dT%H:%M") > slot_time:
                self._precache_slot = None
                self._precache_text = None
                self._precache_bubble = None
                self._precache_path = None
        # 免打扰期间不预合成：这次报时到点会被静音闸丢掉，合成等于白跑一趟
        # 网络请求（退出免打扰后又回到即时合成的既有回退路径）。
        if self._quiet_muted():
            return
        next_secs = next_chime_in_seconds(now, self._cfg)
        if next_secs > self.PRECACHE_WINDOW_S:
            return
        next_at = now + timedelta(seconds=next_secs)
        next_slot = chime_slot(next_at, self._cfg)
        if not next_slot or next_slot == self._last_slot or next_slot == self._precache_slot:
            return
        if self._busy:
            return  # 合成中，下个 tick（20s 内）再试，窗口 60s 足够
        if not _EDGE_TTS_AVAILABLE:
            return
        sentence = build_chime_sentence(next_at, self._cfg)
        bubble = build_bubble_sentence(next_at, self._cfg)
        voice, note = resolve_voice(self._cfg["voice"])
        if note:
            self._announce_voice_substitution(note)
        key = cache_key(
            sentence,
            {
                "voice": voice,
                "rate": self._cfg["rate"],
                "pitch": self._cfg["pitch"],
            },
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._cache_dir / f"{key}.mp3"
        # 先占位：即便本次合成未在报时点前完成，到点也会回退即时合成。
        self._precache_slot = next_slot
        self._precache_text = sentence
        self._precache_bubble = bubble
        self._precache_path = str(out_path) if _cache_hit(out_path) else None
        if _cache_hit(out_path):
            logger.info("预合成命中已有缓存：%s", out_path.name)
            return
        self._busy = True
        self._busy_since = time.monotonic()
        self._synthesis_role = "precache"
        generation = self._next_synthesis_generation()
        worker = _TTSWorker(
            sentence,
            self._cfg["voice"],
            edge_rate_arg(self._cfg["rate"]),
            edge_pitch_arg(self._cfg["pitch"]),
            out_path,
            self._worker_callback(generation),
        )
        logger.info("预合成下一报时音频（%ds 后）：%s", next_secs, out_path.name)
        worker.start()

    def _consume_precache(self, slot: str) -> str | None:
        """到点取用预合成文本；未完成/文件丢失时清空并回退即时合成。

        无论命中与否都清空整组预合成状态（含气泡文本）：气泡文本由调用方
        ``_on_tick`` 在消费前取用，避免残留串到下一次报时。
        """
        if self._precache_slot == slot and self._precache_path:
            path = Path(self._precache_path)
            if path.is_file():
                text = self._precache_text
                self._precache_slot = None
                self._precache_text = None
                self._precache_bubble = None
                self._precache_path = None
                logger.info("报时命中预合成缓存：%s", path.name)
                return text
        self._precache_slot = None
        self._precache_text = None
        self._precache_bubble = None
        self._precache_path = None
        return None

    def _fire(self, sentence: str, now: datetime, bubble_text: str | None = None,
              *, show_bubble: bool = True, role: str = "play",
              respect_quiet: bool = True) -> None:
        """播报一次。

        语音用口播文本 ``sentence``（同时作为合成输入与缓存键）；气泡用
        ``bubble_text``（阿拉伯数字为主，缺省按 ``now`` 现算），二者解耦。

        ``show_bubble=False`` / ``role="speak"`` 是给外部播报（节日提醒）用的：
        只出声、不出气泡（气泡由调用方自己管），合成完成回调据此走 ``_play_only``。

        ``respect_quiet`` 见 :meth:`speak`：免打扰（含全屏等效）期间这里直接丢弃
        本次播报——**在合成之前返回**，连缓存都不查（用户听不到的声音没必要合成）。
        气泡照旧走 ``_bubble``（它自己会进暂存队列），语义与改动前逐字相同；出声的
        各条路径（缓存命中 / 即时合成 / 排队补播）都要经过本方法，所以这道闸只有
        一处。合成在飞时被静音的那一半在 ``_handle_synthesized``。``speak()`` 的
        排队入口另有一道**同语义**的闸（免打扰期间不入队，免得免打扰结束后补播一条
        过期提醒），出队时仍走本方法再判一次——免打扰状态是现读的，不是入队快照。
        """
        if not _EDGE_TTS_AVAILABLE:
            self._notify_missing_tts()
            return
        bubble = bubble_text if bubble_text is not None else build_bubble_sentence(now, self._cfg)
        if respect_quiet and self._quiet_muted():
            # 丢弃而不是补播：报时/节日语音是时间敏感的（14:00 的报时 15:00 再响没有
            # 意义），与气泡「攒着退出后统一汇报」的语义刻意不同。
            logger.debug("免打扰期间静音，丢弃本次语音（气泡照旧）：%s", sentence[:20])
            if show_bubble:
                self._bubble(bubble)
            return
        voice, note = resolve_voice(self._cfg["voice"])
        if note:
            self._announce_voice_substitution(note)
        key = cache_key(
            sentence,
            {
                "voice": voice,
                "rate": self._cfg["rate"],
                "pitch": self._cfg["pitch"],
            },
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._cache_dir / f"{key}.mp3"
        # 缓存命中（含预合成已完成）直接播放，零网络延迟；合成中不阻塞缓存播放。
        # 命中要求文件非空：失败的合成会留下 0 字节/半截文件，只判 exists() 会把
        # 它当成「已有缓存」→ 播出一声静音且再也不重新合成。
        if _cache_hit(out_path):
            if show_bubble:
                self._play_and_bubble(str(out_path), sentence, bubble)
            else:
                self._play_only(str(out_path))
            return
        if self._busy:
            # 合成在飞（多为本次报时的预合成）：排队待补，不得直接丢弃——
            # 到点回退即时合成正经此路径（_on_tick 在预合成未完成时调 _fire，
            # 被 busy 门挡死曾导致到点静默丢报时且 _last_slot 已盖戳不再重试）。
            # 这里**只判合成在飞、不判播放器**（判据刻意不是 _channel_idle）：本方法
            # 是"到点即报 / 立即报时"的入口，缓存命中在上面已直接起播——在下面加
            # 播放器判据会让同一方法里两条路径自相矛盾，还会把时间敏感的报时推迟到
            # 当前音频播完。通道占用的收敛点在两个出队口，不在这里。
            self._queued_fire = (sentence, now, bubble_text, show_bubble, role, respect_quiet)
            logger.info("语音报时合成在飞，排队待补：%s", sentence[:20])
            return
        self._busy = True
        self._busy_since = time.monotonic()
        self._synthesis_role = role
        self._synthesis_respect_quiet = respect_quiet
        self._synthesis_now = now
        self._pending_bubble = bubble if show_bubble else None
        # 本次合成有效：清掉上一次 stop() 留下的作废标记，
        # 否则新起的合成结果会被当成"迟到结果"丢弃。
        self._stopped = False
        generation = self._next_synthesis_generation()
        worker = _TTSWorker(
            sentence,
            voice,
            edge_rate_arg(self._cfg["rate"]),
            edge_pitch_arg(self._cfg["pitch"]),
            out_path,
            self._worker_callback(generation),
        )
        worker.start()

    def _worker_callback(self, generation: int):
        """取本次合成的 worker 回调（顺带保证信号桥已建好并接到本服务）。"""
        if self._bridge is None:
            self._bridge = _AudioBridge()
            self._bridge.signals.synthesized.connect(self._on_synthesized)
        return self._bridge.callback_for(generation)

    def _next_synthesis_generation(self) -> int:
        """递增合成代次并返回：起合成与 watchdog 释放各调用一次。

        代次变了 = 此前那次合成已作废（结果不再属于当前任务），它的迟到回调会被
        :meth:`_on_synthesized` 整条丢弃。
        """
        # getattr 守卫：object.__new__ 构造的测试替身没有 __init__ 属性
        generation = getattr(self, "_synthesis_generation", 0) + 1
        self._synthesis_generation = generation
        return generation

    # ------------------------------------------------------------ 播放
    def _on_synthesized(self, generation: int, path: str, text: str, error: str) -> None:
        """合成完成回调（GUI 线程）。首参是**动身时的代次**，用来认领本次任务。

        代次不一致 = 这次合成的结果已作废（超时自愈释放过、当前在跑的是别的一路）：
        整条丢弃——一个字段都不碰。否则旧任务会取走**新任务**的 role /
        respect_quiet 与 busy 锁：该被静音的旧提醒出声、应豁免的新语音被静音。
        """
        if generation != getattr(self, "_synthesis_generation", None):
            logger.debug("丢弃已作废旧合成的迟到结果（代次 %s，当前 %s）：%s",
                         generation, getattr(self, "_synthesis_generation", None),
                         Path(path).name)
            return
        role = self._synthesis_role
        self._synthesis_role = "play"
        respect_quiet = self._synthesis_respect_quiet
        self._synthesis_respect_quiet = True
        self._busy = False
        try:
            self._handle_synthesized(role, path, text, error, respect_quiet)
        finally:
            # 任何结局（完成/失败/已停止）都必须结算排队项：_stopped 时
            # _drain 内部丢弃，其余情况补播——不能让到点报时静默消失。
            # 两处判据都在 drain 内部（_channel_idle），调用点不再各自判：
            # 起了播的完成 → 通道被接管 → 两个队列都原样留队（EndOfMedia 再结算）；
            # 没起播的完成（预合成 / 免打扰丢弃 / 合成失败 / 已停止）→ 通道空出却
            # 没有 EndOfMedia → 就在此结清。
            # 顺序是「先 _drain_queued_fire」：待补播的报时若在此起了合成，待播语音
            # 会被留队（豁免随队携带），等下一拍——报时优先，且条目不丢。
            self._drain_queued_fire()
            self._drain_pending_speech()

    def _drain_queued_fire(self) -> None:
        """补播被 busy 门拦下的排队播报（若有）；通道不空闲则留队，stop() 后丢弃。

        出队口之一（另两处：:meth:`_on_media_status` 的终止态、:meth:`_on_synthesized`
        的 finally 收口），三处共用同一条判据 :meth:`_channel_idle`。
        """
        # 通道不空闲就**原样留队**（字段一律不动），等下一拍：合成完成 / EndOfMedia /
        # 合成超时自愈。——刚起播那一刻也算不空闲，否则会顶掉刚起播的那一段。
        if not self._channel_idle():
            return
        # getattr 守卫：object.__new__ 构造的测试替身没有 __init__ 属性
        queued = getattr(self, "_queued_fire", None)
        self._queued_fire = None
        if queued is None or self._stopped:
            return
        sentence, now, bubble_text, show_bubble, role, respect_quiet = queued
        self._fire(sentence, now, bubble_text, show_bubble=show_bubble, role=role,
                   respect_quiet=respect_quiet)

    def _handle_synthesized(self, role: str, path: str, text: str, error: str,
                            respect_quiet: bool = True) -> None:
        if self._stopped:
            # stop()（关闭开关 / 应用退出）之后才回来的结果：不再回放/气泡——
            # 否则「关掉语音报时之后又响一声」，退出路径上还可能触碰正在析构的窗口。
            logger.info("语音报时已停止，丢弃迟到的合成结果：%s", Path(path).name)
            return
        if error:
            if error == EDGE_TTS_MISSING:
                # 运行期才发现 edge-tts 缺失（顶层只做 find_spec 探测）：清掉可能
                # 残留的预合成占位，再走既有缺依赖降级文案。
                if role == "precache":
                    self._precache_slot = None
                    self._precache_text = None
                    self._precache_bubble = None
                    self._precache_path = None
                self._notify_missing_tts()
                return
            if role == "precache":
                # 预合成失败：丢弃占位，到点走即时合成回退。
                self._precache_slot = None
                self._precache_text = None
                self._precache_bubble = None
                self._precache_path = None
                logger.warning("预合成失败，到点将即时合成：%s", error)
                return
            logger.warning("语音报时合成失败：%s", error)
            self._bubble(f"语音合成失败（{error[:40]}…）")
            return
        if role == "precache":
            # 预合成完成：仅记录缓存路径，不播放（到点由 _fire 直接播缓存）。
            self._precache_path = str(path)
            logger.info("预合成完成：%s", Path(path).name)
            return
        if respect_quiet and self._quiet_muted():
            # 合成期间才进入免打扰（合成要 3-8s，全屏/手动免打扰都可能在中间发生）：
            # 结果既不出声也不回放，气泡仍按既有语义走（_bubble 自己会进暂存队列）。
            logger.debug("免打扰期间静音，丢弃合成结果（气泡照旧）：%s", Path(path).name)
            if role != "speak":
                self._bubble(self._pending_bubble if self._pending_bubble is not None else text)
            # 这次完成不起播 = 通道空出，待播 speech 由 _on_synthesized 的 finally
            # 统一出队（本次是其中之一，见那里）。此处不得再调一次：双出队路径。
            return
        # 播放那一刻重判通道占用：合成期间别的音频可以合法地起播——报时经缓存
        # 例外（_fire 的缓存命中路径不看占用），合成前判过的空闲早已不作数。此刻
        # setSource+play 会把在播的那一段顶掉（它的音源被替换、永远等不到
        # EndOfMedia）。改为回队，等下一拍按既有不变量（_channel_idle）出队。
        if role == "speak":
            # 外部播报（节日提醒）：只出声，气泡由调用方自己展示。
            if self._player_engaged():
                logger.debug("播放时刻通道已被占用，外部播报回队待播：%s", text[:20])
                self._pending_speech = text
                self._pending_respect_quiet = respect_quiet
                return
            self._play_only(path)
            return
        if self._player_engaged():
            logger.debug("播放时刻通道已被占用，报时回队待播：%s", text[:20])
            # 原 tuple 各字段原样带回（now 见 _synthesis_now 的说明）。
            self._queued_fire = (text, self._synthesis_now, self._pending_bubble,
                                self._pending_bubble is not None, role, respect_quiet)
            return
        self._play_and_bubble(path, text, self._pending_bubble)

    def _play_and_bubble(self, path: str, text: str, bubble_text: str | None = None) -> None:
        """播放音频并展示气泡。

        ``text`` 为语音口播文本（中文数字）；气泡优先用 ``bubble_text``
        （阿拉伯数字文本），未传时回退 ``text`（兼容旧调用与测试）。

        **本方法不判通道占用**：它是"把这一段交给播放器"的执行末端，占用判定归
        调用方（``_handle_synthesized`` 的播放出口、``_fire`` 的缓存命中路径）。
        在这里加判据会变成静默不播，而回队的语义只能由调用方给。
        """
        if not self._ensure_player():
            self._bubble(f"播放器不可用，音频已缓存：{Path(path).name}")
            return
        try:
            from PySide6.QtCore import QUrl

            self._audio_out.setVolume(self._cfg["volume"] / 100.0)
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
        except Exception:
            logger.exception("语音报时播放失败：%s", path)
            self._bubble("语音播放失败（设备/解码器异常）")
            return
        self._bubble(bubble_text if bubble_text is not None else text)

    def _play_only(self, path: str) -> bool:
        """只播放音频、不展示气泡（外部播报用，气泡由调用方自己管）。

        返回是否成功起播；失败只记日志——外部的气泡/提示由调用方决定，
        这里再插一条报时风格的气泡会与对方的展示重复。

        **本方法不判通道占用**（同 :meth:`_play_and_bubble`）：占用判定与"回队"
        的语义都在调用方（``_handle_synthesized`` 的播放出口）。
        """
        if not self._ensure_player():
            logger.warning("播放器不可用，外部播报跳过播放：%s", Path(path).name)
            return False
        try:
            from PySide6.QtCore import QUrl

            self._audio_out.setVolume(self._cfg["volume"] / 100.0)
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
            return True
        except Exception:
            logger.exception("外部播报播放失败：%s", path)
            return False

    def _player_engaged(self) -> bool:
        """播放器是否已**接管**音频通道（正在出声，或刚起播、媒体仍在加载）。

        认 ``LoadingMedia`` 是必须的：``playbackState`` 判不了"刚起播"。实机实测
        （QMediaPlayer + QAudioOutput，offscreen）——``setSource`` 后立刻 ``play()``，
        那一刻 ``playbackState`` 仍是 ``StoppedState``、``mediaStatus`` 为
        ``LoadingMedia``，约 300ms 后才转 ``PlayingState``/``BufferingMedia``；而本
        模块的判据点（三个出队口与 speak/play_file 入口）恰恰可能落在那一刻，只看
        ``playbackState`` 会把刚接管的通道当成空出，让新的语音顶掉刚起播的那一段。
        """
        if self._player is None:
            return False
        try:
            from PySide6.QtMultimedia import QMediaPlayer

            return (
                self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                or self._player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia
            )
        except Exception:
            # 拿不到判据（QtMultimedia 缺失 / object.__new__ 测试替身没有这些方法）
            # 时按"未接管"处理：出队总比滞留安全（滞留就是本模块要修的那类静默丢语音）。
            return False

    def _channel_idle(self) -> bool:
        """音频通道是否**真空闲**：无合成在飞 且 播放器未接管。

        全模块唯一的占用判据：两个补播队列的出队口（不空闲就原样留队）与 speak /
        play_file 的入口门（不空闲就排队 / 让路）都读它。``_fire`` 是唯一例外且是
        刻意的（到点即报的入口，见那里的说明）。
        """
        return not self._busy and not self._player_engaged()

    def _on_media_status(self, status) -> None:
        """媒体状态变化：终止态（播完/坏媒体）即"通道空出"，排空两个补播队列。

        终止态是"这一段音频真的结束了"的唯一信号：此刻两个队列里被占用判据留过队
        的条目都必须结算（报时优先，见 :meth:`_on_synthesized` 的同序说明）——否则
        留队的报时排队项要等下一次合成完成才有下一拍，最坏等到下个报时点。

        **刻意不在本方法里 import QtMultimedia**：终止态枚举在 ``_ensure_player``
        成功创建播放器时缓存到 ``self._terminal_statuses``。这样本方法没有 Qt
        导入（Linux 上 QtMultimedia 会拖 libpulse 等系统库，缺失即 ImportError），
        也让单元测试无需为了拿枚举值去导入 QtMultimedia——CI 的 ubuntu 作业正是
        因为测试里那次导入而红过。
        """
        if status not in getattr(self, "_terminal_statuses", ()):
            return
        self._drain_queued_fire()
        self._drain_pending_speech()

    def _drain_pending_speech(self) -> None:
        """待播语音出队：通道真空闲时补播那一条（若有）并消费掉队列字段。

        出队口之一，与 :meth:`_drain_queued_fire` 共用同一条判据（:meth:`_channel_idle`）
        与同三个触发点：合成完成（:meth:`_on_synthesized` 的 finally）、媒体终止
        （:meth:`_on_media_status`）、合成超时自愈（:meth:`_release_stale_busy`）。
        凡是**合成完成却没起播**的结局（预合成、免打扰丢弃、合成失败、已停止）都
        不会有 EndOfMedia，待播语音不能指望那个事件来出队，否则会无声滞留到被后续
        偶然事件覆盖（豁免的那条被 ``_fire`` 照常播，尊重免打扰的那条被 ``_fire``
        的闸现读再丢一次，``_stopped`` 在这里直接丢弃）。

        **通道不空闲就原样留队**（字段一律不动）：合成在飞时出队会被 ``_fire`` 的
        busy 门迁进 ``_queued_fire``（离开了 END 的出口），播放器被接管时补播会顶掉
        刚起播的那一段——两者都是本模块修过的坑，判据内置在这里，调用点不再各自判。
        """
        if not self._channel_idle():
            return
        # getattr 守卫：object.__new__ 构造的测试替身没有 __init__ 属性
        pending = getattr(self, "_pending_speech", None)
        self._pending_speech = None
        # 随队携带的免打扰口径一并取出、并复位为默认值（与 _pending_speech 同生命周期）。
        respect_quiet = getattr(self, "_pending_respect_quiet", True)
        self._pending_respect_quiet = True
        if not pending or self._stopped:
            return
        self._fire(pending, datetime.now(), None, show_bubble=False, role="speak",
                   respect_quiet=respect_quiet)

    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer()
            self._audio_out = QAudioOutput()
            self._player.setAudioOutput(self._audio_out)
            # 缓存终止态枚举，供 _on_media_status 判空时使用（见该方法的说明）。
            self._terminal_statuses = (
                QMediaPlayer.MediaStatus.EndOfMedia,
                QMediaPlayer.MediaStatus.InvalidMedia,
            )
            # 播完一条后排空待播队列（外部播报排队用）。
            self._player.mediaStatusChanged.connect(self._on_media_status)
            return True
        except Exception:
            logger.exception("创建 QMediaPlayer 失败（检查 QtMultimedia ffmpegmediaplugin）")
            return False

    # ------------------------------------------------------------ 提示
    def _quiet_muted(self) -> bool:
        """当前是否因免打扰（含全屏等效）静音语音报时 / 节日语音。

        判据与气泡**同源**：``window_alerts.quiet_blocked`` 转发 ``quiet_mode`` 的
        唯一判据（手动或全屏等效，以及 ``quiet_also_on_fullscreen`` 配置），本方法
        只负责取宿主窗口，不另读标志——两处判据各自读标志就会出现"气泡压住了、
        声音还在响"这类不一致。

        宿主没有窗口（无 GUI 的测试替身 / 纯逻辑调用）时返回 False：没有窗口就
        没有全屏避让，免打扰也无从谈起。
        """
        from . import window_alerts

        win = getattr(self._app, "win", None)
        return win is not None and window_alerts.quiet_blocked(win)

    def _bubble(self, text: str) -> None:
        """桌宠气泡展示报时文字（受 voice_chime_show_bubble 开关控制）。

        设置窗口打开等场景下 window.show_bubble 会被抑制（_bubble_suppressed），
        报时属用户主动关注事件，此时直接经桌宠气泡位（_speech_bubble）展示，
        避免“只听声不见字”。

        飞行期是唯一的例外：这是**瞬时**状态（鱼被撞飞几秒），此时连直写也
        禁掉（鱼飞行过程中不弹气泡），也不排队、不改道系统通知——一次性播报
        丢弃即可，落地后正常。判据统一走 ``window_alerts`` 的门禁助手（惰性
        import：本模块顶层不 import Qt，见文件头）。
        """
        if not self._cfg.get("show_bubble", True):
            return
        from . import window_alerts
        app = self._app
        win = getattr(app, "win", None)
        # 免打扰（含全屏等效）判定在**可见性判断之前**（同 festival_service）：
        # 宿主隐藏时若先看 isVisible，报时提醒会走系统通知，免打扰压不住也不进
        # 暂存队列。这里的暂存只针对**气泡**：语音由 _fire / _handle_synthesized
        # 的静音闸丢弃（不补播，理由见 _fire 的说明）。
        if win is not None and window_alerts.quiet_blocked(win):
            window_alerts.defer_quiet(text)
            return
        if win is not None and win.isVisible():
            if window_alerts.sprite_in_flight(win):
                return
            suppressed = window_alerts.bubble_blocked(win)
            if not suppressed:
                try:
                    win.show_bubble(text, duration_ms=self.BUBBLE_DURATION_MS)
                    return
                except Exception:
                    logger.exception("气泡展示失败")
            try:
                bubble = getattr(win, "_speech_bubble", None)
                rect = win.visible_content_rect()
                scale = getattr(win, "scale", 1.0)
                if bubble is not None and rect is not None:
                    bubble.show_text(
                        text,
                        rect,
                        self.BUBBLE_DURATION_MS,
                        pet_scale=scale,
                        subtitle="",
                    )
                    return
            except Exception:
                logger.exception("报时气泡降级展示失败")
        notify = getattr(app, "system_notify", None)
        if callable(notify):
            try:
                notify("语音报时", text)
            except Exception:
                logger.exception("桌面通知失败")

    def _notify_missing_tts(self) -> None:
        msg = "语音报时需要 edge-tts 库：请运行 pip install edge-tts 后重试"
        logger.warning(msg)
        self._bubble(msg)

    def _announce_voice_substitution(self, note: str) -> None:
        """配置音色已失效的说明：同一进程只弹一次，别每次报时都刷屏。"""
        if note in _VOICE_SUBSTITUTION_NOTICES:
            logger.debug("已提示过：%s", note)
            return
        _VOICE_SUBSTITUTION_NOTICES.add(note)
        logger.warning(note)
        self._bubble(note)

    def _release_stale_busy(self) -> None:
        """合成线程异常未回调时复位 _busy；否则报时/预合成会被永久跳过。"""
        if not self._busy:
            return
        if time.monotonic() - self._busy_since < _SYNTH_TIMEOUT_S:
            return
        logger.warning("语音合成超时未回调，复位合成锁（%.0fs）", _SYNTH_TIMEOUT_S)
        self._busy = False
        self._synthesis_role = "play"
        # 代次递增 = 这次挂死的合成从此作废：它若日后才回调（网络超时后返回），
        # 回调带的旧代次会被 _on_synthesized 认出来并整条丢弃，不会串到随后起的
        # 新任务上（取走新任务的 role / respect_quiet / busy 锁）。
        self._next_synthesis_generation()
        # 合成锁复位后结算排队项：挂死的合成不会再来回调，到点报时靠这里补。
        # 两个队列同序结算（报时优先），判据在 drain 内部——这里是超时自愈这一拍，
        # 不结算待播语音就会让它永远没人出队（挂死的合成也不会再产生 END）。
        self._drain_queued_fire()
        self._drain_pending_speech()

    # ------------------------------------------------------------ 缓存维护
    def _prune_cache(self) -> None:
        """缓存超上限时按修改时间清理最旧文件（节流，避免每次配置变更全扫）。"""
        now = time.monotonic()
        if self._last_prune_at and now - self._last_prune_at < _PRUNE_MIN_INTERVAL_S:
            return
        self._last_prune_at = now
        try:
            if not self._cache_dir.is_dir():
                return
            files = sorted(
                (p for p in self._cache_dir.glob("*.mp3")),
                key=lambda p: p.stat().st_mtime,
            )
            for old in files[: max(0, len(files) - self.MAX_CACHE_FILES)]:
                try:
                    old.unlink(missing_ok=True)
                except OSError:
                    logger.debug("清理语音缓存失败：%s", old)
        except OSError:
            logger.debug("语音缓存目录不可访问：%s", self._cache_dir)
