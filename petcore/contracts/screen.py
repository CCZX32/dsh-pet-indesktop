"""截屏与截图问答能力的公开契约。

截图只在内存里流转：``ScreenCapture.png`` 直接交给多模态请求，**不写磁盘**、
不写日志正文。没有声明并获批 ``screenshot.capture`` 的 mod 拿不到这个端口。

两个端口分工：

- :class:`ScreenPort` 负责「取画面」：整屏、框选、前台应用信息。框选 UI 归 Core
  （``petcore/ui/screen/``），mod 只拿到裁好的 PNG。
- :class:`ScreenAskPort` 负责「截图提问窗口」：窗口、消息列表、加载态和跨线程都归
  Core；模型调用仍由 mod 在回调里完成（Core 不依赖具体业务域）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    png: bytes
    width: int
    height: int
    screen_name: str = ""
    #: 抓屏当刻的前台应用「进程名 | 窗口标题」；拿不到时为空串。
    app_info: str = ""


class ScreenError(RuntimeError):
    """截屏失败的稳定分类；``reason`` 给界面/日志用，不含画面内容。"""

    reason = "capture_failed"

    def __init__(self, reason: str = "", message: str = ""):
        if reason:
            self.reason = reason
        super().__init__(message or self.reason)


class ScreenSelectionCancelled(ScreenError):
    """用户在框选覆盖层里取消（Esc / 空选区）。"""

    reason = "cancelled"

    def __init__(self, message: str = "已取消截图"):
        super().__init__("cancelled", message)


class ScreenPort(Protocol):
    def capture(self, *, pet_slot: int | None = None) -> ScreenCapture: ...

    def capture_region(self, *, pet_slot: int | None = None) -> ScreenCapture:
        """弹框选覆盖层并返回裁好的画面；取消时抛 :class:`ScreenSelectionCancelled`。"""
        ...

    def foreground_app(self) -> str:
        """当前前台应用描述（进程名 | 标题），拿不到返回空串。"""
        ...


class ScreenAskPort(Protocol):
    """截图提问窗口（Core UI）。

    ``on_ask`` 注册的回调在**后台线程**执行，参数为
    ``(question, image_png, history, pet_slot)``，返回模型答复文本；抛异常时窗口
    显示错误。``history`` 是此前已完成的多轮 ``{role, content}`` 文本副本，
    不含本轮问题、也不含图片（图只在首轮由回调自己拼）。
    """

    def open(
        self,
        owner: str,
        capture: ScreenCapture,
        *,
        pet_slot: int | None = None,
        title: str = "",
    ) -> bool: ...

    def close(self, owner: str, *, pet_slot: int | None = None) -> None: ...

    def is_open(self, owner: str, *, pet_slot: int | None = None) -> bool: ...

    def history(self, owner: str, *, pet_slot: int | None = None) -> list[dict]: ...

    def on_ask(
        self,
        owner: str,
        callback: Callable[[str, bytes, list[dict], int], str],
    ) -> Callable[[], None]: ...
