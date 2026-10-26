# -*- coding: utf-8 -*-
"""游戏帧率的采集权限（零 Qt）：Performance Log Users 组成员判定与一次性授权。

PresentMon 的 ETW 会话只对管理员或 ``Performance Log Users``（内置组，SID
``S-1-5-32-559``）成员开放。本模块只做两件事：

1. :func:`check` —— **只读**判定，进程内 Win32 API（``CheckTokenMembership``），
   不起子进程、不卡 GUI。状态分四种：已生效 / 已加入待重新登录 / 未加入 /
   无法判定（非 Windows 或 API 不可用）。
2. :func:`request_access` —— **只在用户显式调用时**弹一次系统 UAC，以管理员身份
   ``Add-LocalGroupMember -SID S-1-5-32-559``。用户在 UAC 框点"否"是正常结果
   （``cancelled``），不是错误。本模块**不自动提权、不常驻、不装服务**。

两条实现纪律：

- **按 SID 定位组**，不按组名（组名随系统语言变化）。
- **提权只用系统 PowerShell 的绝对路径**（``%SystemRoot%\\System32\\
  WindowsPowerShell\\v1.0\\powershell.exe``），不走 PATH 搜索；脚本用
  ``-EncodedCommand``（UTF-16LE）传递，中文与引号都不会被 5.1 的 ANSI 解析坑到。
  ``Add-LocalGroupMember`` 来自 ``Microsoft.PowerShell.LocalAccounts``：Windows
  自带的 5.1 **一定有**这个模块，PowerShell 7 是否自带随版本/安装方式而变（本机
  7.6.6 能解析到，但不能假定每个用户都有），所以产品路径固定用系统自带的 5.1。
- 提权脚本自带期限：超过等待上限后才被批准的 UAC 不再执行加组；等待超时报
  "结果未知"，以重新查询 :func:`check` 为准。
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Performance Log Users 的 SID（组名随系统语言变化，SID 不变）。
PERF_LOG_USERS_SID = "S-1-5-32-559"

STATUS_ACTIVE = "active"  # 当前令牌已含该组：普通权限即可采集
STATUS_PENDING = "pending_relogon"  # 账户已加入，需注销/重新登录后生效
STATUS_MISSING = "missing"  # 未加入
STATUS_UNSUPPORTED = "unsupported"  # 非 Windows 或无法判定

#: 用户取消 UAC 的原生错误码 / 脚本退出码（Win32 ``ERROR_CANCELLED``）。
EXIT_CANCELLED = 1223
#: 管理员脚本的退出码：加组失败 / 已过期未执行。
EXIT_ADD_FAILED = 2
EXIT_EXPIRED = 3
#: 等管理员进程结束的上限（秒）：UAC 框可能挂着等用户，给足但有界。
GRANT_TIMEOUT_S = 300.0
#: 脚本执行期限比等待上限早这么多秒：超时后才批准的 UAC 不再加组。
DEADLINE_MARGIN_S = 10.0

#: ``ShellExecuteExW`` 参数。
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SW_HIDE = 0
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258

#: 只含数字与连字符的 SID：进脚本前必须过这道校验（脚本里不出现用户可控文本）。
_SID_RE = re.compile(r"S-1-\d+(?:-\d+)+")

#: 本进程是否已成功加入过（跨设置窗口存续；作为成员列表读不到时的兜底判据）。
_state = {"granted": False}


@dataclass(frozen=True)
class GrantResult:
    """一次授权请求的结果。

    ``outcome``：``ok`` / ``cancelled`` / ``error`` / ``unknown``（等待超时，
    以重新查询 :func:`check` 为准）/ ``unsupported``。
    """

    outcome: str
    detail: str = ""


def is_supported() -> bool:
    """这条权限链路只在 Windows 上存在。"""
    return sys.platform == "win32"


def is_valid_sid(sid: str) -> bool:
    return bool(sid) and _SID_RE.fullmatch(str(sid)) is not None


def mark_granted() -> None:
    _state["granted"] = True


def granted_this_process() -> bool:
    return bool(_state["granted"])


# ---------------------------------------------------------------- 令牌（进程内 API）
def _advapi():
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    adv.GetTokenInformation.restype = wintypes.BOOL
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    adv.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    adv.ConvertStringSidToSidW.restype = wintypes.BOOL
    adv.CheckTokenMembership.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
    ]
    adv.CheckTokenMembership.restype = wintypes.BOOL
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    return adv, k32, wintypes


def current_user_sid() -> str:
    """当前进程令牌的用户 SID（字符串形式）；读不到返回空串。

    取令牌而不是 ``USERNAME`` 环境变量：后者可被启动器改写。
    """
    if not is_supported():
        return ""
    try:
        adv, k32, wt = _advapi()
        token = wt.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return ""
        try:
            need = wt.DWORD(0)
            adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(need))  # TokenUser
            if not need.value:
                return ""
            buf = ctypes.create_string_buffer(need.value)
            if not adv.GetTokenInformation(token, 1, buf, need, ctypes.byref(need)):
                return ""
            psid = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_USER.User.Sid
            text = wt.LPWSTR()
            if not adv.ConvertSidToStringSidW(psid, ctypes.byref(text)):
                return ""
            try:
                sid = text.value or ""
            finally:
                k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            k32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return ""
    return sid if is_valid_sid(sid) else ""


def token_has_group() -> bool | None:
    """当前令牌是否含**已启用**的该组（``CheckTokenMembership``）；判不出返回 ``None``。

    只认令牌里已启用的组（deny-only 不算）；这是"现在就能采集"的唯一判据。
    """
    if not is_supported():
        return None
    try:
        adv, k32, wt = _advapi()
        psid = ctypes.c_void_p()
        if not adv.ConvertStringSidToSidW(PERF_LOG_USERS_SID, ctypes.byref(psid)):
            return None
        try:
            member = wt.BOOL(0)
            if not adv.CheckTokenMembership(None, psid, ctypes.byref(member)):
                return None
            return bool(member.value)
        finally:
            k32.LocalFree(psid)
    except (OSError, AttributeError, ValueError):
        return None


def account_in_group(user_sid: str | None = None) -> bool | None:
    """当前账户是否**已在**该组的成员列表里（不看令牌）；判不出返回 ``None``。

    这是跨进程的真值：设置页可能是独立进程，关掉重开后靠它区分
    "已加入待重新登录" 与 "未授权"。只看直接成员（本模块只做直接加入）。
    """
    if not is_supported():
        return None
    sid = current_user_sid() if user_sid is None else user_sid
    if not is_valid_sid(sid):
        return None
    try:
        from ctypes import wintypes

        adv, k32, _ = _advapi()
        net = ctypes.WinDLL("netapi32", use_last_error=True)
        group_sid = ctypes.c_void_p()
        if not adv.ConvertStringSidToSidW(PERF_LOG_USERS_SID, ctypes.byref(group_sid)):
            return None
        try:
            # 组名随系统语言变化：由 SID 反查，绝不硬编码 "Performance Log Users"。
            name = ctypes.create_unicode_buffer(256)
            dom = ctypes.create_unicode_buffer(256)
            n_name, n_dom = wintypes.DWORD(256), wintypes.DWORD(256)
            use = wintypes.DWORD()
            adv.LookupAccountSidW.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_void_p,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
            ]
            adv.LookupAccountSidW.restype = wintypes.BOOL
            if not adv.LookupAccountSidW(
                None,
                group_sid,
                name,
                ctypes.byref(n_name),
                dom,
                ctypes.byref(n_dom),
                ctypes.byref(use),
            ):
                return None
        finally:
            k32.LocalFree(group_sid)
        net.NetLocalGroupGetMembers.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        net.NetLocalGroupGetMembers.restype = wintypes.DWORD
        net.NetApiBufferFree.argtypes = [ctypes.c_void_p]
        resume = ctypes.c_size_t(0)
        found = False
        while True:
            buf = ctypes.c_void_p()
            read, total = wintypes.DWORD(), wintypes.DWORD()
            # level 0 = LOCALGROUP_MEMBERS_INFO_0 { PSID }；ERROR_MORE_DATA(234) 时续枚举。
            rc = net.NetLocalGroupGetMembers(
                None,
                name.value,
                0,
                ctypes.byref(buf),
                0xFFFFFFFF,
                ctypes.byref(read),
                ctypes.byref(total),
                ctypes.byref(resume),
            )
            try:
                if rc not in (0, 234):
                    return None
                ptrs = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))
                for index in range(read.value if buf.value and not found else 0):
                    text = wintypes.LPWSTR()
                    if adv.ConvertSidToStringSidW(ptrs[index], ctypes.byref(text)):
                        try:
                            if (text.value or "").upper() == sid.upper():
                                found = True
                                break
                        finally:
                            k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            finally:
                if buf.value:
                    net.NetApiBufferFree(buf)
            if rc == 0:
                break
        return found
    except (OSError, AttributeError, ValueError):
        return None


def check(
    *,
    token_member: Callable[[], bool | None] | None = None,
    account_member: Callable[[], bool | None] | None = None,
) -> str:
    """当前权限状态（进程内 API，不起子进程）。

    令牌含已启用的组 → ``active``；否则以**账户实际组成员关系**为准（能区分
    "已加入待重新登录" 与 "未加入"）；两者都判不出 → ``unsupported``。
    两个探测函数可注入（测试用），默认是真实 Win32 实现。

    不是热路径：账户成员要枚举本地组（系统调用），按设置页/卡片刷新的节奏调用，
    不要按帧调。
    """
    if not is_supported():
        return STATUS_UNSUPPORTED
    member_check = token_has_group if token_member is None else token_member
    member = member_check()
    if member is None:
        return STATUS_UNSUPPORTED
    if member:
        return STATUS_ACTIVE
    listed_check = account_in_group if account_member is None else account_member
    listed = listed_check()
    if listed is not None:
        return STATUS_PENDING if listed else STATUS_MISSING
    return STATUS_PENDING if granted_this_process() else STATUS_MISSING


# ---------------------------------------------------------------- 系统 PowerShell
def system_powershell() -> str:
    """系统目录下 Windows PowerShell 的绝对路径（不走搜索路径）；取不到返回空串。

    刻意不用 PowerShell 7：``Microsoft.PowerShell.LocalAccounts``（提供
    ``Add-LocalGroupMember``）在 Windows 自带的 5.1 里一定有，7 是否自带随版本与
    安装方式而变；产品路径不能赌用户装的是哪一种。绝对路径同时避开 PATH 劫持。
    """
    if not is_supported():
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260)
    except (OSError, AttributeError):
        return ""
    if not n or n >= 260:
        return ""
    path = os.path.join(buf.value, "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.isfile(path) else ""


def _ps_quote(value: str) -> str:
    """PowerShell 单引号字面量（只接程序自产、已校验的路径/SID）。"""
    if any(ch in value for ch in "'\u2018\u2019\u201a\u201b"):
        raise ValueError("值里不允许出现引号")
    return "'" + value + "'"


def _encode(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def build_grant_command(
    user_sid: str, *, powershell: str, deadline_unix: int
) -> list[str]:
    """管理员进程里要执行的命令（``-EncodedCommand``，脚本里不出现用户可控文本）。

    脚本事务：过期不执行 → 已是成员视为成功（幂等）→ 其它失败退出 2。
    """
    if not is_valid_sid(user_sid):
        raise ValueError("SID 不合法")
    if not str(powershell or "").strip():
        raise ValueError("PowerShell 路径不能为空")
    script = (
        "$ErrorActionPreference='Stop';"
        f"if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -gt {int(deadline_unix)})"
        f"{{exit {EXIT_EXPIRED}}};"
        "try{"
        f"Add-LocalGroupMember -SID {_ps_quote(PERF_LOG_USERS_SID)} "
        f"-Member {_ps_quote(user_sid)};exit 0"
        "}catch{"
        f"if($_.FullyQualifiedErrorId -like 'MemberExists*'){{exit 0}};"
        f"exit {EXIT_ADD_FAILED}"
        "}"
    )
    return [
        str(powershell),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        _encode(script),
    ]


def map_exit_code(code: int) -> GrantResult:
    """管理员进程退出码 → :class:`GrantResult`（幂等成功也算 ``ok``）。"""
    if code == 0:
        mark_granted()
        return GrantResult("ok", "已加入 Performance Log Users，注销或重启电脑后生效")
    if code == EXIT_CANCELLED:
        return GrantResult("cancelled", "已取消授权")
    if code == EXIT_EXPIRED:
        return GrantResult("error", "授权请求已过期，请重试")
    if code == EXIT_ADD_FAILED:
        return GrantResult("error", "加入 Performance Log Users 失败（退出码 2）")
    return GrantResult("error", f"授权失败（退出码 {int(code)}）")


# ---------------------------------------------------------------- 一次性授权（UAC）
class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _shell_execute_runas(executable: str, parameters: str) -> tuple[int, int]:
    """以管理员身份启动一次（``ShellExecuteExW`` + ``runas``）。

    返回 ``(进程句柄, 错误码)``：成功时错误码为 0；用户点"否"时错误码是
    :data:`EXIT_CANCELLED`。句柄由调用方关闭。
    """
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = ctypes.c_int
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = _SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return 0, int(ctypes.get_last_error())
    return int(info.hProcess or 0), 0


def _wait_and_map(handle: int) -> GrantResult:
    """等管理员进程结束并映射退出码；超时返回 ``unknown``（以重新查询为准）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.WaitForSingleObject.restype = ctypes.c_ulong
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.GetExitCodeProcess.restype = ctypes.c_int
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    try:
        waited = int(k32.WaitForSingleObject(ctypes.c_void_p(handle), int(GRANT_TIMEOUT_S * 1000)))
        if waited == _WAIT_TIMEOUT:
            return GrantResult(
                "unknown",
                "等待授权超时：超时后才批准的请求不会执行。若已在超时前批准，"
                "注销或重启电脑后生效；也可以重新查询权限状态",
            )
        if waited != _WAIT_OBJECT_0:
            return GrantResult("error", f"等待授权进程失败（等待码 {waited}）")
        code = ctypes.c_ulong(0)
        if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
            return GrantResult("error", "读不到授权进程的退出码")
        return map_exit_code(int(code.value))
    finally:
        try:
            k32.CloseHandle(ctypes.c_void_p(handle))
        except (OSError, AttributeError):
            pass


