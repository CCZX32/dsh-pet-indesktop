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


# ------------------------------------------------------------------ dHash


def _stripe_image(width: int = 9, height: int = 8) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFF000000)
    for y in range(height):
        for x in range(width // 2, width):
            image.setPixelColor(x, y, 0xFFFFFFFF)
    return image


def test_dhash_is_zero_for_a_flat_image() -> None:
    from petcore.platform.image_hash import dhash

    return_value = dhash(_image(64, 48))
    assert return_value == 0
    assert dhash(None) == 0
    assert dhash(QImage()) == 0


def test_dhash_marks_the_stripe_transition() -> None:
    from petcore.platform.image_hash import dhash

    fingerprint = dhash(_stripe_image())
    expected = sum(1 << (row * 8 + 3) for row in range(8))
    assert fingerprint == expected


def test_hamming_distance_between_fingerprints() -> None:
    from petcore.platform.image_hash import hamming_distance

    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0, 0b1011) == 3


# ------------------------------------------------------------------ 窗口抓图

def _solid(width: int = 200, height: int = 100) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF224466)
    return image


def test_capture_window_gives_the_physical_rect_to_the_grabber() -> None:
    from petcore.platform.image_hash import dhash
    from petcore.platform.screenshot import capture_window

    seen: list[tuple[int, int, int, int]] = []
    frame = _solid()

    def grabber(rect):
        seen.append(tuple(rect))
        return frame

    capture = capture_window(
        (20, 10, 100, 50), hwnd=7, app_info="code.exe | main.py", grabber=grabber
    )

    assert seen == [(20, 10, 100, 50)], "物理矩形不许再乘 DPR"
    assert (capture.width, capture.height) == (200, 100)
    assert capture.hwnd == 7
    assert capture.app_info == "code.exe | main.py"
    assert capture.screen_name == ""
    assert capture.dh_hash == dhash(frame)


def test_capture_window_rejects_an_empty_rect() -> None:
    from petcore.platform.screenshot import capture_window

    with pytest.raises(ScreenshotError):
        capture_window((0, 0, 0, 10), hwnd=1, grabber=lambda rect: _solid())


def test_capture_window_rejects_an_empty_frame() -> None:
    from petcore.platform.screenshot import capture_window

    with pytest.raises(ScreenshotError):
        capture_window((0, 0, 10, 10), grabber=lambda rect: QImage())


def test_capture_window_rejects_a_rect_outside_the_desktop() -> None:
    from petcore.platform.screenshot import (
        ScreenshotError as WindowError,
        _virtual_screen_rect,
        capture_window,
    )

    if _virtual_screen_rect() is None:
        pytest.skip("no virtual screen metrics on this platform")
    with pytest.raises(WindowError):
        capture_window((1_000_000, 1_000_000, 100, 100), grabber=lambda rect: _solid())


def test_capture_window_clamps_a_rect_that_leaves_the_desktop() -> None:
    from petcore.platform.screenshot import _virtual_screen_rect, capture_window

    virtual = _virtual_screen_rect()
    if virtual is None:
        pytest.skip("no virtual screen metrics on this platform")
    x, y, width, height = virtual
    seen: list[tuple[int, int, int, int]] = []

    def grabber(rect):
        seen.append(tuple(rect))
        return _solid(32, 32)

    capture = capture_window((x, y, width + 400, 200), grabber=grabber)
    assert seen and seen[0][2] == width, "右边缘必须被裁到虚拟桌面内"
    assert seen[0][3] == 200
    assert (capture.width, capture.height) == (32, 32)


def test_gdi_grab_returns_real_pixels_on_windows() -> None:
    import sys

    from petcore.platform.screenshot import _grab_desktop_rect

    if sys.platform != "win32":
        pytest.skip("GDI path is Windows-only")
    image = _grab_desktop_rect((0, 0, 64, 48))
    assert not image.isNull()
    assert (image.width(), image.height()) == (64, 48)


def test_sample_window_returns_a_small_fingerprint() -> None:
    import sys

    from petcore.platform.screenshot import sample_window

    if sys.platform != "win32":
        pytest.skip("GDI path is Windows-only")
    fingerprint, width, height = sample_window((0, 0, 800, 600))
    assert isinstance(fingerprint, int)
    assert 0 <= fingerprint < (1 << 64)
    assert 0 < width <= 192 and 0 < height <= 192


# ------------------------------------------------------------------ 视觉输入封顶（DPI）


def test_shrink_png_caps_the_physical_long_edge() -> None:
    from petcore.platform.screenshot import shrink_png

    image = QImage(2000, 1000, QImage.Format.Format_RGB32)
    image.fill(0xFF334455)
    from petcore.platform.screenshot import encode_png

    png = encode_png(image)
    shrunk = shrink_png(png, max_edge=1024)
    result = QImage.fromData(shrunk, "PNG")
    assert (result.width(), result.height()) == (1024, 512)


def test_shrink_png_keeps_small_or_broken_images_untouched() -> None:
    from petcore.platform.screenshot import encode_png, shrink_png

    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0xFF000000)
    png = encode_png(image)
    assert shrink_png(png, max_edge=1024) == png
    assert shrink_png(b"not-a-png", max_edge=1024) == b"not-a-png"
    assert shrink_png(b"", max_edge=1024) == b""


def test_shrink_png_is_independent_of_device_pixel_ratio() -> None:
    """封顶按物理像素：同一张图在 1x/1.5x/2x 屏上送模型的像素预算一致。"""
    from petcore.platform.screenshot import encode_png, shrink_png

    image = QImage(3000, 2000, QImage.Format.Format_RGB32)
    image.fill(0xFF102030)
    png = encode_png(image)
    sizes = []
    for dpr in (1.0, 1.5, 2.0):
        copy = QImage.fromData(png, "PNG")
        copy.setDevicePixelRatio(dpr)
        shrunk = QImage.fromData(shrink_png(encode_png(copy), max_edge=1024), "PNG")
        sizes.append((shrunk.width(), shrunk.height()))
    assert sizes == [(1024, 682)] * 3


def test_capture_desktop_covers_the_virtual_screen() -> None:
    import sys

    from petcore.platform.screenshot import _virtual_screen_rect, capture_desktop

    virtual = _virtual_screen_rect()
    if virtual is None:
        pytest.skip("no virtual screen metrics on this platform")
    capture = capture_desktop()
    assert (capture.width, capture.height) == (virtual[2], virtual[3])
    assert capture.png.startswith(b"\x89PNG")
