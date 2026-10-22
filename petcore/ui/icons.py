from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
IMAGE_MAX_BYTES = 5 * 1024 * 1024



def _ink() -> QColor:
    app = QApplication.instance()
    if app is None:
        return QColor("#252525")
    color = app.palette().color(QPalette.ColorRole.WindowText)
    if color.lightness() > 160:
        return QColor("#d6d6d6")
    return QColor("#3a3a3a")


def _pixmap(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(_ink())
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return pixmap, painter


def _draw(name: str, painter: QPainter) -> None:
    if name == "character":
        painter.drawEllipse(QRectF(12, 5, 12, 12))
        painter.drawArc(QRectF(7, 16, 22, 16), 0, 180 * 16)
    elif name == "size":
        painter.drawLine(QPointF(18, 6), QPointF(18, 30))
        painter.drawLine(QPointF(12, 12), QPointF(18, 6))
        painter.drawLine(QPointF(24, 12), QPointF(18, 6))
        painter.drawLine(QPointF(12, 24), QPointF(18, 30))
        painter.drawLine(QPointF(24, 24), QPointF(18, 30))
    elif name == "hide":
        painter.drawEllipse(QRectF(6, 11, 24, 14))
        painter.drawEllipse(QRectF(14, 15, 8, 6))
        painter.drawLine(QPointF(9, 27), QPointF(27, 9))
    elif name == "pin":
        painter.drawLine(QPointF(18, 7), QPointF(18, 21))
        painter.drawLine(QPointF(11, 13), QPointF(25, 13))
        painter.drawArc(QRectF(13, 19, 10, 8), 180 * 16, 180 * 16)
        painter.drawLine(QPointF(18, 27), QPointF(18, 32))
    elif name == "pointer":
        path = QPainterPath(QPointF(11, 6))
        path.lineTo(11, 27)
        path.lineTo(17, 21)
        path.lineTo(22, 30)
        path.lineTo(26, 28)
        path.lineTo(21, 19)
        path.lineTo(28, 18)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "autostart":
        painter.drawArc(QRectF(8, 8, 20, 20), 40 * 16, 280 * 16)
        painter.drawLine(QPointF(24, 6), QPointF(28, 10))
        painter.drawLine(QPointF(28, 6), QPointF(24, 10))
    elif name == "corner":
        painter.drawLine(QPointF(9, 12), QPointF(9, 9))
        painter.drawLine(QPointF(9, 9), QPointF(12, 9))
        painter.drawLine(QPointF(27, 24), QPointF(27, 27))
        painter.drawLine(QPointF(27, 27), QPointF(24, 27))
        painter.drawLine(QPointF(9, 24), QPointF(9, 27))
        painter.drawLine(QPointF(9, 27), QPointF(12, 27))
        painter.drawLine(QPointF(27, 12), QPointF(27, 9))
        painter.drawLine(QPointF(27, 9), QPointF(24, 9))
    elif name == "screen":
        painter.drawRoundedRect(QRectF(6, 8, 24, 16), 2, 2)
        painter.drawLine(QPointF(14, 29), QPointF(22, 29))
        painter.drawLine(QPointF(18, 24), QPointF(18, 29))
    elif name == "refresh":
        painter.drawArc(QRectF(8, 8, 20, 20), 30 * 16, 280 * 16)
        painter.drawLine(QPointF(25, 7), QPointF(29, 11))
        painter.drawLine(QPointF(29, 7), QPointF(25, 11))
    elif name == "folder":
        path = QPainterPath(QPointF(7, 12))
        path.lineTo(14, 12)
        path.lineTo(16, 9)
        path.lineTo(27, 9)
        path.lineTo(27, 27)
        path.lineTo(7, 27)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "application":
        for x in (10, 19):
            for y in (10, 19):
                painter.drawRoundedRect(QRectF(x, y, 7, 7), 1, 1)
    elif name == "settings":
        painter.drawEllipse(QRectF(13, 13, 10, 10))
        for angle in range(0, 360, 45):
            from math import cos, radians, sin

            x = 18 + 11 * cos(radians(angle))
            y = 18 + 11 * sin(radians(angle))
            painter.drawEllipse(QRectF(x - 1.6, y - 1.6, 3.2, 3.2))
    elif name == "info":
        painter.drawEllipse(QRectF(8, 8, 20, 20))
        painter.drawLine(QPointF(18, 16), QPointF(18, 24))
        painter.drawEllipse(QRectF(17, 11.5, 2, 2))
    elif name == "quit":
        painter.drawArc(QRectF(10, 9, 16, 16), 120 * 16, 300 * 16)
        painter.drawLine(QPointF(18, 6), QPointF(18, 17))
    elif name == "chat":
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(6, 7, 24, 17), 5, 5)
        painter.drawPath(bubble)
        painter.drawLine(QPointF(12, 24), QPointF(12, 30))
        painter.drawLine(QPointF(12, 30), QPointF(18, 24))
        painter.drawLine(QPointF(11, 13), QPointF(25, 13))
        painter.drawLine(QPointF(11, 17), QPointF(21, 17))
    elif name == "play":
        painter.drawPolygon([QPointF(14, 8), QPointF(28, 18), QPointF(14, 28)])
    elif name == "speed":
        painter.drawArc(QRectF(7, 7, 22, 22), 210 * 16, 120 * 16)
        painter.drawLine(QPointF(18, 18), QPointF(25, 12))
    elif name == "physics":
        path = QPainterPath(QPointF(8, 12))
        for index, x in enumerate((12, 16, 20, 24, 28)):
            path.lineTo(x, 18 if index % 2 == 0 else 10)
        painter.drawPath(path)
        painter.drawEllipse(QRectF(6, 22, 24, 8))
    elif name == "spawn":
        painter.drawEllipse(QRectF(7, 10, 16, 16))
        painter.drawLine(QPointF(25, 8), QPointF(25, 16))
        painter.drawLine(QPointF(21, 12), QPointF(29, 12))
    elif name == "clear":
        painter.drawLine(QPointF(10, 10), QPointF(26, 26))
        painter.drawLine(QPointF(26, 10), QPointF(10, 26))
    elif name == "pause":
        painter.drawLine(QPointF(14, 9), QPointF(14, 27))
        painter.drawLine(QPointF(22, 9), QPointF(22, 27))
    elif name == "network":
        painter.drawEllipse(QRectF(14, 5, 8, 8))
        painter.drawEllipse(QRectF(5, 22, 8, 8))
        painter.drawEllipse(QRectF(23, 22, 8, 8))
        painter.drawLine(QPointF(17, 13), QPointF(10, 22))
        painter.drawLine(QPointF(19, 13), QPointF(26, 22))
        painter.drawLine(QPointF(13, 26), QPointF(23, 26))
    else:
        painter.drawEllipse(QRectF(14, 14, 8, 8))


