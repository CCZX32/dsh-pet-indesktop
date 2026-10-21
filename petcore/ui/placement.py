from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


def place_beside_pet(widget: QWidget, anchor: QWidget | None, *, gap: int = 24) -> None:
    if not isinstance(anchor, QWidget) or not anchor.isVisible():
        return
    rect = anchor.frameGeometry()
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    size = widget.size()
    x = rect.right() + gap
    if x + size.width() > available.right():
        x = rect.left() - gap - size.width()
    x = max(available.left(), min(available.right() - size.width(), x))
    y = max(available.top(), min(available.bottom() - size.height(), rect.top()))
    widget.move(QPoint(x, y))
