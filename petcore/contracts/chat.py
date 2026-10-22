"""聊天窗口的公开契约。

mod 只能通过 ``HostPorts.chat`` 驱动 core 的聊天窗口：窗口、Markdown 渲染、会话
落盘和取消都在 core。``owner`` 是 mod id，窗口按 ``(owner, pet_slot)`` 隔离，
互不串流。

运行时代码不得 import PySide6；需要回 GUI 线程用 ``HostPorts.scheduler``。
只有设置页（Core 托管的受信 UI）可以用 QtWidgets，但同样不得自建聊天窗口或
直接操作气泡。
"""

from __future__ import annotations

from typing import Callable, Protocol


class ChatPort(Protocol):
    def open(self, owner: str, *, pet_slot: int | None = None, title: str = "") -> bool: ...
    def append(self, owner: str, role: str, text: str, *, pet_slot: int | None = None) -> None: ...
    def token(self, owner: str, delta: str, *, pet_slot: int | None = None) -> None: ...
    def done(self, owner: str, text: str = "", *, pet_slot: int | None = None) -> None: ...
    def error(
        self, owner: str, reason: str, message: str = "", *, pet_slot: int | None = None
    ) -> None: ...
    def close(self, owner: str, *, pet_slot: int | None = None) -> None: ...
    def cancel(self, owner: str, *, pet_slot: int | None = None) -> None: ...
    def is_open(self, owner: str, *, pet_slot: int | None = None) -> bool: ...
    def history(self, owner: str, *, pet_slot: int | None = None) -> list[dict]: ...
    def record(
        self, owner: str, role: str, text: str, *, pet_slot: int | None = None
    ) -> None:
        """只写会话（和已存在的窗口），不新建/不唤出窗口。

        「看看屏幕」这类后台结果要进聊天记录，但不得打断用户当前操作。
        """
        ...

    def take_attachments(
        self, owner: str, *, pet_slot: int | None = None
    ) -> list[dict]:
        """取走并清空最近一次提交携带的附件描述（文本/图片 data URL）。"""
        ...

    def on_submit(
        self, owner: str, callback: Callable[[str, int], None]
    ) -> Callable[[], None]: ...
    def on_stop(self, owner: str, callback: Callable[[int], None]) -> Callable[[], None]: ...


class ChatCancelled(RuntimeError):
    """调用方主动停止；界面按中性状态显示。"""
