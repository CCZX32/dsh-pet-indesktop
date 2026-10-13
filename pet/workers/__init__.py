# -*- coding: utf-8 -*-
"""Worker（子进程）框架：JSONL 协议 / 启动租约 / QProcess 监督。

依赖方向是本包的硬约束：子进程侧只需要 :mod:`pet.workers.protocol`
（以及 :mod:`pet.workers.launch` 的 Qt-free 部分），导入本包**不得**把 Qt 拉进
子进程。因此带 Qt 的 :class:`~pet.workers.supervisor.WorkerSupervisor` 与
:mod:`pet.workers.launch` 都只经模块级 ``__getattr__`` 惰性暴露，本文件顶层
除了 :mod:`pet.workers.protocol` 之外不再 import 任何子模块。

为什么连 :mod:`~pet.workers.launch` 也要惰性（S3 改动）：子进程的启动路径是
``python -m pet --worker proactive-screen`` → ``pet.workers.worker_entry``，这会
**先执行本包 ``__init__``**。顶层导入 ``.launch`` 会连带 ``pet.feature_state_io``
（S2 实测约 5 ms / 窗口内占比可观），而只想导协议的 worker 一分钱都不该付。
既有 ``from pet.workers import WorkerLaunch`` 用法经 PEP 562 的 ``__getattr__``
照旧可用。

S2 建框架（无生产调用方），S3 落下第一个真 worker（主动识屏）与
``pet/__main__.py`` 的 ``--worker`` 白名单分流。
"""

from __future__ import annotations

from .protocol import (
    MAX_MESSAGE_BYTES,
    MESSAGE_TYPES,
    PROTOCOL,
    WorkerMessage,
    WorkerProtocolError,
    build_message,
    decode_message,
    encode_message,
)

#: 惰性导出的名字 → 定义它们的子模块（``__getattr__`` 按需 import）。
_LAZY_EXPORTS = {
    "HANDOFF_TOKEN_ENV": ".launch",
    "LaunchLease": ".launch",
    "WorkerLaunch": ".launch",
    "WorkerLaunchRejected": ".launch",
    "isolated_worker_environment": ".launch",
    "lease_worker_launch": ".launch",
    "WorkerSupervisor": ".supervisor",
}

__all__ = [
    "HANDOFF_TOKEN_ENV",
    "MAX_MESSAGE_BYTES",
    "MESSAGE_TYPES",
    "PROTOCOL",
    "LaunchLease",
    "WorkerLaunch",
    "WorkerLaunchRejected",
    "WorkerMessage",
    "WorkerProtocolError",
    "WorkerSupervisor",
    "build_message",
    "decode_message",
    "encode_message",
    "isolated_worker_environment",
    "lease_worker_launch",
]


def __getattr__(name: str):
    """Qt-bearing / heavier exports stay lazy so a child import graph pays little."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value  # 缓存：第二次访问不再走 import 机制
    return value
