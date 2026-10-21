from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..media.images import load_pixmap, logical_size, scale_pixmap, screen_dpr

_MAX_WIDTH = 320
#: 气泡内图片的等比缩放上限（宽与高都不超过它）。
MAX_IMAGE_SIDE = 320
_IMAGE_PAD = 8
BUBBLE_GAP = 6
SCREEN_MARGIN = 4

#: 文本缩放系数（``bubble_text_scale`` 百分比 / 100）的支持区间。
TEXT_SCALE_MIN = 0.5
TEXT_SCALE_MAX = 3.0

_TEXT_FONT_PX = 13
_TEXT_PADDING = (10, 14)
_TEXT_RADIUS = 12
_CAPTION_FONT_PX = 12
_CAPTION_PADDING = (5, 10)
_CAPTION_RADIUS = 10


def _px(value: float) -> int:
    return max(1, int(round(value)))


def _text_qss(scale: float) -> str:
    return (
        "QLabel{background:rgba(255,255,255,242);color:#243040;"
        "border:1px solid rgba(120,150,180,180);border-radius:%dpx;"
        "padding:%dpx %dpx;font-size:%dpx;}"
        % (
            _px(_TEXT_RADIUS * scale),
            _px(_TEXT_PADDING[0] * scale),
            _px(_TEXT_PADDING[1] * scale),
            _px(_TEXT_FONT_PX * scale),
        )
    )


def _caption_qss(scale: float) -> str:
    return (
        "QLabel#bubbleCaption{background:rgba(255,255,255,242);color:#243040;"
        "border:1px solid rgba(120,150,180,180);border-radius:%dpx;"
        "padding:%dpx %dpx;font-size:%dpx;font-weight:600;}"
        % (
            _px(_CAPTION_RADIUS * scale),
            _px(_CAPTION_PADDING[0] * scale),
            _px(_CAPTION_PADDING[1] * scale),
            _px(_CAPTION_FONT_PX * scale),
        )
    )


_TEXT_QSS = _text_qss(1.0)

_IMAGE_QSS = (
    "QLabel#bubbleImage{background:rgba(255,255,255,242);"
    "border:1px solid rgba(120,150,180,180);border-radius:12px;}"
)

_CAPTION_QSS = _caption_qss(1.0)


def clamp_text_scale(scale: float) -> float:
    """把文本缩放系数钳进支持区间；非法值回退 1.0（与旧版逐像素一致）。"""
    try:
        value = float(scale)
    except (TypeError, ValueError):
        return 1.0
    if value != value:  # NaN
        return 1.0
    return max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, value))


def clamp_image_scale(scale: float) -> float:
    """图片缩放系数与文本同口径（0.5..3.0），非法值回退 1.0。"""
    return clamp_text_scale(scale)


def _scaled_pixmap(
    image, max_side: int = MAX_IMAGE_SIDE, dpr: float | None = None
) -> QPixmap | None:
    """把 ``QPixmap`` 或图片路径读成不超过 ``max_side`` 逻辑像素的 ``QPixmap``。

    解码尺寸乘设备像素比，避免 1.5 倍缩放的屏幕上「先缩到 320 再放大」发虚。
    """
    max_side = max(1, int(max_side))
    ratio = screen_dpr() if dpr is None else dpr
    if isinstance(image, QPixmap):
        if image.isNull():
            return None
        return scale_pixmap(image, max_side, ratio)
    return load_pixmap(Path(image), max_side, ratio)


