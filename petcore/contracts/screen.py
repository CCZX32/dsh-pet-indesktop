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

#: 框选动作条上的四个动作（mod 与 core 共用同一组字符串）。
ACTION_OCR = "ocr"
ACTION_TRANSLATE = "translate"
ACTION_ASK = "ask"
ACTION_COPY = "copy"
ACTIONS = (ACTION_OCR, ACTION_TRANSLATE, ACTION_ASK, ACTION_COPY)


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    png: bytes
    width: int
    height: int
    screen_name: str = ""
    #: 抓屏当刻的前台应用「进程名 | 窗口标题」；拿不到时为空串。
    app_info: str = ""


@dataclass(frozen=True, slots=True)
class RegionPick:
    """一次框选的结果：裁好的画面 + 用户在动作条上选的动作。"""

    capture: ScreenCapture
    action: str = ACTION_ASK


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

    def capture_region(
        self, *, pet_slot: int | None = None, ai_available: bool = True
    ) -> RegionPick:
        """弹框选覆盖层并返回裁好的画面 + 动作；取消时抛
        :class:`ScreenSelectionCancelled`。

        ``ai_available`` 只控制动作条上「问问肥鱼 / 翻译」的可点性（本地 OCR 由
        扩展自己注册，core 不判断）。``copy`` 的剪贴板写入也在这里完成。
        """
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

    ``on_action`` 是「提取文字 / 翻译」的处理者注册表：core 按 ``priority``
    从小到大依次调用，回调返回空串或抛异常时换下一个。这样「本地 OCR 优先、
    AI 兜底」由扩展的注册顺序决定，core 不认识任何具体引擎。
    """

    def open(
        self,
        owner: str,
        capture: ScreenCapture,
        *,
        pet_slot: int | None = None,
        title: str = "",
    ) -> bool: ...

    def open_action(
        self,
        owner: str,
        action: str,
        capture: ScreenCapture,
        *,
        text: str = "",
        pet_slot: int | None = None,
    ) -> bool:
        """单轮动作结果窗（提取文字 / 翻译）；``text`` 是上游已识别的原文。"""
        ...

    def close(self, owner: str, *, pet_slot: int | None = None) -> None: ...

    def is_open(self, owner: str, *, pet_slot: int | None = None) -> bool: ...

    def history(self, owner: str, *, pet_slot: int | None = None) -> list[dict]: ...

    def on_ask(
        self,
        owner: str,
        callback: Callable[[str, bytes, list[dict], int], str],
    ) -> Callable[[], None]: ...

    def on_action(
        self,
        owner: str,
        callback: Callable[[str, str, bytes, int], str],
        *,
        priority: int = 100,
        actions: tuple[str, ...] = (),
    ) -> Callable[[], None]:
        """注册动作处理者；``actions`` 声明它能处理哪些动作（缺省全部）。

        返回取消注册的函数。core 用这份声明决定动作条按钮是否可点。
        """
        ...
