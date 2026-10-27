"""播放器窗口标题源：看得见不注册 SMTC 的播放器（无 Qt、无 pywin32）。

foobar2000、AIMP、Winamp 这类播放器不上报 Windows 媒体会话，SMTC 里根本没有它们，
"当前播放"就只能空着。但它们有个共同习惯：把当前曲目写进**主窗口标题**
（``歌名 - 歌手 [foobar2000]``）。本模块只负责一件事——按可执行名挑出这些进程的
**主窗口**，把 ``pid / 可执行名 / 标题`` 原样交出去；标题怎么解析归调用方。

三条实测口径：

- **只收无属主的可见顶层窗口**：播放器的"参数选项""首选项"对话框是主窗口的从属
  窗口（``GetWindow(hwnd, GW_OWNER) != 0``），标题里往往只有设置项名，会把"当前
  播放"污染成"参数选项"；皮肤/独立窗口又会给同一进程开出第二条顶层窗口。所以先滤
  从属窗口与空标题，同一 pid 再只留标题最长的那条（越长越可能是"歌名 - 歌手"而不是
  播放器名）。
- **一整趟枚举很便宜**：本机 10 个候选顶层窗口实测 0.38ms（可见性 + 属主 +
  ``GetWindowTextW``），连进程名过滤的整次采样 0.58ms；耗时随窗口数线性增长
  （320 个窗口的口径约 1.4ms）。每秒一次完全付得起。但**进程名解析不能每窗口来
  一次**：psutil 查进程名是系统调用，所以按 pid 在一次采样内缓存，同一 pid 只查一次。
- **不用 pywin32**：本仓库没有它的运行时依赖，``ctypes`` 显式声明签名就够；而在
  64 位下必须显式声明 ``HWND`` 的 restype——默认 ``c_int`` 会把句柄高位截断。

非 Windows、psutil 缺失、以及任何异常一律返回空元组：窗口标题只是锦上添花，
不能因为第三方播放器影响桌宠。本模块不写文件、不发起网络请求、不改任何窗口状态。
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from types import SimpleNamespace

#: ``GetWindow`` 的 ``GW_OWNER``：非 0 表示这是别人的从属窗口（对话框等）。
_GW_OWNER = 4

#: 一次采样最多回几条窗口：调用方按播放器取，一个播放器一条就够。
_DEFAULT_LIMIT = 8


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """一条候选窗口：哪个进程（pid + 小写可执行名）的哪个标题。"""

    pid: int
    exe: str
    title: str


_available: bool | None = None
_win32_api = None


def available() -> bool:
    """窗口标题源在本机是否可用（Windows + psutil）。

    结论缓存一次：它不会在进程生命周期里改变，而调用方会每秒问一次。
    """
    global _available
    if _available is not None:
        return _available
    ok = sys.platform == "win32" and _psutil() is not None
    _available = ok
    return ok


def snapshot(wanted_exes: frozenset[str], *, limit: int = _DEFAULT_LIMIT) -> tuple[WindowInfo, ...]:
    """这些可执行名的**主窗口**标题，最多 ``limit`` 条。

    同一 pid 只保留标题最长的一条；解析不到进程名的窗口直接跳过——认不出是哪个
    程序就不该猜。顺序沿用 ``EnumWindows`` 的 z 序（最上层在前），所以截断时先丢
    被压在下面的窗口。
    """
    wanted = frozenset(str(exe).strip().lower() for exe in wanted_exes if str(exe).strip())
    if not wanted or limit <= 0:
        return ()
    try:
        rows = _enumerate_rows()
    except Exception:
        return ()
    if not rows:
        return ()
    # 进程名解析按 pid 在一次采样内缓存：同 pid 的多条窗口只查一次进程表。
    exe_by_pid: dict[int, str] = {}
    best: dict[int, WindowInfo] = {}
    try:
        for pid, title in rows:
            pid = int(pid)
            if pid <= 0:
                continue
            if pid not in exe_by_pid:
                exe_by_pid[pid] = str(_exe_for_pid(pid) or "").strip().lower()
            exe = exe_by_pid[pid]
            if not exe or exe not in wanted:
                continue
            text = str(title or "").strip()
            if not text:
                continue
            previous = best.get(pid)
            if previous is None or len(text) > len(previous.title):
                best[pid] = WindowInfo(pid=pid, exe=exe, title=text)
    except Exception:
        return ()
    return tuple(list(best.values())[:limit])


# ---------------------------------------------------------------- 内部：Win32 枚举


def _psutil():
    """psutil 模块；没装返回 ``None``（本模块唯一的可选依赖）。"""
    try:
        import psutil
    except Exception:
        return None
    return psutil


def _exe_for_pid(pid: int) -> str:
    """pid → 小写可执行名（含 ``.exe``）；进程已退出或没权限返回空串。

    刻意不缓存到跨采样：pid 会被复用，一个过期映射会把别的程序当成播放器。
    一次采样内的缓存在 :func:`snapshot` 里做。
    """
    psutil = _psutil()
    if psutil is None:
        return ""
    try:
        return str(psutil.Process(int(pid)).name() or "").strip().lower()
    except Exception:
        return ""


def _win32():
    """绑好原型的 user32 函数集合（进程内建一次）；建不出来返回 ``None``。

    用私有的 ``WinDLL`` 实例而不是共享的 ``ctypes.windll.user32``：原型挂在函数
    对象上，共享实例意味着别的模块设的 argtypes 会覆盖我们的（反之亦然）。
    """
    global _win32_api
    if _win32_api is not None:
        return _win32_api
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # 显式声明签名：默认 restype=c_int 会在 64 位下把 HWND 截断成 32 位。
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        _win32_api = SimpleNamespace(user32=user32, callback=callback, DWORD=wintypes.DWORD)
    except Exception:
        return None
    return _win32_api


def _enumerate_rows() -> list[tuple[int, str]]:
    """枚举候选窗口 → ``[(pid, title), ...]``（z 序，最上层在前）。

    这里取的是**所有**无属主可见顶层窗口的标题，还不看进程名：要按进程名先过滤
    就得先扫一遍进程表，而那正是这条路径要避免的开销（整趟枚举本来只要 ~1.4ms）。
    进程名过滤在 :func:`snapshot` 里按 pid 缓存着做。

    这是**刻意的测试接缝**：替换掉它，后面的进程名过滤 / 同 pid 取最长 / 条数上限
    就能在没有桌面的机器上（Linux CI）完整验证。
    """
    if not available():
        return []
    api = _win32()
    if api is None:
        return []
    user32 = api.user32
    rows: list[tuple[int, str]] = []

    def _visit(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, _GW_OWNER):
                return True
            pid = api.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            text = str(buffer.value or "").strip()
            if text:
                rows.append((int(pid.value), text))
        except Exception:
            # 单个窗口读失败不该废掉整趟枚举。
            pass
        return True

    try:
        user32.EnumWindows(api.callback(_visit), 0)
    except Exception:
        return []
    return rows
