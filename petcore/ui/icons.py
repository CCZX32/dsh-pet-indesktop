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

from ..media.images import physical_side, sanitize_dpr, screen_dpr

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
IMAGE_MAX_BYTES = 5 * 1024 * 1024

# `_draw()` 里所有坐标都写在这个设计坐标系里（字形大致落在 6..30）。
_GLYPH_UNITS = 36.0
#: 笔画宽度（**设计单位**，随画布等比缩放）。18px 槽位下 ≈0.8px 逻辑像素——与首个
#: 重写版的实际重量一致，也正是用户认作「正常」的那一档。上一版把笔画钉成恒 1.6
#: 逻辑像素（`1.6 / scale` 反向补偿），18px 下墨量是初版的 1.8–6 倍，观感就是
#: 「图标又粗又大」（实测 settings 120 vs 初版 68 个不透明像素）。
_STROKE_UNITS = 1.6
#: 笔画逻辑像素地板：14–16px（侧栏、控件）不再继续变细，否则笔画会糊掉/消失。
_MIN_STROKE_PX = 0.75
# 菜单图标槽位：主分支 `small_icon_size(menu)=18`。
MENU_ICON_SIZE = 18
#: 设置侧栏的**绘制**尺寸（主分支 `settings_widgets.SIDEBAR_ICON_SIZE = 16`）：
#: 位图按 16 画、视图槽位仍按 18 —— 侧栏行高 34px 下这一档最稳。
SIDEBAR_ICON_SIZE = 16



def _ink() -> QColor:
    app = QApplication.instance()
    if app is None:
        return QColor("#252525")
    color = app.palette().color(QPalette.ColorRole.WindowText)
    if color.lightness() > 160:
        return QColor("#d6d6d6")
    return QColor("#3a3a3a")


def _pixmap(size: int, dpr: float = 1.0) -> tuple[QPixmap, QPainter]:
    """按逻辑尺寸 ``size`` 建图；字形仍按 36 单位设计稿绘制。

    两个尺寸口径必须分开：``size`` 是**显示槽位**（菜单 18px、侧栏 16px），
    ``_GLYPH_UNITS`` 是 ``_draw()`` 里写死的设计坐标系。设计稿整体缩放到槽位，
    笔画也按设计单位一起缩放（不是钉死在逻辑像素上）——这样小槽位下笔画自然变细，
    与初版观感一致。
    """
    logical = max(8, int(size))
    ratio = sanitize_dpr(screen_dpr() if dpr is None else dpr)
    physical = max(1, int(round(logical * ratio)))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    # 设计单位 → 设备像素；``scale`` 是设计单位 → 逻辑像素。
    scale = logical / _GLYPH_UNITS
    painter.scale(ratio * scale, ratio * scale)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(_ink())
    pen.setWidthF(max(_STROKE_UNITS, _MIN_STROKE_PX / scale) if scale > 0 else _STROKE_UNITS)
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
    elif name == "agent":
        painter.drawRoundedRect(QRectF(9, 11, 18, 14), 4, 4)
        painter.drawLine(QPointF(18, 11), QPointF(18, 6))
        painter.drawPoint(QPointF(18, 5))
        painter.drawLine(QPointF(14, 17), QPointF(14, 19))
        painter.drawLine(QPointF(22, 17), QPointF(22, 19))
        painter.drawLine(QPointF(12, 25), QPointF(10, 29))
        painter.drawLine(QPointF(24, 25), QPointF(26, 29))
    elif name == "weather":
        painter.drawEllipse(QRectF(6, 7, 13, 13))
        painter.drawRoundedRect(QRectF(11, 16, 19, 12), 6, 6)
    else:
        painter.drawEllipse(QRectF(14, 14, 8, 8))


def icon(name: str, size: int = MENU_ICON_SIZE, dpr: float | None = None) -> QIcon:
    pixmap, painter = _pixmap(size, dpr if dpr is not None else screen_dpr())
    try:
        _draw(name, painter)
    finally:
        painter.end()
    return QIcon(pixmap)


