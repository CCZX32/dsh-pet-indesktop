# -*- coding: utf-8 -*-
"""有界的 worker 启动诊断：stderr 不是安全的日志也不是安全的展示载荷。

移植自 DLC 分支 `features/screen_understanding/host/worker_diagnostics.py`。
两件事：

* :func:`safe_diagnostic` —— 把 supervisor 的原始诊断字段**白名单过滤**成一小
  组可展示的键值（退出码/代数/重启次数/固定原因码/缺失模块名）。子进程 stderr
  可能含路径、token 或第三方 traceback，绝不整段透传；
* :func:`failure_hint` —— 把固定原因码翻译成一句给人看的中文。

零 Qt、零配置依赖：设置页与子进程两侧都能导入。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

#: 允许透传的固定原因/错误码（其余一律丢弃）。
_SAFE_CODES = frozenset(
    {
        "worker_runtime_boundary",
        "worker_runtime_unavailable",
        "worker_package_invalid",
        "worker_authorization_unavailable",
        "worker_launch_failed",
        "handshake timeout",
        "heartbeat timeout",
        "worker exited",
        "external launch validation failed",
        "request_timeout",
        "worker_stopped",
        "worker_crashed",
        "worker_unavailable",
        "restart_scheduled",
    }
)

_MODULE_NAME = re.compile(r"No module named ['\"]([a-zA-Z_][a-zA-Z0-9_.]{0,127})['\"]")


def safe_diagnostic(detail) -> dict:
    """白名单过滤 supervisor 诊断：只留整数字段、固定原因码与缺失模块名。"""
    raw = detail if isinstance(detail, Mapping) else {}
    result = {k: raw[k] for k in ("exit_code", "generation", "restart_count", "pending") if type(raw.get(k)) is int}
    for key in ("reason", "code"):
        if raw.get(key) in _SAFE_CODES:
            result[key] = raw[key]
    match = _MODULE_NAME.search(str(raw.get("line", ""))[:2000])
    if match:
        result["missing_module"] = match.group(1)
    if isinstance(raw.get("missing_module"), str) and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.]{0,127}", raw["missing_module"]):
        result["missing_module"] = raw["missing_module"]
    return result


def failure_hint(detail: Mapping | None) -> str:
    """固定原因码 → 一句人话（本拓扑没有功能包，「安装新版识屏功能包」类话术已改写）。"""
    detail = detail if isinstance(detail, Mapping) else {}
    code = detail.get("code")
    if code == "worker_runtime_boundary":
        return "识屏 Worker 的运行目录不符合当前安装布局；请重装或更新本程序后重试。"
    if code == "worker_runtime_unavailable":
        return "识屏 Worker 的运行目录不可用；请检查程序数据目录是否存在及访问权限后重试。"
    if code == "worker_authorization_unavailable":
        return "识屏 Worker 当前不可执行；请检查是否被安全软件拦截，稍后重试。"
    if code == "worker_launch_failed":
        return "识屏 Worker 未能启动；请检查程序文件及安全软件拦截后重试。"
    if code == "worker_unavailable":
        return "识屏 Worker 已停止，本次识屏未完成；未自动改用进程内执行，请重试或改用进程内模式。"
    if detail.get("missing_module"):
        return "识屏 Worker 缺少模块 " + str(detail["missing_module"]) + "；请更新到新版本后重试。"
    if detail.get("reason") == "heartbeat timeout":
        return "识屏 Worker 响应超时；请稍后重试，仍失败时检查系统负载与安全软件拦截。"
    if detail.get("reason") == "handshake timeout":
        return "识屏 Worker 握手超时；请检查安全软件拦截，稍后重试。"
    if code == "worker_package_invalid" or detail.get("reason") == "external launch validation failed":
        return "识屏 Worker 的身份校验失败；请重新安装本程序。"
    return "识屏 Worker 启动或运行失败；请重试，仍失败时重装本程序。"


__all__ = ["failure_hint", "safe_diagnostic"]
