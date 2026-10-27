from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..media.images import load_pixmap, logical_size, scale_pixmap, screen_dpr

#: 气泡内图片的等比缩放上限（宽与高都不超过它）。
MAX_IMAGE_SIDE = 320
_IMAGE_PAD = 8
BUBBLE_GAP = 6
SCREEN_MARGIN = 4

#: 文本列宽：短文本 248，超过 60 字逐步放宽到 360（主分支口径），再乘字号缩放。
BUBBLE_TEXT_COLUMN = 248
BUBBLE_TEXT_COLUMN_MAX = 360
BUBBLE_TEXT_GROWTH_CHARS = 60
BUBBLE_TEXT_GROWTH_SPAN = 100
#: label 的显式尺寸口径（主分支 `bubble_label_size`）：最短 96px，行宽余量 4px。
BUBBLE_TEXT_MIN_WIDTH = 96
BUBBLE_TEXT_SLACK = 4
#: 每页最多行数：短文本 3 行，长文本 6 行。
BUBBLE_MAX_LINES_SHORT = 3
BUBBLE_MAX_LINES_LONG = 6

#: 文本缩放系数（``bubble_text_scale`` 百分比 / 100）的支持区间。
TEXT_SCALE_MIN = 0.5
TEXT_SCALE_MAX = 3.0

_TEXT_FONT_PX = 13
_TEXT_SUBTITLE_FONT_PX = 11
_TEXT_PAGER_FONT_PX = 10
_TEXT_PADDING = (10, 14)
_TEXT_RADIUS = 12
_CAPTION_FONT_PX = 12
_CAPTION_PADDING = (5, 10)
_CAPTION_RADIUS = 10


def _px(value: float) -> int:
    return max(1, int(round(value)))


def _panel_margins(scale: float) -> tuple[int, int, int, int]:
    horizontal = _px(_TEXT_PADDING[1] * scale)
    vertical = _px(_TEXT_PADDING[0] * scale)
    return (horizontal, vertical, horizontal, vertical)


def _panel_qss(scale: float) -> str:
    return (
        "QWidget#bubblePanel{background:rgba(255,255,255,242);"
        "border:1px solid rgba(120,150,180,180);border-radius:%dpx;}"
        % _px(_TEXT_RADIUS * scale)
    )


def _text_qss(scale: float) -> str:
    return (
        "QLabel{background:transparent;color:#243040;font-size:%dpx;}"
        % _px(_TEXT_FONT_PX * scale)
    )


def _subtitle_qss(scale: float) -> str:
    return (
        "QLabel#bubbleSubtitle{background:transparent;color:rgba(36,48,64,190);"
        "font-size:%dpx;font-weight:600;}"
        % _px(_TEXT_SUBTITLE_FONT_PX * scale)
    )


