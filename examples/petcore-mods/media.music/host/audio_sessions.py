"""逐进程的 WASAPI 音频会话采样：谁真的在出声、有没有被静音（无 Qt、无宿主依赖）。

SMTC 只说"某个播放器上报了在播"，它回答不了两个会直接影响唱歌动画的问题：

1. **真的在出声吗**：播放器暂停后常把会话留在 Active，而静音、音量拉到 0、或
   只是挂着窗口没播音频时，SMTC 里依旧"在播"——照着它唱歌就会在无声的房间里
   张嘴巴。WASAPI 会话带 ``GetMute()`` 与 ``GetPeakValue()`` 两条独立证据。
2. **不注册 SMTC 的播放器**（foobar2000、AIMP、Winamp）在 SMTC 里根本不存在，
   但它们在音频引擎里一定有会话。这是唯一能看见它们的系统级入口。

本模块只报事实（状态 / 静音 / 峰值），不做"算不算在播"的判定——那需要"多久
的静音才算停"这种时间上下文，属于调用方。

三条实测口径（都写死了，别改成看起来更整齐的写法）：

- **不能用 ``AudioUtilities.GetAllSessions()``**：它每次调用都重新取默认端点并
  ``Activate``（本机实测约 23ms）。缓存
  ``AudioUtilities.GetSpeakers().AudioSessionManager`` 之后手动
  ``GetSessionEnumerator`` 枚举：5 个会话纯枚举约 1.0ms，连状态 / 静音 / 峰值 /
  进程名一起读完约 2.3ms（峰值那趟 ``QueryInterface(IAudioMeterInformation)``
  占大头）。重建端点只发生在异常或 0 条会话时，且节流到 30 秒一次。
- **COM 必须在调用线程初始化**：comtypes 的接口指针不能跨 apartment 白用，
  所以缓存记着是哪个线程建的；换了线程就重建一份，线程退出前由 :func:`close`
  配对 ``CoUninitialize``。
- **同一进程可能有多个会话**（网易云实测两个：主进程一个、音频服务一个）：
  按 pid 合并成一条再交出去，否则"半个进程在播"会被算成两条不同结论。

所有异常一律吞掉返回空元组：音乐识别是锦上添花，绝不能因为第三方播放器或
音频设备把桌宠带崩。本模块不发起网络请求、不碰音频流、不写任何文件。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

#: ``IAudioSessionControl2.GetState`` 的三态。未知值按 inactive 处理：
#: 宁可少报"在播"，也不要凭一个认不出的状态码让桌宠唱起来。
_STATE_NAMES = {1: "active", 0: "inactive", 2: "expired"}

#: 合并同一 pid 多会话时的状态优先级（越小越强）。Active 一定赢；其余按
#: inactive 优于 expired —— expired 是已经死掉、再也不会出声的那条。
_STATE_RANK = {"active": 0, "inactive": 1, "expired": 2}

#: 端点重建的节流窗口（秒）。切耳机、插拔 DAC 会换掉 default endpoint，旧 manager
#: 上永远枚举不到会话，只能重建；但"当前没有任何音频会话"同样是 0 条，所以重建
#: 最多每 30 秒一次，绝不每拍重建。
_REBUILD_INTERVAL = 30.0


@dataclass(frozen=True, slots=True)
class AudioSession:
    """一条（按 pid 合并后的）音频会话事实。

    ``peak`` 是会话的瞬时峰值（0.0..1.0）：静音的播放器仍有会话，但峰值为 0，
    所以它和 ``muted`` 一起构成"没在出声"的证据。
    """

    pid: int
    exe: str
    state: str
    muted: bool
    peak: float


_lock = threading.Lock()
#: 缓存的 ``IAudioSessionManager2`` 及建它的线程 ident（COM 接口是线程亲和的）。
_manager = None
_manager_thread: int | None = None
#: 下一次允许因"枚举失败 / 0 条会话"而丢弃缓存端点的时刻。
_next_invalidate_at = 0.0
#: 建端点连续失败后的冷却：避免设备被独占时每拍都去 Activate 一次。
_build_allowed_at = 0.0
#: 本线程是否由我们 ``CoInitialize`` 过（未初始化就 CoUninitialize 会出错）。
_local = threading.local()
_available: bool | None = None


def available() -> bool:
    """WASAPI 会话枚举在本机是否可用（Windows + pycaw 装得上）。

    结论缓存一次：它不会在进程生命周期里改变，而调用方会每秒问一次。
    """
    global _available
    if _available is not None:
        return _available
    ok = sys.platform == "win32"
    if ok:
        try:
            import pycaw.utils  # noqa: F401  # 只为探测依赖是否装得上
        except Exception:
            ok = False
    _available = ok
    return ok


def snapshot() -> tuple[AudioSession, ...]:
    """采样一次逐进程音频会话；读不到就是空元组，绝不抛。

    调用方把空元组理解为"没有证据"，而不是"没有在放声音"——两者在决策上
    不同（前者退回 SMTC 的结论，后者是否决）。
    """
    try:
        rows = _enumerate_rows()
    except Exception:
        _note_dead_endpoint()
        return ()
    if not rows:
        # 可能是"真的没有程序在出声"，也可能是设备切换后旧端点死了。两种都
        # 只丢掉缓存端点并交给 30 秒节流，不当错误。
        _note_dead_endpoint()
    try:
        return _merge_rows(rows)
    except Exception:
        return ()


def reset() -> None:
    """丢掉缓存的端点与两个节流窗口（设备切换排查、测试换替身时用）。"""
    global _manager, _manager_thread, _next_invalidate_at, _build_allowed_at
    with _lock:
        _manager = None
        _manager_thread = None
        _next_invalidate_at = 0.0
        _build_allowed_at = 0.0


def close() -> None:
    """线程退出前调用：放掉缓存接口，并在本线程配对 ``CoUninitialize``。

    COM 的 apartment 引用计数是线程绑定的，不配对会让线程的 apartment 一直挂着；
    接口指针也必须先丢，否则释放发生在 COM 关掉之后。
    """
    global _manager, _manager_thread
    with _lock:
        if _manager_thread == threading.get_ident():
            _manager = None
            _manager_thread = None
    if getattr(_local, "initialized", False):
        _local.initialized = False
        try:
            import comtypes

            comtypes.CoUninitialize()
        except Exception:
            pass


# ---------------------------------------------------------------- 内部：COM 与枚举


def _co_initialize() -> None:
    """在本线程初始化 COM（幂等，按线程记账）。

    comtypes/pycaw 自己不做这件事，未初始化的线程上枚举会直接抛 COM 错误。
    """
    if getattr(_local, "initialized", False):
        return
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        # 线程已被别处以别的 apartment 模型初始化过时这里会失败；那种情况下 COM
        # 本来就能用，继续往下走，只是不配对 CoUninitialize。
        _local.initialized = False
        return
    _local.initialized = True


def _note_dead_endpoint() -> None:
    """丢掉缓存的端点，并按 30 秒节流（多一次重建都不行）。"""
    global _manager, _manager_thread, _next_invalidate_at
    with _lock:
        now = time.monotonic()
        if now < _next_invalidate_at:
            return
        _next_invalidate_at = now + _REBUILD_INTERVAL
        _manager = None
        _manager_thread = None


def _session_manager():
    """缓存的 ``IAudioSessionManager2``；拿不到返回 ``None``。

    只有这里会付 ``GetSpeakers()`` 那次约 24ms 的 ``Activate`` 成本。
    """
    global _manager, _manager_thread, _build_allowed_at
    ident = threading.get_ident()
    with _lock:
        if _manager is not None and _manager_thread == ident:
            return _manager
        now = time.monotonic()
        # 冷却只拦"手上什么都没有"的情形；手里有另一个线程的接口时立刻为当前
        # 线程重建一次（那是线程亲和，不是端点失效）。
        if _manager is None and now < _build_allowed_at:
            return None
        if _manager is not None:
            _manager = None
            _manager_thread = None
        try:
            from pycaw.utils import AudioUtilities

            manager = AudioUtilities.GetSpeakers().AudioSessionManager
        except Exception:
            manager = None
        if manager is None:
            _build_allowed_at = now + _REBUILD_INTERVAL
            return None
        _manager = manager
        _manager_thread = ident
        _build_allowed_at = 0.0
        return manager


def _enumerate_rows() -> list[tuple[int, int, bool, float, str]]:
    """枚举一次原始会话行 ``(pid, state, muted, peak, exe)``。

    这是**刻意的测试接缝**：替换掉它就能覆盖后面的合并 / 过滤 / 异常吞掉，
    不需要在 CI 上有 COM、音频设备或 Windows。``state`` 是未映射的原始整数。
    """
    _co_initialize()
    from pycaw.api.endpointvolume import IAudioMeterInformation
    from pycaw.utils import AudioSession as _PycawSession
    from pycaw.utils import IAudioSessionControl2

    manager = _session_manager()
    if manager is None:
        return []
    rows: list[tuple[int, int, bool, float, str]] = []
    enumerator = manager.GetSessionEnumerator()
    for index in range(enumerator.GetCount()):
        try:
            control = enumerator.GetSession(index)
            if control is None:
                continue
            control2 = control.QueryInterface(IAudioSessionControl2)
            if control2 is None:
                continue
            session = _PycawSession(control2)
            pid = int(session.ProcessId)
        except Exception:
            # 会话在枚举与读取之间结束很常见（Expired），跳过这一条即可。
            continue
        try:
            state = int(session.State)
        except Exception:
            state = 0
        muted = False
        try:
            muted = bool(session.SimpleAudioVolume.GetMute())
        except Exception:
            pass
        peak = 0.0
        try:
            peak = float(control2.QueryInterface(IAudioMeterInformation).GetPeakValue())
        except Exception:
            pass
        rows.append((pid, state, muted, peak, _session_exe(session)))
    return rows


def _session_exe(session) -> str:
    """会话所属进程的小写可执行名；拿不到（权限/已退出）返回空串。"""
    try:
        process = session.Process
    except Exception:
        return ""
    if process is None:
        return ""
    try:
        return str(process.name() or "").strip().lower()
    except Exception:
        return ""


def _merge_rows(rows) -> tuple[AudioSession, ...]:
    """原始行 → 按 pid 合并后的会话快照（纯函数，测试的主战场）。

    合并口径：任一会话 Active 即 ``active``；峰值取最大（"有一点声音"这个事实
    不能被另一条静默会话盖掉）；``muted`` 取"所有会话都静音"（播放器主窗口没静音、
    只有一个辅助会话静音时，声音照样出得来）。
    """
    merged: dict[int, dict] = {}
    for row in rows:
        pid, state_raw, muted, peak, exe = row
        pid = int(pid)
        if pid <= 0:
            # pid 0 是 Windows 自己的"系统声音"会话，不是应用。
            continue
        state = _STATE_NAMES.get(int(state_raw), "inactive")
        try:
            # GetPeakValue 不保证落在 1.0 以内（实测浏览器会话读到 1.1989：混音
            # 放大后确实会溢出），所以在这里收口，免得调用方要各自防一手。
            value = max(0.0, min(1.0, float(peak)))
        except Exception:
            value = 0.0
        entry = merged.get(pid)
        if entry is None:
            merged[pid] = {
                "state": state,
                "muted": bool(muted),
                "peak": value,
                "exe": str(exe or "").strip().lower(),
            }
            continue
        if _STATE_RANK[state] < _STATE_RANK[entry["state"]]:
            entry["state"] = state
        entry["muted"] = bool(entry["muted"]) and bool(muted)
        entry["peak"] = max(entry["peak"], value)
        if not entry["exe"]:
            entry["exe"] = str(exe or "").strip().lower()
    return tuple(
        AudioSession(
            pid=pid,
            exe=entry["exe"],
            state=entry["state"],
            muted=entry["muted"],
            peak=entry["peak"],
        )
        for pid, entry in merged.items()
    )
