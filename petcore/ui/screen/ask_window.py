"""截图提问浮窗：带图的迷你对话窗（图在输入栏上方，打字发问，可多轮）。

为什么是一个对话窗而不是「框选 → 直接发图 → 弹答案」：一次性问答把「问什么」
的权利没收了——用户框的是图，想问的却是自己的事。**浮窗本身就是确认面**：
图躺在输入栏上方，发不发、发什么文字，都是用户亲手点「发送」那一刻决定的；
打开窗口一个字节都不出网。

隐私不变量：选区图只在内存里（``ScreenCapture.png``），不落盘、不写日志；
唯一的网络出口是用户配置的 AI 服务，且只在点「发送」时发生（由 controller
回调完成，本窗不碰网络）。

线程纪律：窗口对象只在 GUI 线程碰；发送与结果回传都由
:class:`~petcore.ui.screen.controller.ScreenAskController` 用后台线程 + Qt
信号完成，本窗只负责展示。

彩蛋：等待答复时显示 :func:`pick_loading_icon` 抽到的品牌图标（10% 鲸蛙），
**每次请求抽一次**，整轮保持同一只，不轮播、不每帧重抽。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...contracts.screen import ScreenCapture
from ...media.images import scale_pixmap, screen_dpr
from .brand_icons import load_ds_whale, pick_loading_icon

__all__ = ["DEFAULT_QUESTION", "ScreenAskWindow"]

#: 空输入时发出的默认问法（用户框的是图，没打字也要能直接问）。
DEFAULT_QUESTION = "看看这块区域里是什么，说清内容，能给出判断或建议时就直接给。"

_TITLE_TEXT = "截图问答"
_TITLE_LOGO_BOX = 24   # logo 的边长（逻辑像素；实际出图按屏 DPR 放大）
_MARGIN = 12           # 缺省落点贴屏幕右下的留白
_MIN_W, _MIN_H = 320, 360
_BUBBLE_RADIUS = 10
_FISH_BOX = 22
_FISH_INTERVAL_MS = 50  # 20fps 足够顺滑又省电

_LIGHT = {
    "surface": "#ffffff",
    "text": "#1f2328",
    "hint": "#6b7280",
    "border": "#e2e4e8",
    "divider": "#eceef1",
    "button": "#f0f1f3",
}
_DARK = {
    "surface": "#1c1e26",
    "text": "#ebedf3",
    "hint": "#a0aabe",
    "border": "#3a3a42",
    "divider": "#33333a",
    "button": "#2f3138",
}


def _resolve_palette(widget: QWidget) -> dict:
    """跟着宿主调色板走（窗口底色亮度 < 128 算暗，同主分支口径）。"""
    try:
        color = widget.palette().color(QPalette.ColorRole.Window)
        return _DARK if color.lightness() < 128 else _LIGHT
    except Exception:
        return _LIGHT


class _Bubble(QLabel):
    """一条消息泡（用户靠右、AI 靠左；可选中可复制）。"""

    def __init__(self, text: str, role: str, colors: dict, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName(f"screen-ask-{role}")
        # 模型输出里可能带 <b>/<img> 残片：一律纯文本渲染（AutoText 会把本地
        # 路径图片加载出来——那是隐私面，不是样式面）。
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        background = "#1677e8" if role == "user" else colors["button"]
        foreground = "#ffffff" if role == "user" else colors["text"]
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {foreground};"
            f"  border-radius: {_BUBBLE_RADIUS}px; padding: 7px 10px; font-size: 13px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setProperty("_side", "right" if role == "user" else "left")


class _LoadingFish(QWidget):
    """等待态的品牌图标：轻轻浮动 + 呼吸透明度（图标由 ``start`` 抽定）。

    相位只推动画；素材缺席时回退三点跳动（绝不让「加载动画」自己成为故障点）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-ask-fish")
        self.setFixedSize(_FISH_BOX, _FISH_BOX)
        self._icon = QPixmap()
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_FISH_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self, icon: QPixmap) -> None:
        self._icon = QPixmap() if icon is None else icon
        self._phase = 0.0
        self.update()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def icon(self) -> QPixmap:
        return self._icon

    def _tick(self) -> None:
        self._phase += 0.13
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        icon = self._icon
        if icon.isNull():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1677e8"))
            for index in range(3):
                lift = max(0.0, math.sin(self._phase * 2.2 - index * 0.9)) * 4
                painter.setOpacity(pulse)
                painter.drawEllipse(
                    QRectF(5 + index * 6, 9 - lift, 4, 4)
                )
            painter.end()
            return
        width, height = icon.width(), icon.height()
        if width <= 0 or height <= 0:
            painter.end()
            return
        grow = 1.0 + 0.06 * math.sin(self._phase)
        scale = min(_FISH_BOX / width, _FISH_BOX / height) * grow
        target_w, target_h = width * scale, height * scale
        bob = math.sin(self._phase) * 1.2
        target = QRectF(
            (self.width() - target_w) / 2,
            (self.height() - target_h) / 2 + bob,
            target_w,
            target_h,
        )
        painter.setOpacity(pulse)
        painter.drawPixmap(target, icon, QRectF(icon.rect()))
        painter.end()


