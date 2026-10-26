"""菜单/侧栏图标口径：18px 槽位 + 整帧素材裁剪适配。

三个用户可见的回归在这里钉住：
1. 图标槽位从 24px 收到 18px（主分支 `small_icon_size(menu)` 同值），但**字形不许被裁**——
   设计稿是 36 单位坐标系，按槽位缩放而不是硬画进 18px 画布；
2. **笔画随画布缩放**：18px 槽位下 ≈0.8px。把笔宽钉成恒 1.6 逻辑像素会让墨量变成
   初版的 1.8–6 倍（`settings` 120 vs 68），桌面观感就是「图标过大」；
3. 动画预览拿到的是一整帧视频画布（640×390 里角色只占中间一小块），直接缩进 18px
   槽位会让角色只剩几个像素；必须先裁 alpha 包围盒再按 1.04 填充率适配。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from petcore.ui.icons import MENU_ICON_SIZE, SIDEBAR_ICON_SIZE, fitted_icon, icon
from petcore.ui.menu_style import menu_stylesheet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _opaque(image: QImage, threshold: int = 20) -> int:
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > threshold
    )


def _alpha_bounds(image: QImage, threshold: int = 20):
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def test_icon_slot_is_the_main_branch_size() -> None:
    assert MENU_ICON_SIZE == 18
    # 侧栏按 16 绘制（主分支 `SIDEBAR_ICON_SIZE`），视图槽位仍是 18。
    assert SIDEBAR_ICON_SIZE == 16


def test_vector_icon_is_scaled_into_the_slot_instead_of_clipped(app) -> None:
    """18px 槽位下字形必须完整落在画布内（旧实现会把 36 单位设计稿裁掉一半）。"""
    pixmap = icon("settings", MENU_ICON_SIZE).pixmap(QSize(MENU_ICON_SIZE, MENU_ICON_SIZE))
    image = pixmap.toImage()
    assert image.size() == QSize(MENU_ICON_SIZE, MENU_ICON_SIZE)
    bounds = _alpha_bounds(image)
    assert bounds is not None, "图标完全空白"
    left, top, right, bottom = bounds
    # 设计稿字形落在 6..30 / 36，缩放后四周应留 2px 左右余量：贴边即被裁。
    assert left >= 1 and top >= 1
    assert right <= MENU_ICON_SIZE - 2 and bottom <= MENU_ICON_SIZE - 2
    # 字形至少占槽位的 55%，否则「18px 图标」看起来只有 10px。
    assert (right - left + 1) >= MENU_ICON_SIZE * 0.55
    assert (bottom - top + 1) >= MENU_ICON_SIZE * 0.55


def test_icon_stroke_scales_with_the_canvas_instead_of_staying_heavy(app) -> None:
    """笔画按设计单位随画布缩放：18px 槽位的墨量必须回到初版量级。

    回归事实：把笔宽钉成恒 1.6 逻辑像素后，18px 下 `settings` 的墨量是 120 个
    不透明像素（初版 68、主分支 121），桌面观感就是「图标又粗又大」。
    这里钉住墨量上限与小槽位（16/14px）的可辨识下限。
    """
    ceilings = {"settings": 90, "chat": 105, "network": 90, "application": 95}
    for name, ceiling in ceilings.items():
        image = icon(name, MENU_ICON_SIZE).pixmap(
            QSize(MENU_ICON_SIZE, MENU_ICON_SIZE)
        ).toImage()
        ink = _opaque(image)
        assert 20 <= ink <= ceiling, f"{name} 墨量 {ink} 超出 {ceiling}（笔画太重）"
    # 侧栏 16px 与控件 14px 档仍要有笔画（地板 0.75px 生效）。
    for slot in (16, 14):
        small = icon("settings", slot).pixmap(QSize(slot, slot)).toImage()
        assert _opaque(small) >= 20
        bounds = _alpha_bounds(small)
        assert bounds is not None and bounds[2] <= slot - 1 and bounds[3] <= slot - 1


def test_glyph_boxes_stay_inside_the_slot(app) -> None:
    """所有字形都要落在画布内（未缩放的 36 单位设计稿会裁掉一半字形）。"""
    names = (
        "character",
        "size",
        "hide",
        "pin",
        "pointer",
        "autostart",
        "corner",
        "screen",
        "refresh",
        "folder",
        "application",
        "settings",
        "info",
        "quit",
        "chat",
        "play",
        "speed",
        "physics",
        "spawn",
        "clear",
        "pause",
        "network",
        "agent",
        "weather",
    )
    for name in names:
        image = icon(name, MENU_ICON_SIZE).pixmap(
            QSize(MENU_ICON_SIZE, MENU_ICON_SIZE)
        ).toImage()
        bounds = _alpha_bounds(image)
        assert bounds is not None, f"{name} 完全空白"
        left, top, right, bottom = bounds
        assert left >= 0 and top >= 0
        assert right <= MENU_ICON_SIZE - 1 and bottom <= MENU_ICON_SIZE - 1


def test_menu_stylesheet_uses_the_18px_icon_slot(app) -> None:
    for dark in (False, True):
        qss = menu_stylesheet(dark, 13)
        # 尺寸走主分支的 `icon-size`（`QMenu::icon { width/height }` 会被 Qt 忽略）。
        assert "icon-size: 18px" in qss
        assert "width: 18px; height: 18px" not in qss
        assert "width: 24px" not in qss


def _frame_with_padding(width: int = 640, height: int = 390, blob=(270, 120, 100, 150)):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#67b7ff"))
    x, y, w, h = blob
    painter.drawEllipse(x, y, w, h)
    painter.end()
    return image


def test_fitted_icon_crops_the_transparent_frame(app) -> None:
    """整帧 640×390、角色只占 100×150：裁剪后角色要占满槽位。"""
    frame = _frame_with_padding()
    fitted = fitted_icon(QPixmap.fromImage(frame), MENU_ICON_SIZE)
    image = fitted.pixmap(QSize(MENU_ICON_SIZE, MENU_ICON_SIZE)).toImage()
    assert image.size() == QSize(MENU_ICON_SIZE, MENU_ICON_SIZE)
    bounds = _alpha_bounds(image)
    assert bounds is not None
    left, top, right, bottom = bounds
    # 未裁剪时角色只有 18*100/640 ≈ 3px 宽、18*150/390 ≈ 7px 高。
    assert (right - left + 1) >= MENU_ICON_SIZE * 0.6
    assert (bottom - top + 1) >= MENU_ICON_SIZE * 0.8
    assert _opaque(image) > 100


def test_fitted_icon_keeps_aspect_ratio(app) -> None:
    """宽角色不该被拉成方形：内容框的宽高比与原素材一致（±1px 取整误差）。"""
    frame = _frame_with_padding(blob=(200, 100, 240, 120))  # 2:1
    image = fitted_icon(QPixmap.fromImage(frame), 36).pixmap(QSize(36, 36)).toImage()
    left, top, right, bottom = _alpha_bounds(image)
    width = right - left + 1
    height = bottom - top + 1
    assert abs(width / height - 2.0) <= 0.35


def test_empty_source_yields_an_empty_icon(app) -> None:
    assert fitted_icon(None, MENU_ICON_SIZE).isNull()
    blank = QImage(64, 64, QImage.Format.Format_ARGB32)
    blank.fill(QColor(0, 0, 0, 0))
    assert fitted_icon(QPixmap.fromImage(blank), MENU_ICON_SIZE).isNull()
