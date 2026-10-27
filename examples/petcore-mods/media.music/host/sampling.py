"""一次识别的**采样编排**：三源按需采集，产出 ``Sample``（零 Qt，端口/探针可注入）。

为什么单独一个模块：运行时的每秒一拍与设置页的「识别诊断」按钮要采**同一份**
证据，否则诊断说的和实际判定的不是一回事。把"什么时候问哪个源"收在一处：

- **SMTC 恒定**：它是主源，元数据、时间轴、传输控制都来自它；
- **音频会话恒定**：它便宜（实测 2ms 级），而且是"在不在出声"的裁判；
- **窗口标题按需**：只在 SMTC 没有"在播"会话时才枚举——这一条把空闲时的
  系统调用省掉（窗口枚举实测 0.5ms，但它会碰到别的进程的标题，能不问就不问）。

任何一源抛异常都折成"该源没有数据"，绝不冒泡到调用方：音乐是锦上添花。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import audio_sessions, now_playing, window_source


@dataclass(frozen=True, slots=True)
class Sample:
    """三源的一次采样（``recognizer.decide`` 的输入，也是诊断文本的数据源）。"""

    playback: object = None
    sessions: tuple = ()
    smtc_reason: str = ""
    smtc_error: bool = False
    audio: tuple = ()
    audio_available: bool = True
    windows: tuple = ()
    window_available: bool = True


def collect(
    *,
    browser_media_enabled: bool = False,
    tracked_app_id: str = "",
    allowed_ids: frozenset[str] | None = None,
    targets: frozenset[str] | None = None,
    smtc=None,
    audio=None,
    windows=None,
) -> Sample:
    """采一次三源。``smtc`` / ``audio`` / ``windows`` 是测试注入缝（默认模块函数）。"""
    read_smtc = smtc or now_playing.read_sample
    read_audio = audio or audio_sessions.snapshot
    read_windows = windows or window_source.snapshot

    kwargs: dict = {
        "browser_media_enabled": bool(browser_media_enabled),
        "tracked_app_id": str(tracked_app_id or ""),
    }
    if allowed_ids:
        kwargs["allowed_ids"] = frozenset(allowed_ids)
    try:
        smtc_sample = read_smtc(**kwargs)
    except Exception:
        smtc_sample = now_playing.SmtcSample(reason="读取系统媒体信息失败。", failed=True)

    audio_available = _available(audio_sessions.available)
    audio_rows: tuple = ()
    if audio_available:
        try:
            audio_rows = tuple(read_audio() or ())
        except Exception:
            audio_rows = ()

    window_available = _available(window_source.available)
    playback = getattr(smtc_sample, "playback", None)
    need_window = playback is None or not bool(getattr(playback, "playing", False))
    window_rows: tuple = ()
    if window_available and need_window:
        try:
            window_rows = tuple(read_windows(frozenset(targets or ())) or ())
        except Exception:
            window_rows = ()

    return Sample(
        playback=playback,
        sessions=tuple(getattr(smtc_sample, "sessions", ()) or ()),
        smtc_reason=str(getattr(smtc_sample, "reason", "") or ""),
        smtc_error=bool(getattr(smtc_sample, "failed", False)),
        audio=audio_rows,
        audio_available=audio_available,
        windows=window_rows,
        window_available=window_available,
    )


def _available(probe) -> bool:
    try:
        return bool(probe())
    except Exception:
        return False
