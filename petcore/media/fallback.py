from __future__ import annotations

import math

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter


class FallbackClip(QObject):
    frameChanged = Signal(int)
    finished = Signal()
    errorOccurred = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._image = QImage(640, 360, QImage.Format.Format_ARGB32)
        self._image.fill(Qt.GlobalColor.transparent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def frameCount(self) -> int:
        return 0

    def duration(self) -> float:
        return 1.0

    def currentFrameNumber(self) -> int:
        return int(self._phase) % 60

    def currentImage(self):
        return self._image

    def warm_first_frame(self) -> None:
        self._render()

    def start(self) -> bool:
        self._timer.start()
        self._render()
        self.frameChanged.emit(0)
        return True

    def stop(self) -> None:
        self._timer.stop()

    def jumpToFrame(self, index: int) -> bool:
        self._phase = float(index)
        self._render()
        return True

    def set_decode_throttle(self, _divisor: int) -> None:
        return

    def close(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._phase += 1.0
        self._render()
        self.frameChanged.emit(int(self._phase) % 60)

    def _render(self) -> None:
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        offset = math.sin(self._phase / 6.0) * 8
        painter.setBrush(QColor(96, 170, 255, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(250, 120 + int(offset), 140, 150)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawEllipse(280, 160 + int(offset), 22, 26)
        painter.drawEllipse(340, 160 + int(offset), 22, 26)
        painter.setBrush(QColor(40, 60, 90, 230))
        painter.drawEllipse(288, 168 + int(offset), 8, 10)
        painter.drawEllipse(348, 168 + int(offset), 8, 10)
        painter.end()