def fitted_icon(
    source, size: int = MENU_ICON_SIZE, dpr: float | None = None
) -> QIcon:
    """把整帧素材裁到不透明范围，再按短边适配进 ``size`` 方形槽位。

    主分支同款两道处理（`pet/context_menus/icons.py:520` 的
    `fitted_pet_pixmap_icon`）：动画帧是整块视频画布（640×390 里角色只占中间
    一小块），直接缩到 18px 菜单槽位会让角色只剩几个像素；另外帧 pixmap 若
    带着 DPR 交给 ``QIcon``，Qt 会按物理像素当逻辑像素算，图标再小一半。
    这里统一 ``setDevicePixelRatio(1.0)`` 后用 alpha 包围盒裁剪，最后画进
    带正确 DPR 的方形画布。

    填充率按主分支口径 ``1.04``（**略微超出**槽位 4%，不是缩小留白）：
    预览图是角色本体，留白会让 18px 槽位里的角色显得比矢量图标小一圈。
    """
    from PySide6.QtGui import QBitmap, QImage, QRegion

    if source is None:
        return QIcon()
    image = source.toImage() if isinstance(source, QPixmap) else source
    if not isinstance(image, QImage) or image.isNull():
        return QIcon()
    # 帧 pixmap 可能保留 DPR=2：先抹平，否则下面按物理像素算尺寸会小一半。
    # 没有 alpha 通道的帧（JPEG / 无透明 PNG）解出来是 RGB32，`createAlphaMask()`
    # 对它返回**空图**——直接当「全透明」会把整帧丢掉，菜单只剩占位图标。
    if not image.hasAlphaChannel():
        bounds_rect = image.rect()
    else:
        if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
            image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            # 整帧全透明 = 没有可预览的内容；返回空图标让调用方保留占位图标，
            # 而不是给一个「看得见槽位、看不见内容」的空白图标。
            return QIcon()
        bounds_rect = bounds
    image = image.copy(bounds_rect)
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return QIcon()

    logical = max(8, int(size))
    ratio = sanitize_dpr(screen_dpr() if dpr is None else dpr)
    physical = max(1, int(round(logical * ratio)))
    canvas = QPixmap(physical, physical)
    canvas.fill(Qt.GlobalColor.transparent)
    canvas.setDevicePixelRatio(ratio)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        extent = logical * 1.04
        scale = min(extent / image.width(), extent / image.height())
        width = image.width() * scale
        height = image.height() * scale
        target = QRectF(
            (logical - width) / 2.0, (logical - height) / 2.0 - 0.2, width, height
        )
        painter.drawImage(target, image)
    finally:
        painter.end()
    return QIcon(canvas)


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


def file_icon(
    path: Path | str, size: int = MENU_ICON_SIZE, display: str = "contain", dpr: float | None = None
) -> QIcon:
    if image_error(path):
        return QIcon()
    ratio = sanitize_dpr(screen_dpr() if dpr is None else dpr)
    pixmap = QPixmap(str(Path(path).expanduser()))
    if pixmap.isNull():
        return QIcon()
    limit = physical_side(size, ratio)
    mode = (
        Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if display == "cover"
        else Qt.AspectRatioMode.KeepAspectRatio
    )
    scaled = pixmap.scaled(limit, limit, mode, Qt.TransformationMode.SmoothTransformation)
    if display == "cover" and (scaled.width() > limit or scaled.height() > limit):
        x = max(0, (scaled.width() - limit) // 2)
        y = max(0, (scaled.height() - limit) // 2)
        scaled = scaled.copy(x, y, limit, limit)
    scaled.setDevicePixelRatio(ratio)
    return QIcon(scaled)


def icon_from_spec(spec, dpr: float | None = None, size: int = MENU_ICON_SIZE) -> QIcon:
    if isinstance(spec, dict) and spec.get("kind") == "file":
        return file_icon(
            spec.get("path") or "",
            size=size,
            display="cover" if spec.get("display") == "cover" else "contain",
            dpr=dpr,
        )
    return icon(str(spec or ""), size=size, dpr=dpr)

