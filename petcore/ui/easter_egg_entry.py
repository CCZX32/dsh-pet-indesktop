"""彩蛋菜单行：圆形头像 + 标题 + 「请点击」，点击后由菜单关闭再执行。

菜单行的自绘走 ``MenuItem.builder``：``MenuModel._append_item`` 看到 builder
就交给它自己 ``addAction``（``QWidgetAction``），不再生成普通文本项。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget, QWidgetAction

from .. import paths
from ..media.images import screen_dpr
from .easter_egg import DEFAULT_EASTER_EGG_TITLE, SUPPORTED_IMAGE_SUFFIXES
from .menu_style import is_dark, menu_text_color

ROW_HEIGHT = 39
AVATAR_SIZE = 27
_HINT_TEXT = "请点击"

#: 图片目录不可用时回退的随包头像目录（相对资源根）。
_FALLBACK_AVATAR_DIR = "big_blue_fat_fish"


def _first_readable_image(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return None
    for path in entries:
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        if QImageReader(str(path)).canRead():
            return path
    return None


def _round_pixmap(pixmap: QPixmap, dpr: float = 1.0) -> QPixmap:
    """裁成圆形头像；物理边长按 DPR 放大，避免 1.5 倍屏上发虚。"""
    try:
        ratio = float(dpr)
    except (TypeError, ValueError):
        ratio = 1.0
    if ratio <= 0:
        ratio = 1.0
    side = max(1, int(round(AVATAR_SIZE * ratio)))
    scaled = pixmap.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    left = max(0, (scaled.width() - side) // 2)
    top = max(0, (scaled.height() - side) // 2)
    cropped = scaled.copy(left, top, side, side)
    round_pixmap = QPixmap(side, side)
    round_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(round_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addEllipse(0, 0, side, side)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    round_pixmap.setDevicePixelRatio(ratio)
    return round_pixmap


def avatar_pixmap(window) -> QPixmap | None:
    """彩蛋菜单行的头像：先用彩蛋图片，退回随包素材，再失败就不画。"""
    images: list[Path] = []
    easter = getattr(window, "easter", None)
    lister = getattr(easter, "images", None)
    if callable(lister):
        try:
            images = [Path(item) for item in lister()]
        except Exception:
            images = []
    source = images[0] if images else _first_readable_image(
        paths.legacy_asset_root() / _FALLBACK_AVATAR_DIR
    )
    if source is None:
        return None
    reader = QImageReader(str(source))
    if not reader.canRead():
        return None
    ratio = screen_dpr(window)
    side = max(1, int(round(AVATAR_SIZE * ratio)))
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(
            size.scaled(
                QSize(side, side),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            )
        )
    image = reader.read()
    if image.isNull():
        return None
    return _round_pixmap(QPixmap.fromImage(image), ratio)


def _scaled_font(base: QFont | None, delta: int = 0) -> QFont:
    """从菜单字体派生行内字号（标题 delta=0、提示 delta=-2）。"""
    font = QFont(base) if base is not None else QFont()
    if font.pointSizeF() > 0:
        font.setPointSizeF(max(1.0, font.pointSizeF() + delta))
        return font
    pixels = font.pixelSize()
    font.setPixelSize(max(1, (pixels if pixels > 0 else 13) + delta))
    return font


class EasterEggRow(QWidget):
    """一行彩蛋入口：高度 39px、横向布局，hover 时整行浅色圆角底。"""

    clicked = Signal()

    def __init__(
        self,
        window,
        parent: QWidget | None = None,
        *,
        base_font: QFont | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("easterEggRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ROW_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._window = window

        dark = is_dark()
        hover = "#3a3a46" if dark else "#edf2f7"
        hint_color = "#9a9aa2" if dark else "#8b93a1"
        self.setStyleSheet(
            "QWidget#easterEggRow{background:transparent;border-radius:8px;}"
            "QWidget#easterEggRow:hover{background:%s;}" % hover
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 12, 0)
        layout.setSpacing(8)

        self.avatar_label: QLabel | None = None
        pixmap = avatar_pixmap(window)
        if pixmap is not None:
            self.avatar_label = QLabel(self)
            self.avatar_label.setObjectName("easterEggAvatar")
            self.avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self.avatar_label.setPixmap(pixmap)
            self.avatar_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            layout.addWidget(self.avatar_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(self._title(window), self)
        self.title_label.setObjectName("easterEggRowTitle")
        self.title_label.setFont(_scaled_font(base_font))
        self.title_label.setStyleSheet("color:%s;" % menu_text_color())
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.hint_label = QLabel(_HINT_TEXT, self)
        self.hint_label.setObjectName("easterEggRowHint")
        self.hint_label.setFont(_scaled_font(base_font, -2))
        self.hint_label.setStyleSheet("color:%s;" % hint_color)
        self.hint_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout.addWidget(self.hint_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.clicked.connect(self._trigger)

    @staticmethod
    def _title(window) -> str:
        config = getattr(window, "config", None)
        raw = ""
        if config is not None:
            try:
                raw = str(config.get("easter_egg_title") or "").strip()
            except Exception:
                raw = ""
        return raw or DEFAULT_EASTER_EGG_TITLE

    def _trigger(self) -> None:
        callback = getattr(self._window, "show_easter_egg", None)
        if callable(callback):
            QTimer.singleShot(0, callback)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def build_easter_egg_entry(menu: QMenu, window) -> QWidgetAction:
    """往 ``menu`` 追加彩蛋行并返回该 ``QWidgetAction``。"""
    menu.ensurePolished()
    row = EasterEggRow(window, base_font=menu.font())
    action = QWidgetAction(menu)
    action.setText("彩蛋图片")
    action.setToolTip("点开一张彩蛋图片")
    action.setDefaultWidget(row)
    menu.addAction(action)
    return action
