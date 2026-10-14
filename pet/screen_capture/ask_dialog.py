# -*- coding: utf-8 -*-
"""截图问答浮窗：带图的迷你对话窗（图在输入栏上方，打字发问，可多轮）。

为什么是一个对话窗而不是"框选 → 直接发图 → 弹答案"（2026-10-14 实机反馈后
重做）：

- 一次性问答把"问什么"的权利没收了——用户框的是图，想问的却是自己的事
  （"这段报错什么意思"/"这页说的是哪天截止"），答案面不该替用户出题；
- 一层系统 Yes/No 确认框既突兀又与操作条语义重复。**浮窗本身就是确认面**：
  图躺在输入栏上方，发不发、发什么文字，都是用户亲手点「发送」那一刻决定的；
  打开窗口一个字节都不出网。

隐私不变量（与 ``vision_bridge`` 同一约定）：选区图只在 :meth:`start_with_image`
时编码成内存 JPEG（不落盘），唯一的网络出口是用户配置的视觉/聊天 API，且只在
点「发送」时发生。消息列表如实呈现每一次发出去的内容（首轮 = 图 + 问题）。

线程纪律：发送在后台线程（``VisionConversation.ask`` 同步阻塞、超时 60s 起），
结果经 Qt 信号回 GUI 线程；窗口对象只在 GUI 线程碰。
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QPixmap
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

from .result_panel import _STYLES, resolve_style
from .vision_bridge import VisionConversation

log = logging.getLogger("dsh-pet-standalone")

__all__ = ["ScreenAskDialog"]

_MARGIN = 12          # 缺省落点贴屏幕右下的留白
_MIN_W, _MIN_H = 320, 360
_THUMB_MAX_H = 140    # 输入栏上方缩略图的最大高度
_BUBBLE_RADIUS = 10


class _Bubble(QLabel):
    """一条消息泡（用户靠右、AI 靠左；可选中可复制——问答窗里的文本不许只读死）。"""

    def __init__(self, text: str, role: str, colors: dict, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName(f"screen-ask-{role}")
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bg = "#1677e8" if role == "user" else colors["button"]
        fg = "#ffffff" if role == "user" else colors["text"]
        side = "right" if role == "user" else "left"
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: {_BUBBLE_RADIUS}px;"
            f"  padding: 7px 10px; font-size: 13px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setProperty("_side", side)


class ScreenAskDialog(QFrame):
    """截图问答浮窗（每次 ``start_with_image`` 开新会话，窗口本体复用）。

    ``config`` 是宿主配置面（与 ``ChatVisionChannel`` 同一个 duck-type）；
    ``conversation_factory`` 是测试替身入口（默认 :class:`VisionConversation`）。
    """

    _reply_ready = Signal(str)    # 后台线程 → GUI：答复到了
    _reply_failed = Signal(str)   # 后台线程 → GUI：失败理由（人话）

    def __init__(self, config, parent: QWidget | None = None, *,
                 style: str | None = None, conversation_factory=None) -> None:
        super().__init__(parent)
        self._config = config
        self._conversation_factory = (
            conversation_factory if conversation_factory is not None else VisionConversation
        )
        self._conversation = None
        self._sending = False
        self._drag_offset: QPoint | None = None
        self._user_pos: QPoint | None = None   # 用户拖过的位置（复用窗体时沿用）
        self._user_size: QSize | None = None

        self._style = resolve_style(style, self.palette())
        self._palette = _STYLES[self._style]
        self.setObjectName("screen-ask-dialog")
        self.setWindowTitle("截图问答")
        self.setFrameShape(QFrame.Shape.NoFrame)  # 卡片由 paintEvent 手画（同结果面板）
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self._build()
        self._grip = QSizeGrip(self)
        self._grip.resize(16, 16)
        self._reply_ready.connect(self._on_reply)
        self._reply_failed.connect(self._on_error)

    # ---------------------------------------------------------------- 构建

    def _build(self) -> None:
        colors = self._palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 标题栏（拖拽把手：标签对鼠标透明，按下落在面板上）
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("截图问答", self)
        title.setObjectName("screen-ask-title")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header.addWidget(title)
        note = QLabel("点「发送」才会把图发给你配置的 AI 服务", self)
        note.setObjectName("screen-ask-note")
        note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header.addWidget(note)
        header.addStretch(1)
        close_btn = QPushButton("×", self)
        close_btn.setObjectName("screen-ask-close")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # 缩略图卡（输入栏上方——"这张图是接下来提问的上下文"）
        self._thumb = QLabel(self)
        self._thumb.setObjectName("screen-ask-thumb")
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setFixedHeight(_THUMB_MAX_H)
        layout.addWidget(self._thumb)

        # 消息列表
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("screen-ask-scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._messages_host = QWidget()
        self._messages = QVBoxLayout(self._messages_host)
        self._messages.setContentsMargins(2, 2, 2, 2)
        self._messages.setSpacing(6)
        self._messages.addStretch(1)
        self._scroll.setWidget(self._messages_host)
        layout.addWidget(self._scroll, 1)

        # 状态行（正在看图 / 失败理由）
        self._status = QLabel("", self)
        self._status.setObjectName("screen-ask-status")
        self._status.setVisible(False)
        layout.addWidget(self._status)

        # 输入行
        row = QHBoxLayout()
        row.setSpacing(8)
        self._input = QLineEdit(self)
        self._input.setObjectName("screen-ask-input")
        self._input.setPlaceholderText("问问这张截图…（回车发送）")
        self._input.returnPressed.connect(self.send_current)
        row.addWidget(self._input, 1)
        self._send_btn = QPushButton("发送", self)
        self._send_btn.setObjectName("screen-ask-send")
        self._send_btn.clicked.connect(self.send_current)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        self.setStyleSheet(f"""
            QLabel#screen-ask-title {{
                color: {colors["text"]}; font-size: 13px; font-weight: 600;
            }}
            QLabel#screen-ask-note, QLabel#screen-ask-status {{
                color: {colors["hint"]}; font-size: 11px;
            }}
            QLabel#screen-ask-thumb {{
                background: {colors["button"]}; border-radius: 8px;
            }}
            QScrollArea#screen-ask-scroll {{ background: transparent; }}
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

    # ---------------------------------------------------------------- 对外

    def start_with_image(self, image: QImage, context_text: str = "") -> None:
        """开新会话：换缩略图、清消息、重置会话上下文，然后显示并聚焦输入框。

        ``context_text``：随首轮发出的参考资料（现在是结果面板带来的 OCR 文字）。
        """
        if image is None or image.isNull():
            raise ValueError("截图问答收到空图")
        try:
            conversation = self._conversation_factory(self._config)
            conversation.start(image, context_text=context_text)
        except Exception:
            # 通道建不起来（没配置/配置坏了）：如实报错，窗口照样不开。
            log.exception("截图问答：会话通道创建失败")
            raise
        self._conversation = conversation
        thumb = QPixmap.fromImage(image).scaledToHeight(
            _THUMB_MAX_H, Qt.TransformationMode.SmoothTransformation)
        self._thumb.setPixmap(thumb)
        self._clear_messages()
        self._set_status("")
        self._set_sending(False)
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def send_current(self) -> bool:
        """发送当前输入（空输入走默认问法）。发送中/无会话时拒收，返回是否受理。"""
        if self._sending or self._conversation is None:
            return False
        text = self._input.text().strip()
        conversation = self._conversation
        question = text or "看看这块区域里是什么，说清内容，能给出判断或建议时就直接给。"
        self._append_bubble(question, "user")
        self._input.clear()
        self._set_sending(True)
        self._set_status("正在看图…")
        threading.Thread(
            target=self._ask_worker, args=(conversation, question),
            daemon=True, name="pet-screen-ask",
        ).start()
        return True

    # ---------------------------------------------------------------- 会话收口

    def _ask_worker(self, conversation, question: str) -> None:
        try:
            reply = conversation.ask(question)
        except Exception as exc:
            log.exception("截图问答：发送失败")
            self._reply_failed.emit(str(exc) or type(exc).__name__)
            return
        self._reply_ready.emit(reply)

    def _on_reply(self, reply: str) -> None:
        self._set_sending(False)
        self._set_status("")
        text = str(reply or "").strip()
        self._append_bubble(text or "（模型没说话，再试一次？）", "assistant")

    def _on_error(self, reason: str) -> None:
        self._set_sending(False)
        self._set_status(f"发送失败：{reason}")

    # ---------------------------------------------------------------- 界面小件

    def _append_bubble(self, text: str, role: str) -> None:
        bubble = _Bubble(text, role, self._palette, self._messages_host)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 4)
        else:
            row.addWidget(bubble, 4)
            row.addStretch(1)
        self._messages.insertLayout(self._messages.count() - 1, row)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())   # 新消息滚到底

    def _clear_messages(self) -> None:
        while self._messages.count() > 1:    # 留住底部 stretch
            item = self._messages.takeAt(0)
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.deleteLater()
            else:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def _set_sending(self, sending: bool) -> None:
        self._sending = sending
        self._send_btn.setEnabled(not sending)
        self._input.setEnabled(not sending)

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    # ------------------------------------------------------------ 展示与几何

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
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

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._grip.move(self.width() - 16, self.height() - 16)
        if self.isVisible():
            self._user_size = event.size()

    def moveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().moveEvent(event)
        if self._drag_offset is not None:
            self._user_pos = event.pos()

    # ------------------------------------------------------------ 拖拽与键盘

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 透明背景窗口上 QSS 不画自身背景（同结果面板的实测结论）——卡片手画。
        from PySide6.QtGui import QColor, QPainter, QPainterPath

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()),
                            float(rect.width()), float(rect.height()), 14.0, 14.0)
        painter.fillPath(path, QColor(self._palette["surface"]))
        painter.setPen(QColor(self._palette["border"]))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._user_pos = self.pos()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt 命名)
        # 本窗是普通焦点窗（要打字），Esc 直接关；输入框里的 Esc 留给输入框自己。
        if event.key() == Qt.Key.Key_Escape and not self._input.hasFocus():
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
