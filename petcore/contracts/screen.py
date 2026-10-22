"""截屏能力的公开契约。

截图只在内存里流转：``ScreenCapture.png`` 直接交给多模态请求，**不写磁盘**、
不写日志正文。没有声明并获批 ``screenshot.capture`` 的 mod 拿不到这个端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    png: bytes
    width: int
    height: int
    screen_name: str = ""


class ScreenPort(Protocol):
    def capture(self, *, pet_slot: int | None = None) -> ScreenCapture: ...