def request_access(
    *,
    user_sid: str | None = None,
    powershell: str | None = None,
    now: Callable[[], float] = time.time,
) -> GrantResult:
    """弹**一次**系统 UAC，把当前账户加入 Performance Log Users。

    **只在用户显式调用时执行**（设置页的"授权…"按钮）；本函数不自动重试、不提权
    常驻。调用方应放到后台线程：UAC 决策由系统弹窗同步阻塞等待（用户不答就一直等），
    批准后等管理员进程至多 :data:`GRANT_TIMEOUT_S` 秒。用户在 UAC 框点"否" →
    ``cancelled``（不是错误）。
    """
    if not is_supported():
        return GrantResult("unsupported", "仅 Windows 需要此授权")
    sid = current_user_sid() if user_sid is None else user_sid
    if not is_valid_sid(sid):
        return GrantResult("error", "无法确定当前账户")
    exe = system_powershell() if powershell is None else powershell
    if not exe:
        return GrantResult("error", "找不到系统 PowerShell")
    deadline = int(now() + GRANT_TIMEOUT_S - DEADLINE_MARGIN_S)
    try:
        argv = build_grant_command(sid, powershell=exe, deadline_unix=deadline)
    except ValueError as exc:
        return GrantResult("error", f"授权参数不安全：{exc}")
    try:
        handle, error = _shell_execute_runas(argv[0], subprocess.list2cmdline(argv[1:]))
    except (OSError, AttributeError) as exc:
        return GrantResult("error", f"无法拉起系统授权窗口：{exc}")
    if error == EXIT_CANCELLED:
        return GrantResult("cancelled", "已取消授权")
    if error or not handle:
        return GrantResult("error", f"无法拉起系统授权窗口（错误码 {error}）")
    return _wait_and_map(handle)
