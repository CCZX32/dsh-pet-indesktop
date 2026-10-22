"""截屏端口：PNG 在内存里、不落盘、失败给稳定 reason。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from petcore.contracts.screen import ScreenCapture
from petcore.platform.screenshot import (
    ScreenshotError,
    capture_screen,
    data_url,
    grab_screen_image,
)


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    return QApplication.instance() or QApplication([])


class FakeScreen:
    def __init__(self, image: QImage | None = None, name: str = "fake-screen") -> None:
        self.image = image if image is not None else _image()
        self._name = name
        self.calls: list[int] = []

    def name(self) -> str:
        return self._name

    def grabWindow(self, window_id):  # noqa: N802 - Qt API
        self.calls.append(window_id)
        return self.image


def _image(width: int = 40, height: int = 24) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    return image


def test_capture_returns_png_bytes_without_touching_disk(tmp_path: Path) -> None:
    screen = FakeScreen()
    before = list(tmp_path.rglob("*"))
    capture = capture_screen(screen=screen)
    assert isinstance(capture, ScreenCapture)
    assert capture.png.startswith(b"\x89PNG")
    assert (capture.width, capture.height) == (40, 24)
    assert capture.screen_name == "fake-screen"
    assert screen.calls == [0]
    assert list(tmp_path.rglob("*")) == before


def test_data_url_is_inline_png() -> None:
    capture = ScreenCapture(png=b"abc", width=1, height=1)
    url = data_url(capture)
    assert url.startswith("data:image/png;base64,")
    assert url.endswith("YWJj")


def test_empty_screen_reports_a_stable_reason() -> None:
    empty = QImage()
    with pytest.raises(ScreenshotError) as caught:
        capture_screen(screen=FakeScreen(empty))
    assert caught.value.reason == "capture_failed"


def test_explicit_screen_wins_and_window_screen_is_the_fallback() -> None:
    own = FakeScreen(name="own")
    other = FakeScreen(name="other")

    class Window:
        def screen(self):
            return own

    assert capture_screen(Window(), screen=other).screen_name == "other"
    assert capture_screen(Window()).screen_name == "own"


class PixmapScreen(FakeScreen):
    """真实 Qt 的 ``QScreen.grabWindow`` 返回 QPixmap（Qt6），不是 QImage。"""

    def grabWindow(self, window_id):  # noqa: N802 - Qt API
        self.calls.append(window_id)
        return QPixmap.fromImage(self.image)


def test_grab_screen_image_normalizes_a_qpixmap_to_device_pixels() -> None:
    """冻结帧必须是 QImage/DPR=1，否则覆盖层 drawImage 抛 TypeError（灰屏）。"""
    image, target = grab_screen_image(PixmapScreen())

    assert isinstance(image, QImage)
    assert image.devicePixelRatio() == 1.0
    assert (image.width(), image.height()) == (40, 24)
    assert target is not None


def test_capture_screen_accepts_a_qpixmap_grab() -> None:
    capture = capture_screen(screen=PixmapScreen())

    assert capture.png.startswith(b"\x89PNG")
    assert (capture.width, capture.height) == (40, 24)
