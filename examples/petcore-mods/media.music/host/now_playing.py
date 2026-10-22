"""读取 Windows 系统媒体会话（SMTC）：当前曲目、进度与传输控制（无 Qt）。

数据来源是 Windows 的 SMTC——播放器主动向系统上报的会话（网易云、QQ 音乐、
酷狗、汽水、浏览器……）。所以这里不需要为单个播放器做适配。

三条实测口径（沿用主分支 ``pet/now_playing.py`` 的结论）：

- **进度不一定有**：QQ 音乐会上报 position/end_time；网易云与酷狗恒为 0。
  因此 :attr:`Playback.position` 允许为 ``None``（"该播放器不提供进度"），
  调用方回退到本地计时。
- **不是所有会话都是歌**：浏览器把网页**视频**也上报成 ``MUSIC(1)``，SMTC 里没有
  字段能把两者分开，只能按会话来源否决（:func:`accepts_singing`）。浏览器会话
  还需要配置里显式打开 ``music_browser_media_enabled``；系统提示音/通知类应用
  在 :data:`_VETO_APP_IDS` 里直接否决。
- **winrt 只在这里惰性导入**：它在非 Windows 或未装可选依赖时不存在；导入发生在
  调用线程（运行时是后台轮询线程），模块导入本身不碰 COM。

**未移植 foobar2000 窗口标题源**：它需要读进程列表 + 枚举顶层窗口标题，属于另一
套 Win32 代码（主分支 ``pet/foobar_playing.py``）。本 mod 只做 SMTC；foobar 用户
可以在 foobar 里装 SMTC 插件，或继续用主分支版本。这条省略是刻意的。

本模块只读系统信息与发传输控制，不发起任何网络请求、不触碰音频流。
"""

from __future__ import annotations

import asyncio
import sys
import threading
from dataclasses import dataclass

# Windows.Media.MediaPlaybackType
MEDIA_TYPE_UNKNOWN = 0
MEDIA_TYPE_MUSIC = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_IMAGE = 3

# Windows.Media.Control.GlobalSystemMediaTransportControlsSessionPlaybackStatus
PLAYBACK_STATUS_PLAYING = 4

#: 判定"不上报进度"的阈值：末位时长小于该值视为无效时间轴。
_MIN_VALID_DURATION = 0.01

#: 已知浏览器的 SMTC app_id（小写、去掉 ``.exe`` 后比较）。这是**否决表不是白名单**：
#: 表外应用一律不受影响，只有明确认识的浏览器才走浏览器开关分支。
_BROWSER_APP_IDS = frozenset(
    {
        "msedge",
        "microsoftedge",
        "chrome",
        "chromium",
        "firefox",
        "brave",
        "bravebrowser",
        "opera",
        "vivaldi",
        "arc",
    }
)

#: 系统提示音 / 通知类应用：它们会上报"在播"，但不是歌。
_VETO_APP_IDS = frozenset(
    {
        "systemsettings",
        "shellexperiencehost",
        "windows.ui.core.corewindow",
        "notificationlistenerservice",
        "lockapp",
    }
)

#: 选会话时的类型优先级（越小越优先）：音乐 > 未上报 > 图片（视频已否决）。
_MEDIA_TYPE_RANK = {
    MEDIA_TYPE_MUSIC: 0,
    MEDIA_TYPE_UNKNOWN: 1,
    MEDIA_TYPE_IMAGE: 2,
}

#: 传输命令 → 气泡里的成功文案。
ACTION_LABELS = {
    "pause": "播放/暂停",
    "next": "下一首",
    "prev": "上一首",
    "stop": "停止播放",
}


@dataclass(frozen=True, slots=True)
class Playback:
    """一次采样结果：曲目 + 进度。``position=None`` 表示播放器不上报进度。"""

    title: str = ""
    artist: str = ""
    app_id: str = ""
    position: float | None = None
    duration: float = 0.0
    playing: bool = False
    source: str = "smtc"

    def key(self) -> tuple[str, str]:
        """判断"是否换了首歌"的标识（大小写/空白归一）。"""
        return (self.title.strip().lower(), self.artist.strip().lower())

    def label(self) -> str:
        title = self.title.strip()
        artist = self.artist.strip()
        if title and artist:
            return f"{artist} - {title}"
        return title or artist or "未知曲目"


