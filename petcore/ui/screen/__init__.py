"""Core 截图界面：框选覆盖层、截图提问浮窗与控制器。

``select_region`` 实现 ``ScreenPort.capture_region``；``ScreenAskController``
实现 ``ScreenAskPort``。窗口、消息列表、加载彩蛋与跨线程都在这一层，mod 只拿
裁好的 PNG 与回调。
"""

from __future__ import annotations

from .ask_window import ScreenAskWindow
from .controller import ScreenAskController
from .selection import select_region

__all__ = ["ScreenAskController", "ScreenAskWindow", "select_region"]
