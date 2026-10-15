# -*- coding: utf-8 -*-
"""Internal official host ABI, supplied after host-owned authorization.

Ported from the DLC branch ``pet/feature_ports.py``；本仓库只保留**本地功能包**用得
上的那一组端口：owner 作用域的配置 / 文档 / 状态文档，加上执行许可与 Worker 装配
位。DLC 侧同文件里的凭据库（``credentials`` / ``legacy_secret_reader``）、偏好
（``preferences``）、窗口（``FeatureWindowPorts``）、用户数据
（``FeatureUserDataPort``）与官方内置域（screen / ai）绑定不在本仓库的 MOD 路径上，
随那条线一起做——本地包不拿凭据、不拿 Core 窗口对象、不拿全局配置。
注：DLC 4A 的两个 host 侧端口本体已移植（``pet/desktop_query.py`` /
``pet/credentials.py``，含契约测试），但本上下文**不注入**它们——``desktop``
恒为 ``None``、``credentials`` 字段不落地；宿主注入随识屏/聊天包线一起做。

``events`` 是 Phase 2 内核移植新增的事件订阅面：原生上下文恒为 ``None``，由
:meth:`pet.plugins.feature_host.FeatureHost.bind_context` 在授权后注入绑定本
owner 的 :class:`pet.plugins.events.ScopedEventBus`。

Not a sandbox: 端口是"能力面"的表达，不是 Python 沙箱；作者代码与桌宠同权限运行
（见 ``docs/modding/HOST-ONLY.md`` 的信任模型）。给定端口也不授予安装状态账本或
另一个 owner 的数据。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from .api_ports import FeatureApiPort

__all__ = [
    "FeatureConfigurationPort",
    "FeatureDocumentPort",
    "FeatureHostContext",
    "FeatureStateDocumentPort",
]


class FeatureConfigurationPort(Protocol):
    """一个 owner 的配置命名空间；节点由宿主选定，作者选不了。"""

    def read_namespace(self) -> dict: ...

    def revision(self) -> str: ...

    def commit_namespace(
        self, value: dict, *, expected_revision: str, source_guard: Callable[[dict], None] | None = None
    ) -> None: ...

    def operation(self) -> AbstractContextManager[None]: ...


class FeatureDocumentPort(Protocol):
    """宿主选定的一份数据文档，不是通用文件系统访问。"""

    def read(self) -> dict: ...

    def write(self, value: dict) -> None: ...

    def clear(self) -> None: ...


class FeatureStateDocumentPort(FeatureDocumentPort, Protocol):
    """一份可跨实例互斥的状态文档（锁策略由宿主决定）。"""

    def locked(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class FeatureHostContext:
    """Internal official host ABI, supplied after host-owned authorization.

    Values are already bound to one owner; nothing here lets a feature select
    another owner's namespace, another document or a Core data directory.
    """

    owner: str
    configuration: FeatureConfigurationPort
    documents: Mapping[str, FeatureDocumentPort]
    state_documents: Mapping[str, FeatureStateDocumentPort]
    #: 桌面查询端口；本仓库的 MOD 路径恒为 None（不给桌面/窗口能力）。
    desktop: Any | None = None
    worker_launch_factory: Any | None = None
    allow_in_process: bool = True
    execution_authorized: Callable[[], bool] | None = None
    bind_execution: Callable[[Callable, Callable], Callable[[], None]] | None = None
    #: 通用 api 端口；本仓库固定为"调用即抛 unsupported_capability"（D2-d 未落地）。
    api: FeatureApiPort | None = None
    #: owner 作用域的事件订阅门面；未过 bind_context 授权的原生上下文恒为 None。
    events: Any | None = None
