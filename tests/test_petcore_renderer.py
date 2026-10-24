# -*- coding: utf-8 -*-
"""petcore 帧渲染的物理像素 / DPR 回归。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from petcore.ui.renderer import frame_pixmap


def _qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_frame_pixmap_scales_to_physical_pixels_and_sets_dpr() -> None:
    _qapp()
    image = QImage(100, 50, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    pixmap = frame_pixmap(image, 40, 40, dpr=1.5)

    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (60, 30)
    assert pixmap.devicePixelRatio() == 1.5
    assert round(pixmap.deviceIndependentSize().width()) == 40
    assert round(pixmap.deviceIndependentSize().height()) == 20


def test_frame_pixmap_sanitizes_invalid_dpr_and_preserves_mirror() -> None:
    _qapp()
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(0, 0, Qt.GlobalColor.red)

    pixmap = frame_pixmap(image, 4, 2, mirrored=True, dpr=0)

    assert pixmap is not None
    assert pixmap.devicePixelRatio() == 1.0
    assert pixmap.toImage().pixelColor(3, 0).red() > 200