@dataclass(frozen=True, slots=True)
class Session:
    """一个 SMTC 会话的采样快照（选择器的输入，纯数据）。"""

    app_id: str = ""
    media_type: int = MEDIA_TYPE_UNKNOWN
    playing: bool = False
    browser: bool = False
    vetoed: bool = False
    index: int = 0

    @property
    def type_rank(self) -> int:
        return _MEDIA_TYPE_RANK.get(self.media_type, _MEDIA_TYPE_RANK[MEDIA_TYPE_UNKNOWN])


def normalized_app_id(app_id: str | None) -> str:
    """归一化 SMTC app_id：小写、去空白、去 ``.exe`` 后缀。

    实测同一台机器上形状不统一（``Chrome`` / ``MSEdge`` / ``cloudmusic.exe``），
    比较前必须归一。
    """
    value = str(app_id or "").strip().lower()
    if value.endswith(".exe"):
        value = value[:-4]
    return value


def is_browser_session(app_id: str | None) -> bool:
    return normalized_app_id(app_id) in _BROWSER_APP_IDS


def is_vetoed_session(app_id: str | None) -> bool:
    return normalized_app_id(app_id) in _VETO_APP_IDS


def accepts_singing(session: Session, *, browser_media_enabled: bool = False) -> bool:
    """该会话能不能进歌词/唱歌链路（唯一一份否决规则）。"""
    if session.vetoed:
        return False
    if session.media_type in (MEDIA_TYPE_VIDEO, MEDIA_TYPE_IMAGE):
        return False
    if session.browser and not browser_media_enabled:
        return False
    return True


def pick_singing_session(
    sessions: list[Session] | tuple[Session, ...],
    *,
    browser_media_enabled: bool = False,
    tracked_app_id: str = "",
) -> Session | None:
    """在**可接受候选**里为歌词/唱歌链路选会话。

    被否决的会话（视频 / 图片 / 表内的系统应用 / 开关关时的浏览器）在选择阶段
    就被剔除，而不是先选出赢家再否决——否则浏览器报的音乐会挤掉同播的原生播放器。
    候选内：在播者按类型分层（音乐 > 未上报），层内优先"上次跟踪的那个"，否则取
    枚举顺序最靠前的；都没在播则留在跟踪对象上（暂停时不跳走）；否则取第一个。
    一个候选都没有时返回 ``None``。
    """
    accepted = [
        session for session in sessions if accepts_singing(session, browser_media_enabled=browser_media_enabled)
    ]
    if not accepted:
        return None
    wanted = normalized_app_id(tracked_app_id)
    tracked = None
    if wanted:
        tracked = next(
            (session for session in accepted if normalized_app_id(session.app_id) == wanted),
            None,
        )
    playing = [session for session in accepted if session.playing]
    if playing:
        best = min(session.type_rank for session in playing)
        tier = [session for session in playing if session.type_rank == best]
        if tracked is not None and tracked.playing and tracked.type_rank == best:
            return tracked
        return tier[0]
    if tracked is not None:
        return tracked
    return accepted[0]


# ---------------------------------------------------------------- winrt 惰性导入


def _manager_class():
    """惰性导入 SMTC 管理器；非 Windows / 未装 winrt 时返回 ``None``。"""
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as manager_class,
        )
    except Exception:
        return None
    return manager_class


def unavailable_reason() -> str:
    """为什么读不到 SMTC（给用户看的一句话）；可用时返回空串。"""
    if sys.platform != "win32":
        return "当前系统不支持读取系统媒体信息（仅 Windows）。"
    if _manager_class() is None:
        return "读取不到系统媒体会话：缺少 winrt 组件，请重装桌宠。"
    return ""


