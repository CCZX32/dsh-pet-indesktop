from __future__ import annotations

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QWidget

# 菜单图标槽位：与主分支 `small_icon_size(menu)`（modern 主题 18）一致。
# 24px 的旧值让菜单图标比 13px 文字大近一倍，视觉上「图标压字」。
MENU_ICON_SIZE = 18
#: 勾选层挂在 QMenu 上的属性名（避免被 GC，也供测试定位）。
CHECK_LAYER_ATTR = "_menuCheckLayer"


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


# 几何数值对齐主分支 modern 菜单（`pet/context_menus/menu_styles/modern.py`）：
# 行 24px（min-height 18 + 上下各 3）、图标槽 18px、图标左缘 9px、文字缩进 13px。
# 旧的 32px 行 + 30px 缩进让 18px 图标在行里只占 56%，菜单整体也比主分支厚一档。
# 注意：QSS 里不能写 `#` 注释（会被当成 ID 选择器，整条规则失效）。
#
# `QMenu::indicator` 只留 1px 且不画：QMenu 的勾选列与图标列是同一个位置，勾选塞在
# indicator 里 = 勾选项不能有图标（旧实现正是如此，主动识屏/Agent 联动/免打扰全部没
# 图标）。勾选改由 `MenuCheckLayer` 画在行尾（主分支 `ModernCheckLayer` 同口径）。
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
QMenu::indicator { width: 1px; height: 1px; image: none; }
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
QMenu::indicator { width: 1px; height: 1px; image: none; }
QMenu::right-arrow { width: 7px; height: 11px; margin-right: 10px; }
"""


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
    return qss


def menu_text_color() -> str:
    """菜单文字色（与 QSS 的 `QMenu { color: … }` 保持同一份事实来源）。"""
    return "#e4e4e9" if is_dark() else "#252525"


def accent_color() -> str:
    return "#0a84ff"


class MenuCheckLayer(QWidget):
    """行尾勾选层：QSS 的 indicator 让位给图标列，勾选标记自己画。

    主分支 `ModernCheckLayer` 的移植：13px 强调色圆 + 白勾，圆心距行右缘 21px，
    跟随 `aboutToShow` / `toggled` / `triggered` 重画，所以勾选与取消是即时的。
    """

    #: 圆的半径与圆心到行右缘的距离（逻辑 px）。
    RADIUS = 6.5
    RIGHT_INSET = 21.0

    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self.setObjectName("menuCheckLayer")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def sync(self) -> None:
        menu = self.parentWidget()
        if not isinstance(menu, QMenu):
            return
        self.setGeometry(menu.rect())
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        del event
        menu = self.parentWidget()
        if not isinstance(menu, QMenu):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            if not action.isCheckable() or not action.isChecked():
                continue
            rect = menu.actionGeometry(action)
            if not rect.isValid() or rect.isEmpty():
                continue
            center = QPointF(
                max(self.RADIUS, self.width() - self.RIGHT_INSET),
                rect.center().y() + 0.5,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(accent_color()))
            painter.drawEllipse(center, self.RADIUS, self.RADIUS)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor("#ffffff"), 1.55)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(center.x() - 3.7, center.y()),
                        QPointF(center.x() - 1.2, center.y() + 2.4),
                        QPointF(center.x() + 3.8, center.y() - 2.8),
                    ]
                )
            )


def _sync_menu_checks(menu: QMenu) -> None:
    layer = install_check_layer(menu)
    if layer is not None:
        layer.sync()


def install_check_layer(menu: QMenu) -> MenuCheckLayer | None:
    """给菜单（含子菜单）挂行尾勾选层；可重复调用，用于补接后来加进来的项。"""
    if not isinstance(menu, QMenu):
        return None
    layer = getattr(menu, CHECK_LAYER_ATTR, None)
    if not isinstance(layer, MenuCheckLayer):
        layer = MenuCheckLayer(menu)
        setattr(menu, CHECK_LAYER_ATTR, layer)
        menu.aboutToShow.connect(
            lambda menu=menu: QTimer.singleShot(0, menu, lambda: _sync_menu_checks(menu))
        )
        menu.aboutToHide.connect(layer.hide)
        menu.triggered.connect(lambda _action=None, layer=layer: layer.update())
    for action in menu.actions():
        submenu = action.menu()
        if isinstance(submenu, QMenu):
            install_check_layer(submenu)
        if action.isCheckable() and not action.property("menuCheckBound"):
            action.setProperty("menuCheckBound", True)
            action.toggled.connect(layer.update)
    return layer


__all__ = [
    "CHECK_LAYER_ATTR",
    "MENU_ICON_SIZE",
    "MenuCheckLayer",
    "accent_color",
    "install_check_layer",
    "is_dark",
    "menu_stylesheet",
    "menu_text_color",
]
