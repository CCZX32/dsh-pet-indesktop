from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

# 菜单图标槽位：与主分支 `small_icon_size(menu)`（modern 主题 18）一致。
# 24px 的旧值让菜单图标比 13px 文字大近一倍，视觉上「图标压字」。
MENU_ICON_SIZE = 18
_CHECK_SIZE = 14
_CHECK_CACHE: dict[bool, str] = {}


def _render_check(path: Path, color: str) -> None:
    """画一根圆头折线对勾，存成 PNG 供 QSS `url()` 引用。

    QSS 菜单项由样式表引擎绘制，`PE_IndicatorMenuCheckMark` 根本不会回调样式
    （实测 `drawPrimitive` 一次都不进），所以只能给 `QMenu::indicator:checked`
    一张现成图片。
    """
    pixmap = QPixmap(_CHECK_SIZE, _CHECK_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    size = float(_CHECK_SIZE)
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(size * 0.16, size * 0.52),
                QPointF(size * 0.40, size * 0.78),
                QPointF(size * 0.86, size * 0.22),
            ]
        )
    )
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path))


def check_image_path(dark: bool | None = None) -> str:
    """返回当前主题的对勾图片路径（首次调用时生成，之后复用）。"""
    dark = is_dark() if dark is None else bool(dark)
    cached = _CHECK_CACHE.get(dark)
    if cached and Path(cached).exists():
        return cached
    name = "dsh-pet-menu-check-dark-v1.png" if dark else "dsh-pet-menu-check-light-v1.png"
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        try:
            _render_check(path, "#e4e4e9" if dark else "#252525")
        except OSError:
            return ""
    value = path.as_posix()
    _CHECK_CACHE[dark] = value
    return value


# 几何数值对齐主分支 modern 菜单（`pet/context_menus/menu_styles/modern.py`）：
# 行 24px（min-height 18 + 上下各 3）、图标槽 18px、图标左缘 9px、文字缩进 13px。
# 旧的 32px 行 + 30px 缩进让 18px 图标在行里只占 56%，菜单整体也比主分支厚一档。
# 注意：QSS 里不能写 `#` 注释（会被当成 ID 选择器，整条规则失效）。
_LIGHT = """
QMenu {
    background: #ffffff;
    color: #252525;
    border: 1px solid #d8dbe0;
    border-radius: 12px;
    padding: 6px;
    font-size: %(font_size)dpx;
    icon-size: %(icon_size)dpx;
}
QMenu::item {
    min-height: %(min_height)dpx;
    padding: 3px 29px 3px 13px;
    border-radius: 9px;
}
QMenu::item:selected { background: #edf2f7; }
QMenu::item:disabled { color: #a6a8ac; }
QMenu::separator {
    height: 1px;
    background: #eceef1;
    margin: 4px 4px;
}
QMenu::indicator { width: 14px; height: 14px; }
QMenu::icon { left: 9px; }
QMenu::right-arrow { width: 7px; height: 11px; margin-right: 10px; }
"""

_DARK = """
QMenu {
    background: #2a2a30;
    color: #e4e4e9;
    border: 1px solid #45454f;
    border-radius: 12px;
    padding: 6px;
    font-size: %(font_size)dpx;
    icon-size: %(icon_size)dpx;
}
QMenu::item {
    min-height: %(min_height)dpx;
    padding: 3px 29px 3px 13px;
    border-radius: 9px;
}
QMenu::item:selected { background: #3a3a46; }
QMenu::item:disabled { color: #7e7e82; }
QMenu::separator {
    height: 1px;
    background: #3a3a42;
    margin: 4px 4px;
}
QMenu::indicator { width: 14px; height: 14px; }
QMenu::icon { left: 9px; }
QMenu::right-arrow { width: 7px; height: 11px; margin-right: 10px; }
"""


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def menu_stylesheet(dark: bool | None = None, font_size: int = 13) -> str:
    dark = is_dark() if dark is None else bool(dark)
    try:
        size = max(9, min(32, int(font_size)))
    except (TypeError, ValueError):
        size = 13
    qss = (_DARK if dark else _LIGHT) % {
        "font_size": size,
        # 主分支口径：13px 字 → 18px 行。大字号时跟着长，避免文字被 min-height 切掉。
        "min_height": max(18, size + 5),
        "icon_size": MENU_ICON_SIZE,
    }
    image = check_image_path(dark)
    marker = "QMenu::indicator { width: 14px; height: 14px; }"
    if not image or marker not in qss:
        return qss
    extra = (
        marker
        + "\nQMenu::indicator:unchecked { image: none; border: none; background: transparent; }"
        + "\nQMenu::indicator:checked { image: url(%s); }" % image
    )
    return qss.replace(marker, extra)


def menu_text_color() -> str:
    """菜单文字色（与 QSS 的 `QMenu { color: … }` 保持同一份事实来源）。"""
    return "#e4e4e9" if is_dark() else "#252525"


def accent_color() -> str:
    return "#0a84ff"
