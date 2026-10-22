"""Core 聊天窗口：Markdown 流式渲染 + 输入框 + 历史。

窗口归 core（``ChatPort`` 的唯一实现者）；mod 只发事件，不碰 Qt。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

FLUSH_INTERVAL_MS = 50
MAX_INPUT_LINES = 6
_HINT = "Enter 发送 · Shift+Enter 换行"


def _markdown_for(messages) -> str:
    """把消息列表渲染成一份 Markdown；assistant 内容原样（它本身就是 Markdown）。"""
    blocks: list[str] = []
    for item in messages:
        role = str(item.get("role") or "user")
        text = str(item.get("content") or "")
        if not text:
            continue
        if role == "user":
            blocks.append(f"**我**\n\n{text}")
        elif role == "assistant":
            blocks.append(text)
        elif role == "tool":
            blocks.append(f"> 工具：{text}")
        else:
            blocks.append(f"> {text}")
    return "\n\n---\n\n".join(blocks)


class ChatInput(QPlainTextEdit):
    """Enter 发送、Shift+Enter 换行（多行输入里唯一放行换行的场景）。"""

    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    submitted = Signal(str)
    stop_requested = Signal()
    cleared = Signal()
    session_selected = Signal(str)
    closed = Signal()

    def __init__(
        self,
        *,
        title: str = "AI 对话",
        font_size: int = 13,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 620)
        self.setMinimumSize(420, 420)
        self._messages: list[dict[str, str]] = []
        self._stream_text = ""
        self._streaming = False
        self._pending_dirty = False
        self._last_error = ""

        self.header = QWidget(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 8, 10, 0)
        header_layout.setSpacing(8)
        self.history_combo = QComboBox(self.header)
        self.history_combo.setMinimumWidth(180)
        self.history_combo.activated.connect(self._on_history_selected)
        header_layout.addWidget(self.history_combo, 1)
        self.new_button = QPushButton("新会话", self.header)
        self.new_button.clicked.connect(self._on_new)
        header_layout.addWidget(self.new_button)

        self.transcript = QTextBrowser(self)
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setReadOnly(True)

        self.status_label = QLabel(_HINT, self)
        self.status_label.setObjectName("chatStatus")

        self.input = ChatInput(self)
        self.input.setPlaceholderText("说点什么…（Enter 发送，Shift+Enter 换行）")
        self.input.setFixedHeight(84)
        self.input.submitted.connect(self._on_submit)

        self.send_button = QPushButton("发送", self)
        self.send_button.clicked.connect(self._on_submit)
        self.stop_button = QPushButton("停止", self)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.hide()
        self.clear_button = QPushButton("清空", self)
        self.clear_button.clicked.connect(self._on_clear)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.header)
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self.input)
        layout.addLayout(buttons)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush)

        self.set_font_size(font_size)
        self.setObjectName("chatWindow")

    # ---------------------------------------------------------------- 外观
    def set_font_size(self, size: int) -> None:
        try:
            value = max(10, min(18, int(size)))
        except (TypeError, ValueError):
            value = 13
        self.transcript.setFont(QFont("", value))
        self.input.setFont(QFont("", value))
        self.status_label.setStyleSheet("color:#8b93a1;font-size:%dpx;" % max(9, value - 2))

    def set_error_style(self, on: bool) -> None:
        self.status_label.setStyleSheet(
            ("color:#d9534f;font-size:12px;" if on else "color:#8b93a1;font-size:12px;")
        )

    # ---------------------------------------------------------------- 历史
    def set_history(self, sessions, current_id: str = "") -> None:
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        for session in sessions:
            label = str(getattr(session, "title", "") or "新会话")
            self.history_combo.addItem(f"{label} · {_short_time(getattr(session, 'updated_at', 0))}",
                                       str(getattr(session, "session_id", "")))
        index = self.history_combo.findData(str(current_id))
        if index >= 0:
            self.history_combo.setCurrentIndex(index)
        self.history_combo.blockSignals(False)

    def _on_history_selected(self, index: int) -> None:
        session_id = str(self.history_combo.itemData(index) or "")
        if session_id:
            self.session_selected.emit(session_id)

    def _on_new(self) -> None:
        self.session_selected.emit("")

    # ---------------------------------------------------------------- 内容
    def messages(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._messages]

    def stream_text(self) -> str:
        return self._stream_text

    def is_streaming(self) -> bool:
        return self._streaming

    def load_messages(self, messages) -> None:
        self._messages = [dict(item) for item in messages]
        self._stream_text = ""
        self._streaming = False
        self._render()

    def append_message(self, role: str, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self._messages.append({"role": str(role or "user"), "content": text})
        self._render()

    def begin_stream(self) -> None:
        self._stream_text = ""
        self._streaming = True
        self._set_busy(True)
        self._messages.append({"role": "assistant", "content": ""})
        self._render()

    def append_token(self, delta: str) -> None:
        if not self._streaming:
            self.begin_stream()
        self._stream_text += str(delta or "")
        if self._messages and self._messages[-1].get("role") == "assistant":
            self._messages[-1]["content"] = self._stream_text
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def finish_stream(self, text: str = "") -> None:
        if text:
            self._stream_text = str(text)
        if self._messages and self._messages[-1].get("role") == "assistant":
            self._messages[-1]["content"] = self._stream_text
        self._streaming = False
        self._flush_timer.stop()
        self._render()
        self._set_busy(False)
        self.status_label.setText(_HINT)

    def show_error(self, reason: str, message: str = "") -> None:
        self._last_error = f"{reason}: {message}" if message else str(reason)
        self._streaming = False
        self._flush_timer.stop()
        self._set_busy(False)
        self.set_error_style(True)
        self.status_label.setText(f"出错：{message or reason}")
        self._render()

    def clear(self) -> None:
        self._messages.clear()
        self._stream_text = ""
        self._streaming = False
        self.cleared.emit()
        self._render()

    # ---------------------------------------------------------------- 内部
    def _set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.stop_button.setVisible(busy)
        self.input.setReadOnly(busy)

    def _on_submit(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.submitted.emit(text)

    def _on_clear(self) -> None:
        self.clear()

    def _flush(self) -> None:
        self._render()

    def _render(self) -> None:
        self.transcript.setMarkdown(_markdown_for(self._messages))
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.transcript.setTextCursor(cursor)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closed.emit()
        super().closeEvent(event)


def _short_time(timestamp) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return "刚刚"
    if value <= 0:
        return "刚刚"
    delta = max(0.0, time.time() - value)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    return time.strftime("%m-%d", time.localtime(value))
