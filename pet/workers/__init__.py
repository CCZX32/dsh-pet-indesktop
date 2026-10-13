# -*- coding: utf-8 -*-
"""Worker（子进程）框架：JSONL 协议 / 启动租约 / QProcess 监督。

依赖方向是本包的硬约束：子进程侧只需要 :mod:`pet.workers.protocol`
（以及 :mod:`pet.workers.launch` 的 Qt-free 部分），导入本包**不得**把 Qt 拉进
子进程。因此带 Qt 的 :class:`~pet.workers.supervisor.WorkerSupervisor` 只经
模块级 ``__getattr__`` 惰性暴露，本文件顶层绝不 import 它。

本片（S2）只建框架：没有任何生产调用方，主动识屏 worker 在 S3 接入。
"""

from __future__ import annotations

from .launch import (
    HANDOFF_TOKEN_ENV,
    LaunchLease,
    WorkerLaunch,
    WorkerLaunchRejected,
    isolated_worker_environment,
    lease_worker_launch,
)
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
    """Qt-bearing exports stay lazy so a child import graph never pulls Qt."""
    if name == "WorkerSupervisor":
        from .supervisor import WorkerSupervisor

        return WorkerSupervisor
    raise AttributeError(name)