_LOOP_LOCAL = threading.local()

#: 单次采样/控制的超时（秒）：正常采样实测 ~5ms 级；没有它，一次永不返回的
#: WinRT 请求会把采样线程永久钉住（主分支的现场教训）。
CALL_TIMEOUT = 3.0


def _run_sync(coro):
    """在调用线程的**常驻**事件循环里跑协程（每拍新建循环是主分支实测的开销大头）。

    SMTC 查询在 GUI 主线程实测会永久阻塞窗口，所以调用方必须在后台线程里用它。
    """
    loop = getattr(_LOOP_LOCAL, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _LOOP_LOCAL.loop = loop
    return loop.run_until_complete(coro)


def close_thread_loop() -> None:
    """关闭**本线程**的常驻事件循环（采样线程退出时调用，避免未关闭循环告警）。"""
    loop = getattr(_LOOP_LOCAL, "loop", None)
    _LOOP_LOCAL.loop = None
    if loop is None:
        return
    try:
        if not loop.is_closed():
            loop.close()
    except Exception:
        return


def _session_app_id(session) -> str:
    try:
        return str(getattr(session, "source_app_user_model_id", "") or "")
    except Exception:
        return ""


def _read_playback_info(session):
    try:
        return session.get_playback_info()
    except Exception:
        return None


def _read_media_type(holder) -> int:
    """读 ``playback_type``；读不到一律按 Unknown（绝不冒到外层当成"播放器没了"）。"""
    try:
        value = getattr(holder, "playback_type", None)
        return MEDIA_TYPE_UNKNOWN if value is None else int(value)
    except Exception:
        return MEDIA_TYPE_UNKNOWN


def _read_status(holder) -> int | None:
    try:
        return int(holder.playback_status)
    except Exception:
        return None


def _snapshot(session, index: int) -> Session:
    app_id = _session_app_id(session)
    info = _read_playback_info(session)
    status = _read_status(info)
    return Session(
        app_id=app_id,
        media_type=_read_media_type(info),
        playing=status == PLAYBACK_STATUS_PLAYING,
        browser=is_browser_session(app_id),
        vetoed=is_vetoed_session(app_id),
        index=index,
    )


async def _read_async(*, browser_media_enabled: bool, tracked_app_id: str):
    manager_class = _manager_class()
    if manager_class is None:
        return None, unavailable_reason()
    manager = await manager_class.request_async()
    raw_sessions = list(manager.get_sessions() or ())
    if not raw_sessions:
        return None, "系统里没有正在播放的媒体会话。"
    snapshots = [_snapshot(session, index) for index, session in enumerate(raw_sessions)]
    chosen = pick_singing_session(
        snapshots, browser_media_enabled=browser_media_enabled, tracked_app_id=tracked_app_id
    )
    if chosen is None:
        return None, "当前媒体会话不是音乐（视频或未开启的浏览器会话已被过滤）。"
    session = raw_sessions[chosen.index]

    # 字段各自兜住：选取与读取之间会话可能失效，或时间轴字段异常。
    try:
        props = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        duration = float(timeline.end_time.total_seconds())
        raw_position = float(timeline.position.total_seconds())
    except Exception:
        return None, "读取系统媒体信息失败。"
    title = str(getattr(props, "title", "") or "").strip()
    artist = str(getattr(props, "artist", "") or "").strip()
    if not title and not artist:
        return None, "当前会话没有曲目信息（可能还在加载）。"
    has_timeline = duration > _MIN_VALID_DURATION
    return (
        Playback(
            title=title,
            artist=artist,
            app_id=chosen.app_id,
            position=raw_position if has_timeline else None,
            duration=duration if has_timeline else 0.0,
            playing=chosen.playing,
            source="smtc",
        ),
        "",
    )


def read_playback_with_reason(
    *,
    browser_media_enabled: bool = False,
    tracked_app_id: str = "",
) -> tuple[Playback | None, str]:
    """采样当前曲目；读不到时第二项是给用户看的原因（不抛异常）。"""
    reason = unavailable_reason()
    if reason:
        return None, reason
    try:
        return _run_sync(
            asyncio.wait_for(
                _read_async(
                    browser_media_enabled=bool(browser_media_enabled),
                    tracked_app_id=str(tracked_app_id or ""),
                ),
                CALL_TIMEOUT,
            )
        )
    except (asyncio.TimeoutError, TimeoutError):
        return None, "读取系统媒体信息超时。"
    except Exception:
        return None, "读取系统媒体信息失败。"


def read_playback(
    *,
    browser_media_enabled: bool = False,
    tracked_app_id: str = "",
) -> Playback | None:
    """采样当前曲目；无播放器/无会话/任何异常都返回 ``None``。"""
    return read_playback_with_reason(
        browser_media_enabled=browser_media_enabled, tracked_app_id=tracked_app_id
    )[0]


# ---------------------------------------------------------------- 传输控制


def _pick_transport_session(manager, tracked_app_id: str):
    """传输控制用选择器：跟随在播的会话，暂停时不跳到别的会话上。

    与唱歌链路刻意隔离：用户在看视频时点「暂停」就该暂停那个视频，所以这里既不做
    媒体类型分层、也不做唱歌链路的否决。
    """
    sessions = list(manager.get_sessions() or ())
    if not sessions:
        return None
    wanted = normalized_app_id(tracked_app_id)
    tracked_session = None
    tracked_playing = False
    playing = []
    for session in sessions:
        info = _read_playback_info(session)
        is_playing = _read_status(info) == PLAYBACK_STATUS_PLAYING
        if wanted and normalized_app_id(_session_app_id(session)) == wanted:
            tracked_session, tracked_playing = session, is_playing
        if is_playing:
            playing.append(session)
    if tracked_session is not None and tracked_playing:
        return tracked_session
    if playing:
        return playing[0]
    if tracked_session is not None:
        return tracked_session
    return sessions[0]


async def _transport_async(action: str, tracked_app_id: str) -> tuple[bool, str]:
    manager_class = _manager_class()
    if manager_class is None:
        return False, unavailable_reason()
    manager = await manager_class.request_async()
    session = _pick_transport_session(manager, tracked_app_id)
    if session is None:
        return False, "当前没有可控制的播放器（请先在播放器里播放一首歌）。"
    info = _read_playback_info(session)
    controls = getattr(info, "controls", None)
    if action == "pause":
        ok = bool(await session.try_toggle_play_pause_async())
        return ok, "" if ok else "这个播放器不支持播放/暂停。"
    if action == "stop":
        stop = getattr(session, "try_stop_async", None)
        enabled = True if controls is None else bool(getattr(controls, "is_stop_enabled", True))
        if stop is None or not enabled:
            return False, "这个播放器不支持停止。"
        ok = bool(await stop())
        return ok, "" if ok else "这个播放器不支持停止。"
    previous = action == "prev"
    flag = "is_previous_enabled" if previous else "is_next_enabled"
    if controls is not None and not bool(getattr(controls, flag, False)):
        return False, "这个播放器不支持切歌（网络电台之类）。"
    method = session.try_skip_previous_async if previous else session.try_skip_next_async
    ok = bool(await method())
    return ok, "" if ok else "这个播放器不支持切歌（网络电台之类）。"


def transport(action: str, *, tracked_app_id: str = "") -> tuple[bool, str]:
    """发一个传输命令；返回 ``(是否成功, 失败原因)``，绝不抛异常。"""
    if action not in ACTION_LABELS:
        return False, f"不认识的操作：{action}"
    reason = unavailable_reason()
    if reason:
        return False, reason
    try:
        return _run_sync(asyncio.wait_for(_transport_async(action, str(tracked_app_id or "")), CALL_TIMEOUT))
    except (asyncio.TimeoutError, TimeoutError):
        return False, "系统媒体控制调用超时，请稍后重试。"
    except Exception:
        return False, "系统媒体控制调用失败，请稍后重试。"
