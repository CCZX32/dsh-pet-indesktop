"""截屏：抓一块屏幕到内存 PNG（不落盘、不写日志正文）。

只用 Qt 的 ``QScreen.grabWindow(0)``：跨平台可用、无需额外依赖；HDR/框选/OCR
留给后续阶段。权限由调用侧（``ScreenPort`` 的提供者）按能力声明控制。
"""

from __future__ import annotations

import base64
import logging

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from ..contracts.screen import ScreenCapture

logger = logging.getLogger("petcore.platform.screenshot")


def data_url(capture: ScreenCapture) -> str:
    """把 PNG 转成多模态请求可用的内联 data URL（只存在于内存）。"""
    encoded = base64.b64encode(capture.png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class ScreenshotError(RuntimeError):
    reason = "capture_failed"

    def __init__(self, reason: str = "", message: str = ""):
        if reason:
            self.reason = reason
        super().__init__(message or self.reason)


def _target_screen(window=None) -> QScreen | None:
    if window is not None:
        try:
            screen = window.screen()
        except Exception:
            screen = None
        if screen is not None:
            return screen
    return QGuiApplication.primaryScreen()


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ScreenshotError("capture_failed", "屏幕内容编码失败")
    data = bytes(buffer.data())
    buffer.close()
    if not data:
        raise ScreenshotError("capture_failed", "屏幕内容为空")
    return data


def capture_screen(window=None, *, screen: QScreen | None = None) -> ScreenCapture:
    """抓 ``screen``（缺省为窗口所在屏，再退主屏）的整屏内容。"""
    target = screen or _target_screen(window)
    if target is None:
        raise ScreenshotError("no_screen", "没有可用的显示器")
    try:
        image = target.grabWindow(0)
    except Exception as exc:  # noqa: BLE001 - 平台插件失败统一成稳定 reason
        logger.debug("grabWindow failed", exc_info=True)
        raise ScreenshotError("capture_failed", f"无法读取屏幕内容：{type(exc).__name__}") from exc
    if image is None or image.isNull():
        raise ScreenshotError("capture_failed", "无法读取屏幕内容")
    return ScreenCapture(
        png=_encode_png(image),
        width=int(image.width()),
        height=int(image.height()),
        screen_name=str(target.name() or ""),
    )
