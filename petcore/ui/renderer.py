from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


def frame_pixmap(frame, width: int, height: int, *, mirrored: bool = False):
    if frame is None:
        return None
    pixmap = frame if isinstance(frame, QPixmap) else QPixmap.fromImage(frame)
    if pixmap.isNull():
        return None
    scaled = pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if mirrored:
        scaled = scaled.toImage().mirrored(True, False)
        return QPixmap.fromImage(scaled)
    return scaled