def icon(name: str, size: int = 36) -> QIcon:
    pixmap, painter = _pixmap(size)
    try:
        _draw(name, painter)
    finally:
        painter.end()
    return QIcon(pixmap)


def image_error(path: Path | str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return "请选择存在的图片文件"
    if candidate.suffix.lower() not in IMAGE_SUFFIXES:
        return "仅支持 PNG、JPG、WebP、BMP、GIF 和 TIFF"
    try:
        if candidate.stat().st_size > IMAGE_MAX_BYTES:
            return "图片文件不能超过 5 MB"
    except OSError:
        return "无法读取图片文件"
    reader = QImageReader(str(candidate))
    if not reader.canRead() or not reader.size().isValid():
        return "图片内容无效或无法解码"
    return ""


def file_icon(path: Path | str, size: int = 36, display: str = "contain") -> QIcon:
    if image_error(path):
        return QIcon()
    pixmap = QPixmap(str(Path(path).expanduser()))
    if pixmap.isNull():
        return QIcon()
    mode = (
        Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if display == "cover"
        else Qt.AspectRatioMode.KeepAspectRatio
    )
    scaled = pixmap.scaled(size, size, mode, Qt.TransformationMode.SmoothTransformation)
    if display == "cover" and (scaled.width() > size or scaled.height() > size):
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        scaled = scaled.copy(x, y, size, size)
    return QIcon(scaled)


def icon_from_spec(spec) -> QIcon:
    if isinstance(spec, dict) and spec.get("kind") == "file":
        return file_icon(
            spec.get("path") or "", display="cover" if spec.get("display") == "cover" else "contain"
        )
    return icon(str(spec or ""))