def _pager_qss(scale: float) -> str:
    return (
        "QLabel#bubblePager{background:transparent;color:rgba(60,76,94,160);"
        "font-size:%dpx;}"
        % _px(_TEXT_PAGER_FONT_PX * scale)
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


def column_for_text(text: str, scale: float = 1.0) -> int:
    """文本列宽：短文本 248，超过 60 字逐步放宽到 360，再乘字号缩放。"""
    scale = clamp_text_scale(scale)
    length = len(str(text or ""))
    if length <= BUBBLE_TEXT_GROWTH_CHARS:
        grow = 0
    else:
        span = min(length - BUBBLE_TEXT_GROWTH_CHARS, BUBBLE_TEXT_GROWTH_SPAN)
        grow = (BUBBLE_TEXT_COLUMN_MAX - BUBBLE_TEXT_COLUMN) * span // BUBBLE_TEXT_GROWTH_SPAN
    return max(60, int(round((BUBBLE_TEXT_COLUMN + grow) * scale)))


def _wrap_lines(text: str, column_px: int, font) -> list[str]:
    """按字体实际宽度逐字折行；显式换行保留。"""
    metrics = QFontMetrics(font)
    column = max(20, int(column_px) - BUBBLE_TEXT_SLACK)
    lines: list[str] = []
    for paragraph in str(text or "").splitlines() or [""]:
        widths = {character: metrics.horizontalAdvance(character) for character in set(paragraph)}
        current = ""
        width = 0
        for character in paragraph:
            advance = widths[character]
            if current and width + advance > column:
                lines.append(current)
                current = character
                width = advance
            else:
                current += character
                width += advance
        lines.append(current)
    return lines


def paginate_text(text: str, *, column_px: int, font, max_lines: int | None = None) -> list[str]:
    """把长文本切成多页；短文本不超过 3 行，长文本每页 6 行。"""
    lines = _wrap_lines(text, column_px, font)
    limit = int(max_lines or 0)
    if limit <= 0:
        limit = (
            BUBBLE_MAX_LINES_SHORT
            if len(lines) <= BUBBLE_MAX_LINES_SHORT
            else BUBBLE_MAX_LINES_LONG
        )
    limit = max(1, limit)
    if len(lines) > BUBBLE_MAX_LINES_SHORT:
        limit = max(limit, BUBBLE_MAX_LINES_LONG)
    pages = [
        "\n".join(lines[index : index + limit])
        for index in range(0, len(lines), limit)
    ]
    pages = [page for page in pages if page.strip()] or [str(text or "")]
    # 末页只剩一行会被误读成“被截断”；从前一页借一行过来（主分支同口径）。
    if len(pages) > 1 and len(pages[-1].split("\n")) == 1:
        previous = pages[-2].split("\n")
        if len(previous) > 1:
            pages[-2] = "\n".join(previous[:-1])
            pages[-1] = previous[-1] + "\n" + pages[-1]
    return pages



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
    #: 左键点在气泡上：桌宠用来打开「快速对话」（主分支同一条入口）。
    clicked = Signal()
    #: 气泡收起（自动到时 / 手动 hide 都算，仅「原本可见」时发一次）。
    #: 点击台词要排在余额气泡收起之后，窗口层靠它接续。
    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._content_kind = "text"
        self._anchor: QRect | None = None
        self._place_key: tuple | None = None
        #: `showEvent/hideEvent` 里的可见标志（进 hideEvent 时 Qt 已清 visible）。
        self._was_shown = False
        self._text_scale = 1.0
        self._stream_mode = False
        self._host_on_top = True
        self._full_text = ""
        self._subtitle = ""
        self._pages: list[str] = []
        self._page_index = 0
        self._duration_ms = 4000

        self.label = QLabel("")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.label.setWordWrap(False)
        self.label.setStyleSheet(_TEXT_QSS)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("bubbleSubtitle")
        self.subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(_subtitle_qss(1.0))
        self.subtitle_label.hide()

        self.pager = QLabel("")
        self.pager.setObjectName("bubblePager")
        self.pager.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pager.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pager.setStyleSheet(_pager_qss(1.0))
        self.pager.hide()

        self.text_panel = QWidget(self)
        self.text_panel.setObjectName("bubblePanel")
        self.text_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.text_panel.setStyleSheet(_panel_qss(1.0))
        panel_layout = QVBoxLayout(self.text_panel)
        panel_layout.setContentsMargins(*_panel_margins(1.0))
        panel_layout.setSpacing(2)
        panel_layout.addWidget(self.subtitle_label)
        panel_layout.addWidget(self.label)
        panel_layout.addWidget(self.pager)

        self.caption_label = QLabel("")
        self.caption_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.caption_label.setObjectName("bubbleCaption")
        self.caption_label.setMaximumWidth(MAX_IMAGE_SIDE + 2 * _IMAGE_PAD)
        self.caption_label.setStyleSheet(_CAPTION_QSS)
        self.caption_label.hide()

        self.image_label = QLabel("")
        self.image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
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
        layout.addWidget(self.text_panel)

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
        self.subtitle_label.setStyleSheet(_subtitle_qss(value))
        self.pager.setStyleSheet(_pager_qss(value))
        self.text_panel.setStyleSheet(_panel_qss(value))
        if self.text_panel.layout() is not None:
            self.text_panel.layout().setContentsMargins(*_panel_margins(value))
        self.caption_label.setStyleSheet(_caption_qss(value))
        if self._content_kind == "text" and self._full_text:
            self._render_text()
            if self._anchor is not None:
                self._place(self._anchor)
            if self.isVisible():
                self._schedule_page()
            return
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
    def show_text(
        self,
        text: str,
        anchor: QRect,
        duration_ms: int = 4000,
        *,
        subtitle: str = "",
    ) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self._content_kind = "text"
        self.caption_label.hide()
        self.caption_label.clear()
        self.image_label.hide()
        self.image_label.clear()
        self.text_panel.show()
        self._full_text = text
        self._subtitle = str(subtitle or "").strip()
        self._duration_ms = max(800, int(duration_ms))
        self._page_index = 0
        self._anchor = QRect(anchor)
        self._render_text()
        self._place(anchor)
        self.show()
        self.raise_()
        # 窗口显示后布局才最终生效：再量一次并重排，避免“永远慢一句”。
        self.adjustSize()
        self._place(anchor)
        self._schedule_page()

    def _column(self) -> int:
        column = column_for_text(self._full_text, self._text_scale)
        anchor = self._anchor
        if anchor is not None:
            screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                padding = 2 * _px(_TEXT_PADDING[1] * self._text_scale)
                column = min(column, max(80, area.width() - 2 * SCREEN_MARGIN - padding))
        return column

    def _text_font(self):
        self.label.ensurePolished()
        font = self.label.font()
        font.setPixelSize(_px(_TEXT_FONT_PX * self._text_scale))
        return font

    def _paginate(self) -> list[str]:
        return paginate_text(
            self._full_text,
            column_px=self._column(),
            font=self._text_font(),
        )

    def _render_text(self) -> None:
        self._pages = self._paginate()
        if not self._pages:
            return
        self._page_index = max(0, min(self._page_index, len(self._pages) - 1))
        page = self._pages[self._page_index]
        self.label.setWordWrap(False)
        self.label.setText(page)

        font = self._text_font()
        metrics = QFontMetrics(font)
        lines = page.split("\n") or [""]
        widest = max((metrics.horizontalAdvance(line) for line in lines), default=0)
        width = max(
            BUBBLE_TEXT_MIN_WIDTH,
            min(self._column(), widest + BUBBLE_TEXT_SLACK),
        )

        self.subtitle_label.setText(self._subtitle)
        self.subtitle_label.setVisible(bool(self._subtitle))
        subtitle_height = 0
        if self._subtitle:
            self.subtitle_label.ensurePolished()
            subtitle_metrics = QFontMetrics(self.subtitle_label.font())
            subtitle_width = min(
                self._column(),
                subtitle_metrics.horizontalAdvance(self._subtitle) + BUBBLE_TEXT_SLACK,
            )
            width = max(width, BUBBLE_TEXT_MIN_WIDTH, subtitle_width)
            subtitle_height = self.subtitle_label.heightForWidth(width)
            if subtitle_height <= 0:
                subtitle_height = self.subtitle_label.sizeHint().height()
            self.subtitle_label.setFixedWidth(width)
            self.subtitle_label.setFixedHeight(max(1, subtitle_height))

        height = max(1, len(lines)) * metrics.lineSpacing() + 2
        self.label.setFixedSize(width, height)

        if len(self._pages) > 1:
            dots = " ".join(
                "●" if index == self._page_index else "○"
                for index in range(len(self._pages))
            )
            self.pager.setText(dots)
            self.pager.setFixedWidth(width)
            self.pager.show()
        else:
            self.pager.clear()
            self.pager.hide()

        layout = self.text_panel.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()

    def _schedule_page(self) -> None:
        total = max(1, sum(len(page) for page in self._pages))
        share = len(self._pages[self._page_index]) / total if self._pages else 1.0
        dwell = max(900, int(self._duration_ms * share))
        self._timer.start(dwell)

    def page_count(self) -> int:
        return len(self._pages)

    def page_index(self) -> int:
        return self._page_index

    def full_text(self) -> str:
        """当前气泡的完整正文（分页前），只读。"""
        return self._full_text

    def subtitle_text(self) -> str:
        return self._subtitle

    def next_page(self) -> bool:
        """翻到下一页；已是最后一页时返回 False（由滚轮决定是否关闭）。"""
        if self._page_index + 1 >= len(self._pages):
            return False
        self._page_index += 1
        self._render_text()
        if self._anchor is not None:
            self._place(self._anchor)
        self._schedule_page()
        return True

    def previous_page(self) -> bool:
        if self._page_index <= 0:
            return False
        self._page_index -= 1
        self._render_text()
        if self._anchor is not None:
            self._place(self._anchor)
        self._schedule_page()
        return True

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._content_kind != "text" or len(self._pages) <= 1:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        if delta < 0:
            if not self.next_page():
                self.hide()
        elif not self.previous_page():
            pass
        event.accept()

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
        self._full_text = ""
        self._subtitle = ""
        self._pages = []
        self.label.clear()
        self.text_panel.hide()
        caption = str(caption or "").strip()
        caption_width = max_side + 2 * _IMAGE_PAD
        self.caption_label.setWordWrap(True)
        self.caption_label.setFixedWidth(caption_width)
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))
        if caption:
            self.caption_label.ensurePolished()
            caption_height = self.caption_label.heightForWidth(caption_width)
            if caption_height <= 0:
                caption_height = self.caption_label.sizeHint().height()
            self.caption_label.setFixedHeight(max(1, caption_height))
        width, height = logical_size(pixmap)
        self.image_label.setFixedSize(
            width + 2 * _IMAGE_PAD, height + 2 * _IMAGE_PAD
        )
        self.image_label.setPixmap(pixmap)
        self.image_label.show()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()
        self._place(anchor)
        self.show()
        self.raise_()
        self.adjustSize()
        self._place(anchor)
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

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton and self.isVisible():
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """收起时发一次 `closed`（自动到时、手动 hide、桌宠隐藏都走这里）。

        进 `hideEvent` 时 Qt 已经把 visible 标志清掉了，所以用 `showEvent` 记的
        自己的标志判断「原本是否可见」——否则每条都会发，或者一条都不发。
        """
        was_visible = self._was_shown
        super().hideEvent(event)
        self._was_shown = False
        if was_visible:
            self.closed.emit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._was_shown = True

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
        y = max(area.top() + SCREEN_MARGIN, min(y, area.bottom() - height - SCREEN_MARGIN))
        self.move(int(x), int(y))