class ScreenAskWindow(QFrame):
    """截图问答浮窗（每次 ``start`` 开新会话，窗口本体复用）。"""

    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._capture: ScreenCapture | None = None
        self._messages: list[dict] = []
        self._waiting = False
        self._loading_icon = QPixmap()
        self._drag_offset: QPoint | None = None
        self._user_pos: QPoint | None = None
        self._user_size: QSize | None = None
        self._title_src = QPixmap()
        self._title_scaled: QPixmap | None = None
        self._title_screen_wired = False

        self._palette_colors = _resolve_palette(self)
        self.setObjectName("screen-ask-window")
        self.setWindowTitle(_TITLE_TEXT)
        self.setFrameShape(QFrame.Shape.NoFrame)  # 卡片由 paintEvent 手画
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self._grip = QSizeGrip(self)
        self._grip.resize(16, 16)
        self._build()

    # ---------------------------------------------------------------- 构建

    def _build(self) -> None:
        colors = self._palette_colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        # 标题栏就是品牌标识本身：固定 DS logo 顶掉「截图问答」四字（不随机）。
        # 那四个字留在窗口标题与无障碍名里；素材缺席时退回文字。
        self._title = QLabel(_TITLE_TEXT, self)
        self._title.setObjectName("screen-ask-title")
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._title.setAccessibleName(_TITLE_TEXT)
        header.addWidget(self._title)
        note = QLabel("点「发送」才会把图发给你配置的 AI 服务", self)
        note.setObjectName("screen-ask-note")
        note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header.addWidget(note)
        header.addStretch(1)
        close_button = QPushButton("×", self)
        close_button.setObjectName("screen-ask-close")
        close_button.setFixedSize(24, 24)
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)
        layout.addLayout(header)

        # 缩略图 chip（图躺在输入栏上方；大图横幅会把对话区挤没）
        self._thumb_chip = QFrame(self)
        self._thumb_chip.setObjectName("screen-ask-chip")
        chip_row = QHBoxLayout(self._thumb_chip)
        chip_row.setContentsMargins(6, 4, 8, 4)
        chip_row.setSpacing(8)
        self._thumb = QLabel(self._thumb_chip)
        self._thumb.setObjectName("screen-ask-thumb")
        self._thumb.setFixedSize(40, 40)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip_row.addWidget(self._thumb)
        self._chip_text = QLabel("截图已就位 · 发送时随问题一起给 AI", self._thumb_chip)
        self._chip_text.setObjectName("screen-ask-chip-text")
        chip_row.addWidget(self._chip_text, 1)
        layout.addWidget(self._thumb_chip)

        # 消息列表（视口与宿主都不透明：透明窗上「透明滚动区」会透出桌面）
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("screen-ask-scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._messages_host = QWidget()
        self._messages_host.setObjectName("screen-ask-messages")
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(2, 2, 2, 2)
        self._messages_layout.setSpacing(6)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_host)
        layout.addWidget(self._scroll, 1)

        # 状态行（正在看图 / 失败理由）+ 加载彩蛋
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._fish = _LoadingFish(self)
        self._fish.setVisible(False)
        status_row.addWidget(self._fish)
        self._status = QLabel("", self)
        self._status.setObjectName("screen-ask-status")
        self._status.setVisible(False)
        status_row.addWidget(self._status, 1)
        layout.addLayout(status_row)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit(self)
        self.input.setObjectName("screen-ask-input")
        self.input.setPlaceholderText("问问这张截图…（回车发送）")
        self.input.returnPressed.connect(self.send_current)
        row.addWidget(self.input, 1)
        self._send_button = QPushButton("发送", self)
        self._send_button.setObjectName("screen-ask-send")
        self._send_button.clicked.connect(self.send_current)
        row.addWidget(self._send_button)
        layout.addLayout(row)

        self.setStyleSheet(f"""
            QLabel#screen-ask-title {{
                color: {colors["text"]}; font-size: 13px; font-weight: 600;
            }}
            QLabel#screen-ask-note, QLabel#screen-ask-status {{
                color: {colors["hint"]}; font-size: 11px;
            }}
            QFrame#screen-ask-chip {{
                background: {colors["button"]}; border-radius: 8px;
                border: 1px solid {colors["border"]};
            }}
            QLabel#screen-ask-thumb {{
                background: {colors["divider"]}; border-radius: 6px;
            }}
            QLabel#screen-ask-chip-text {{
                color: {colors["hint"]}; font-size: 11px;
            }}
            QScrollArea#screen-ask-scroll,
            QScrollArea#screen-ask-scroll QWidget#qt_scrollarea_viewport,
            QWidget#screen-ask-messages {{
                background: {colors["surface"]};
            }}
            QScrollArea#screen-ask-scroll QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px;
            }}
            QScrollArea#screen-ask-scroll QScrollBar::handle:vertical {{
                background: {colors["border"]}; border-radius: 4px; min-height: 24px;
            }}
            QScrollArea#screen-ask-scroll QScrollBar::add-line:vertical,
            QScrollArea#screen-ask-scroll QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollArea#screen-ask-scroll QScrollBar::add-page:vertical,
            QScrollArea#screen-ask-scroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QLineEdit#screen-ask-input {{
                background: {colors["button"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]}; border-radius: 8px;
                padding: 6px 10px; font-size: 13px;
            }}
            QLineEdit#screen-ask-input:focus {{ border-color: #1677e8; }}
            QPushButton#screen-ask-send {{
                background: #1677e8; color: #ffffff; border: none;
                border-radius: 8px; padding: 6px 16px; font-size: 13px;
            }}
            QPushButton#screen-ask-send:hover {{ background: #3d8ef0; }}
            QPushButton#screen-ask-send:disabled {{
                background: {colors["button"]}; color: {colors["hint"]};
            }}
            QPushButton#screen-ask-close {{
                border: none; background: transparent;
                color: {colors["hint"]}; font-size: 14px; padding: 0;
            }}
            QPushButton#screen-ask-close:hover {{ color: {colors["text"]}; }}
        """)
        self._refresh_title_icon()

    # ---------------------------------------------------------------- 对外

    def start(self, capture: ScreenCapture, title: str = "") -> None:
        """开新会话：换缩略图、清消息、重置等待态，然后显示并聚焦输入框。"""
        self._capture = capture
        if title:
            self.setWindowTitle(str(title))
        self._thumb.setPixmap(self._thumb_pixmap(capture))
        self._chip_text.setText("截图已就位 · 发送时随问题一起给 AI")
        self.clear_messages()
        self.end_waiting()
        self.input.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def capture(self) -> ScreenCapture | None:
        return self._capture

    def thumbnail(self) -> QPixmap:
        pixmap = self._thumb.pixmap()
        return QPixmap(pixmap) if pixmap is not None else QPixmap()

    def messages(self) -> list[dict]:
        return [dict(item) for item in self._messages]

    def is_waiting(self) -> bool:
        return self._waiting

    def loading_icon(self) -> QPixmap:
        """本轮等待抽中的图标（``begin_waiting`` 抽一次，整轮不变）。"""
        return self._loading_icon

    def send_current(self) -> bool:
        """发送当前输入（空输入走默认问法）；等待中/无截图时拒收。"""
        if self._waiting or self._capture is None:
            return False
        question = self.input.text().strip() or DEFAULT_QUESTION
        self.input.clear()
        self.submitted.emit(question)
        return True

    def begin_waiting(self) -> None:
        """进入等待态：抽一次加载图标、起呼吸动画、锁输入。"""
        self._waiting = True
        self._loading_icon = pick_loading_icon()
        self._fish.start(self._loading_icon)
        self._fish.setVisible(True)
        self._send_button.setEnabled(False)
        self.input.setEnabled(False)
        self._set_status("正在看图…")

    def end_waiting(self, error: str = "") -> None:
        """收口等待态；``error`` 非空时状态行显示失败理由（红色）。"""
        self._waiting = False
        self._fish.stop()
        self._fish.setVisible(False)
        self._send_button.setEnabled(True)
        self.input.setEnabled(True)
        self._set_status(str(error or ""), error=bool(error))
        if not error and self.isVisible():
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def append_user(self, text: str) -> None:
        self._append(str(text or ""), "user")

    def append_assistant(self, text: str) -> None:
        self._append(str(text or ""), "assistant")

    def clear_messages(self) -> None:
        self._messages.clear()
        while self._messages_layout.count() > 1:  # 留住底部 stretch
            item = self._messages_layout.takeAt(0)
            row = item.layout()
            if row is not None:
                while row.count():
                    child = row.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.deleteLater()
            else:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    # ---------------------------------------------------------------- 内部

    def _thumb_pixmap(self, capture: ScreenCapture) -> QPixmap:
        png = bytes(getattr(capture, "png", b"") or b"")
        if not png:
            return QPixmap()
        pixmap = QPixmap()
        try:
            if not pixmap.loadFromData(png, "PNG"):
                return QPixmap()
        except Exception:
            return QPixmap()
        return scale_pixmap(pixmap, 40, screen_dpr(self))

    def _append(self, text: str, role: str) -> None:
        text = text.strip()
        if not text:
            return
        self._messages.append({"role": role, "content": text})
        bubble = _Bubble(text, role, self._palette_colors, self._messages_host)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 4)
        else:
            row.addWidget(bubble, 4)
            row.addStretch(1)
        self._messages_layout.insertLayout(self._messages_layout.count() - 1, row)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())  # 新消息滚到底

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))
        color = "#d9534f" if error else self._palette_colors["hint"]
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")

    # ------------------------------------------------------------ 展示与几何

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 标题栏 logo 按最终落点的屏 DPR 重出（构建时不知道会落哪块屏）。
        self._refresh_title_icon()
        if not self._title_screen_wired:
            handle = self.windowHandle()
            if handle is not None:
                handle.screenChanged.connect(self._on_title_screen_changed)
                self._title_screen_wired = True
        if self._waiting and not self._fish.isVisible():
            self._fish.start(self._loading_icon)
            self._fish.setVisible(True)
        if self._user_size is not None:
            self.resize(self._user_size)
        if self._user_pos is not None:
            self.move(self._user_pos)
            return
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.right() - self.width() - _MARGIN
        y = available.bottom() - self.height() - _MARGIN
        self.move(max(available.left(), x), max(available.top(), y))

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 只停表：等待轮次与图标留着（被收起不是换了件事）。
        self._fish.stop()
        super().hideEvent(event)

    def _on_title_screen_changed(self, _screen) -> None:
        self._refresh_title_icon()

    def _refresh_title_icon(self, dpr: float | None = None) -> None:
        """按当前屏 DPR 出标题栏 logo（固定 DS logo，只重出图、不换素材）。"""
        src = load_ds_whale()
        if src.isNull():
            self._title_src = QPixmap()
            self._title_scaled = None
            self._title.setText(_TITLE_TEXT)
            return
        ratio = self.devicePixelRatioF() if dpr is None else float(dpr)
        scaled = scale_pixmap(src, _TITLE_LOGO_BOX, ratio)
        self._title_src = src
        self._title_scaled = scaled
        self._title.setPixmap(scaled)  # setPixmap 会清掉文字：两态不并存

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._grip.move(self.width() - 16, self.height() - 16)
        if self.isVisible():
            self._user_size = event.size()

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().moveEvent(event)
        if self._drag_offset is not None:
            self._user_pos = event.pos()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 透明背景窗口上 QSS 不画自身背景——卡片手画。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(
            float(rect.x()),
            float(rect.y()),
            float(rect.width()),
            float(rect.height()),
            14.0,
            14.0,
        )
        painter.fillPath(path, QColor(self._palette_colors["surface"]))
        painter.setPen(QColor(self._palette_colors["border"]))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    # ------------------------------------------------------------ 拖拽与键盘

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._user_pos = self.pos()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt 命名
        # 本窗是普通焦点窗（要打字），Esc 直接关；输入框里的 Esc 留给输入框自己。
        if event.key() == Qt.Key.Key_Escape and not self.input.hasFocus():
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
