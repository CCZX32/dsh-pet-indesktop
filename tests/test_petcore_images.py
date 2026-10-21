"""图片装载的 DPR 口径：高 DPI 屏上不能「先缩到逻辑像素再被放大」。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from petcore.media.images import (
    load_pixmap,
    logical_size,
    physical_side,
    sanitize_dpr,
    scale_pixmap,
)
from petcore.ui.bubble import SpeechBubble
from petcore.ui.easter_egg import EasterEggPopup, load_scaled_pixmap

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_image(path: Path, width: int, height: int) -> Path:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#30a0ff"))
    assert image.save(str(path))
    return path


def test_sanitize_dpr_falls_back_for_garbage() -> None:
    assert sanitize_dpr(1.5) == pytest.approx(1.5)
    assert sanitize_dpr(0) == 1.0
    assert sanitize_dpr(-2) == 1.0
    assert sanitize_dpr("nope") == 1.0
    assert sanitize_dpr(None) == 1.0


def test_physical_side_multiplies_by_the_ratio() -> None:
    assert physical_side(520, 1.0) == 520
    assert physical_side(520, 1.5) == 780
    assert physical_side(320, 2) == 640
    assert physical_side(0, 1.5) == 2


def test_load_pixmap_decodes_at_physical_resolution(app, tmp_path: Path) -> None:
    path = _write_image(tmp_path / "big.png", 1600, 1200)
    pixmap = load_pixmap(path, 520, 1.5)

    assert pixmap is not None
    assert pixmap.devicePixelRatio() == pytest.approx(1.5)
    assert (pixmap.width(), pixmap.height()) == (780, 585)
    assert logical_size(pixmap) == (520, 390)


def test_small_images_keep_their_logical_size_on_hidpi(app, tmp_path: Path) -> None:
    path = _write_image(tmp_path / "small.png", 200, 100)
    pixmap = load_pixmap(path, 520, 1.5)

    assert pixmap is not None
    # 物理像素按 DPR 放大，逻辑尺寸仍是 200x100（不会被 QLabel 缩小）。
    assert (pixmap.width(), pixmap.height()) == (300, 150)
    assert logical_size(pixmap) == (200, 100)


def test_scale_pixmap_applies_the_same_rule_to_existing_pixmaps(app, tmp_path: Path) -> None:
    path = _write_image(tmp_path / "source.png", 1200, 600)
    source = load_pixmap(path, 1200, 1.0)
    assert source is not None

    scaled = scale_pixmap(source, 320, 2.0)
    assert scaled.devicePixelRatio() == pytest.approx(2.0)
    assert (scaled.width(), scaled.height()) == (640, 320)
    assert logical_size(scaled) == (320, 160)


def test_popup_decodes_for_the_screen_ratio(app, tmp_path: Path) -> None:
    path = _write_image(tmp_path / "egg.png", 1600, 1600)
    # QLabel 会把 pixmap 的 DPR 归一化成自身 DPR（offscreen 是 1.0），所以这里
    # 先验证装载函数，再验证弹窗的逻辑尺寸没被 DPR 改变。
    pixmap = load_scaled_pixmap(path, 520, 2.0)
    assert pixmap.devicePixelRatio() == pytest.approx(2.0)
    assert pixmap.width() == 1040  # 520 逻辑像素 × 2

    popup = EasterEggPopup(path, "彩蛋", dpr=2.0)
    try:
        assert popup.device_pixel_ratio == pytest.approx(2.0)
        assert popup.image_label.size().toTuple() == (520, 520)
        assert popup.image_label.pixmap().deviceIndependentSize().width() in (520.0, 1040.0)
    finally:
        popup.close()


def test_bubble_image_decodes_for_the_pet_screen_ratio(app, tmp_path: Path) -> None:
    path = _write_image(tmp_path / "wide.png", 1600, 800)
    scaled = load_pixmap(path, 320, 2.0)
    assert scaled is not None and scaled.width() == 640  # 320 逻辑像素 × 2

    bubble = SpeechBubble()
    try:
        assert bubble.show_image(path, QRect(200, 200, 100, 100), dpr=2.0) is True
        assert bubble.image_label.size().toTuple() == (320 + 2 * 8, 160 + 2 * 8)
    finally:
        bubble.close()