class SpeechBubble(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._content_kind = "text"
        self._anchor: QRect | None = None
        self._place_key: tuple | None = None
        self._text_scale = 1.0
        self._stream_mode = False
        self._host_on_top = True

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(_MAX_WIDTH)
        self.label.setStyleSheet(_TEXT_QSS)

        self.caption_label = QLabel("")
        self.caption_label.setObjectName("bubbleCaption")
        self.caption_label.setMaximumWidth(MAX_IMAGE_SIDE + 2 * _IMAGE_PAD)
        self.caption_label.setStyleSheet(_CAPTION_QSS)
        self.caption_label.hide()

        self.image_label = QLabel("")
        self.image_label.setObjectName("bubbleImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setContentsMargins(_IMAGE_PAD, _IMAGE_PAD, _IMAGE_PAD, _IMAGE_PAD)
        self.image_label.setStyleSheet(_IMAGE_QSS)
        self.image_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BUBBLE_GAP)
        layout.addWidget(self.caption_label)
        layout.addWidget(self.image_label)
        layout.addWidget(self.label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._apply_window_flags()

    # ---------------------------------------------------------------- 查询
    def content_kind(self) -> str:
        return self._content_kind

    def is_showing_image(self) -> bool:
        return self._content_kind == "image" and self.isVisible()

    def anchor(self) -> QRect | None:
        return QRect(self._anchor) if self._anchor is not None else None

    def text_scale(self) -> float:
        """当前文本缩放系数（1.0 = 旧版默认字号）。"""
        return self._text_scale

    def set_text_scale(self, scale: float) -> None:
        """按系数缩放正文/副标题字号与内边距；文本在显示时立即重排。"""
        value = clamp_text_scale(scale)
        if value == self._text_scale:
            return
        self._text_scale = value
        self.label.setStyleSheet(_text_qss(value))
        self.caption_label.setStyleSheet(_caption_qss(value))
        if self._anchor is None or not self.isVisible():
            return
        self.adjustSize()
        self._place(self._anchor)

    # ---------------------------------------------------------------- 窗口样式
    def _window_flags(self):
        if self._stream_mode:
            return (
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if self._host_on_top:
            # 同一图层：桌宠置顶时气泡也必须置顶，否则图片气泡会被桌宠盖住
            # （文字气泡贴在头顶，肉眼看不出来）。
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def _apply_window_flags(self) -> None:
        """重建旗标（setWindowFlags 会隐窗，可见时要原地恢复并抬到最前）。"""
        was_visible = self.isVisible()
        self.setWindowFlags(self._window_flags())
        if was_visible:
            if self._anchor is not None:
                self._place(self._anchor)
            self.show()
            self.raise_()

    def set_host_on_top(self, on: bool) -> None:
        """跟随宿主「窗口置顶」开关（同主分支 ``set_host_on_top``）。"""
        on = bool(on)
        if on == self._host_on_top:
            return
        self._host_on_top = on
        self._apply_window_flags()

    def host_on_top(self) -> bool:
        return self._host_on_top

    def set_stream_mode(self, enabled: bool) -> None:
        """直播捕获兼容：气泡也必须是普通顶层窗口，否则捕获软件看不到它。"""
        enabled = bool(enabled)
        if enabled == self._stream_mode:
            return
        self._stream_mode = enabled
        self._apply_window_flags()

    # ---------------------------------------------------------------- 文本
    def show_text(self, text: str, anchor: QRect, duration_ms: int = 4000) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self._content_kind = "text"
        self.caption_label.hide()
        self.caption_label.clear()
        self.image_label.hide()
        self.image_label.clear()
        self.label.show()
        self.label.setText(text)
        self.adjustSize()
        self._place(anchor)
        self.show()
        self.raise_()
        self._timer.start(max(800, int(duration_ms)))

    # ---------------------------------------------------------------- 图片
    def show_image(
        self,
        image,
        anchor: QRect,
        caption: str = "",
        duration_ms: int = 4000,
        *,
        image_scale: float = 1.0,
        dpr: float | None = None,
    ) -> bool:
        scale = clamp_image_scale(image_scale)
        max_side = max(1, int(round(MAX_IMAGE_SIDE * scale)))
        pixmap = _scaled_pixmap(image, max_side, dpr)
        if pixmap is None:
            return False
        self._content_kind = "image"
        self.label.clear()
        self.label.hide()
        caption = str(caption or "").strip()
        self.caption_label.setMaximumWidth(max_side + 2 * _IMAGE_PAD)
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))
        width, height = logical_size(pixmap)
        self.image_label.setFixedSize(
            width + 2 * _IMAGE_PAD, height + 2 * _IMAGE_PAD
        )
        self.image_label.setPixmap(pixmap)
        self.image_label.show()
        self.adjustSize()
        self._place(anchor)
        self.show()
        self.raise_()
        self._timer.start(max(800, int(duration_ms)))
        return True

    # ---------------------------------------------------------------- 跟随
    def reposition(self, anchor: QRect) -> None:
        """锚点或自身尺寸变化时重排；不可见时只记住锚点。"""
        self._anchor = QRect(anchor)
        if not self.isVisible():
            return
        key = (
            anchor.x(),
            anchor.y(),
            anchor.width(),
            anchor.height(),
            self.width(),
            self.height(),
        )
        if key == self._place_key:
            return
        self._place(anchor)

    def _place(self, anchor: QRect) -> None:
        """贴着角色锚点放：上居中 → 上偏左右 → 两侧 → 下方，且不压住角色。"""
        self._anchor = QRect(anchor)
        width = self.width()
        height = self.height()
        self._place_key = (
            anchor.x(),
            anchor.y(),
            anchor.width(),
            anchor.height(),
            width,
            height,
        )
        centered = anchor.center().x() - width // 2
        left_x = anchor.left() - width + max(24, anchor.width() // 3)
        right_x = anchor.right() - max(24, anchor.width() // 3)
        above = anchor.top() - height - BUBBLE_GAP
        below = anchor.bottom() + BUBBLE_GAP
        middle = anchor.center().y() - height // 2
        candidates = [
            (centered, above),
            (left_x, above),
            (right_x, above),
            (anchor.right() + BUBBLE_GAP, middle),
            (anchor.left() - width - BUBBLE_GAP, middle),
            (centered, below),
            (left_x, below),
            (right_x, below),
        ]
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            self.move(int(candidates[0][0]), int(candidates[0][1]))
            return
        for x, y in candidates:
            rect = QRect(int(x), int(y), width, height)
            if area.contains(rect) and not rect.intersects(anchor):
                self.move(rect.topLeft())
                return
        x = max(area.left() + SCREEN_MARGIN, min(area.right() - width - SCREEN_MARGIN, centered))
        y = above if above >= area.top() + SCREEN_MARGIN else min(
            area.bottom() - height - SCREEN_MARGIN, below
        )
        self.move(int(x), int(y))
