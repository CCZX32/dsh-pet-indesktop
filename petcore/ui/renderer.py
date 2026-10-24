from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTransform


def frame_pixmap(
    frame, width: int, height: int, *, mirrored: bool = False, dpr: float = 1.0
):
    if frame is None:
        return None
    pixmap = frame if isinstance(frame, QPixmap) else QPixmap.fromImage(frame)
    if pixmap.isNull():
        return None
    try:
        dpr = float(dpr)
    except (TypeError, ValueError):
        dpr = 1.0
    if dpr <= 0 or dpr != dpr:
        dpr = 1.0
    physical_width = max(1, int(round(width * dpr)))
    physical_height = max(1, int(round(height * dpr)))
    scaled = pixmap.scaled(
        physical_width,
        physical_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if mirrored:
        result = scaled.transformed(QTransform().scale(-1, 1))
    else:
        result = scaled
    result.setDevicePixelRatio(dpr)
    return result
