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

#: 送给视觉模型前的长边上限（**物理像素**）。按物理像素封顶，保证同一份内容在
#: 100%/150%/200% 缩放下占用同样的像素预算与费用；本地 OCR 仍用原图。
VISION_MAX_EDGE = 1024

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
    #: 窗口采样时的窗口句柄（整屏/框选为 0）。
    hwnd: int = 0
    #: 画面指纹（64 位 dHash，由 Core 在抓图时算好）；无法计算时为 0。
    dh_hash: int = 0


@dataclass(frozen=True, slots=True)
class WindowSample:
    """窗口画面的轻量采样：只有指纹与尺寸，没有 PNG。"""

    hwnd: int = 0
    dh_hash: int = 0
    width: int = 0
    height: int = 0
    process: str = ""
    title: str = ""
    rect: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """前台窗口的只读快照；不含窗口内容。"""

    hwnd: int
    process: str = ""
    title: str = ""
    #: 屏幕坐标 ``(x, y, w, h)``；DWM/GetWindowRect 都失败时为 ``None``。
    rect: tuple[int, int, int, int] | None = None


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

    def foreground_window(self) -> WindowInfo | None:
        """当前前台窗口的句柄/进程/标题/矩形；不可见、最小化或非 Windows 返回
        ``None``。只读元数据，不抓取窗口内容，也不写日志。"""
        ...

    def capture_foreground(
        self, *, expected_hwnd: int = 0
    ) -> ScreenCapture | None:
        """抓当前前台窗口那一块画面（内存 PNG + ``dh_hash``）。

        ``expected_hwnd`` 非 0 时在抓图前后各复核一次前台窗口：不一致就返回
        ``None`` 并丢弃画面，避免把用户刚切走的窗口拍下来。窗口没有可用矩形、
        被最小化或抓取失败同样返回 ``None``（调用方按「本次跳过」处理）。
        """
        ...

    def shrink_for_vision(self, png: bytes, *, max_edge: int = VISION_MAX_EDGE) -> bytes:
        """把 PNG 按长边（物理像素）缩到 ``max_edge`` 以内，供多模态请求使用。

        图片只在内存里缩放；空数据/解码失败/本来就不超限时原样返回。本地 OCR
        与「复制图像」必须继续用原图，只有要发给模型的那一步才调这里。
        """
        ...

    def sample_foreground(
        self, *, expected_hwnd: int = 0
    ) -> WindowSample | None:
        """只采样窗口画面的指纹与尺寸（不编码 PNG、不做大图读取）。

        用来判断「这次心跳画面变了没有」；确认变化后再调
        :meth:`capture_foreground` 拿真正要发给模型的画面。
        同样的双复核与失败返回 ``None`` 语义。
        """
        ...

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
