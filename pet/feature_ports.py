# -*- coding: utf-8 -*-
"""Internal official host ABI, supplied after host-owned authorization.

Ported from the DLC branch ``pet/feature_ports.py``；本地功能包路径只注入 owner
作用域的配置 / 文档 / 状态文档，加上执行许可与 Worker 装配位——本地包不拿凭据、
不拿 Core 窗口对象、不拿全局配置。用户数据（``FeatureUserDataPort``）与官方
AI 域绑定属聊天包线，本片不落。
注：DLC 4A 的两个 host 侧端口本体已移植（``pet/desktop_query.py`` /
``pet/credentials.py``，含契约测试）；本地 MOD 上下文里 ``desktop`` 与
``credentials`` 恒为 ``None``，注入只发生在官方识屏绑定（``bind_screen_context``）。

``events`` 是 Phase 2 内核移植新增的事件订阅面：原生上下文恒为 ``None``，由
:meth:`pet.plugins.feature_host.FeatureHost.bind_context` 在授权后注入绑定本
owner 的 :class:`pet.plugins.events.ScopedEventBus`。

识屏包线（DLC 第三片）再补四个字段——``credentials`` / ``legacy_secret_reader`` /
``preferences`` / ``window``，与上游 DLC 同名同形。它们全部默认 ``None``：
本地 MOD 路径（``bind_local_context``）不注入其中任何一个；只有官方识屏绑定
（``bind_screen_context``）按 owner 闭集注入。

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
    "FeaturePreferencesPort",
    "FeatureStateDocumentPort",
    "FeatureWindowPorts",
    "FeatureWindowState",
]


class FeatureConfigurationPort(Protocol):
    """一个 owner 的配置命名空间；节点由宿主选定，作者选不了。"""

    def read_namespace(self) -> dict: ...

    def revision(self) -> str: ...

    def commit_namespace(
        self, value: dict, *, expected_revision: str, source_guard: Callable[[dict], None] | None = None
    ) -> None: ...

    def operation(self) -> AbstractContextManager[None]: ...


class FeaturePreferencesPort(Protocol):
    """宿主已圈好字段集的偏好面；``stage`` 只进草稿，``flush`` 才落盘。"""

    def read(self) -> dict: ...

    def stage(self, values: dict) -> None: ...

    def flush(self) -> bool: ...


class FeatureDocumentPort(Protocol):
    """宿主选定的一份数据文档，不是通用文件系统访问。"""

    def read(self) -> dict: ...

    def write(self, value: dict) -> None: ...

    def clear(self) -> None: ...


class FeatureStateDocumentPort(FeatureDocumentPort, Protocol):
    """一份可跨实例互斥的状态文档（锁策略由宿主决定）。"""

    def locked(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class FeatureWindowState:
    """一份值快照，不是窗口句柄或应用对象（与上游 DLC 同形）。"""

    window_id: str
    instance_id: str
    character_id: str
    display_name: str
    visible: bool
    interacting: bool
    mouse_through: bool


@dataclass(frozen=True, slots=True)
class FeatureWindowPorts:
    """Core 绑定的窗口操作面；越过应用边界的只有快照（与上游 DLC 同形）。

    ``external_text`` 是识屏→聊天联动的带 id 通道；宿主没有对接面时由绑定层
    回退到 ``sync_text``（上游 ``_bind_window`` 的同口径回退）。
    """

    snapshot: Callable[[], FeatureWindowState]
    agent_busy: Callable[[str, str], bool]
    show_bubble: Callable[[str, int], None]
    hold_bubble: Callable[[float], None]
    sync_text: Callable[[str, str], None]
    external_text: Callable[[str, str, str, str], None]
    enabled: Callable[[], bool]
    bind_lifecycle: Callable[[Callable[[], None], Callable[[], None], Callable[[], None]], Callable[[], None]]


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
    #: 凭据库端口（4A 本体在 pet/credentials.py）；仅官方识屏绑定注入，本地 MOD 恒 None。
    credentials: Any | None = None
    #: legacy 凭据读取器（上游迁移用）；本仓库不移植迁移，识屏绑定恒 None。
    legacy_secret_reader: Callable[[str], str] | None = None
    #: 字段集已由宿主圈定的偏好面；仅官方识屏绑定注入，本地 MOD 恒 None。
    preferences: FeaturePreferencesPort | None = None
    #: 窗口操作面（快照/气泡/聊天联动/生命周期）；仅官方识屏绑定注入。
    window: FeatureWindowPorts | None = None
