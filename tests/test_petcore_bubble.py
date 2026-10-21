from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.bubble import SpeechBubble
from petcore.ui.pet_window import PetWindow


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.pets = None
        self.tray = None

    def characters(self):
        return list(self._characters)

    def build_menu(self, parent=None):
        return None

    def open_settings(self, initial_page=None):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        return None


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    config = Config(tmp_path)
    instance = PetWindow(config, tmp_path, FakeHost([fallback()]))
    instance.start(fallback())
    instance.move(200, 420)
    yield instance
    instance.shutdown()


def _write_image(path: Path, width: int = 400, height: int = 200) -> Path:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#30a0ff"))
    assert image.save(str(path))
    return path


def test_bubble_follows_the_pet_when_the_window_moves(app, window) -> None:
    window.say("跟着我")
    bubble = window.bubble
    assert bubble.isVisible() is True
    assert bubble.is_showing_image() is False
    before = bubble.pos()

    window.move(window.x() + 60, window.y())
    app.processEvents()

    anchor = window.bubble_anchor_rect()
    assert bubble.pos() != before
    assert bubble.x() == pytest.approx(before.x() + 60, abs=2)
    assert bubble.y() == pytest.approx(before.y(), abs=2)
    assert not bubble.geometry().intersects(anchor), "气泡不得压住头框"


def test_reposition_is_skipped_when_nothing_changed(app, window) -> None:
    window.say("不动")
    bubble = window.bubble
    second_anchor = window.bubble_anchor_rect()
    bubble.move(bubble.x() + 7, bubble.y() + 7)
    moved = bubble.pos()
    bubble.reposition(second_anchor)
    assert bubble.pos() == moved, "锚点与尺寸都没变时不应重排"


def test_show_image_switches_content_and_scales(app, window, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "egg.png", width=400, height=200)
    bubble = window.bubble
    anchor = window.bubble_anchor_rect()

    bubble.show_image(image_path, anchor, caption="厉害了我的鲸")

    assert bubble.isVisible() is True
    assert bubble.is_showing_image() is True
    assert bubble.caption_label.isVisible() is True
    assert bubble.caption_label.text() == "厉害了我的鲸"
    pixmap = bubble.image_label.pixmap()
    assert pixmap.width() == 320
    assert pixmap.height() == 160
    assert not bubble.geometry().intersects(anchor), "图片气泡不得压住头框"

    bubble.show_text("回到文字", anchor)
    assert bubble.is_showing_image() is False
    assert bubble.label.isVisible() is True
    assert bubble.image_label.isVisible() is False


def test_show_image_accepts_a_pixmap(app, window) -> None:
    pixmap = QPixmap(500, 500)
    pixmap.fill(QColor("#ff8800"))
    bubble = window.bubble
    bubble.show_image(pixmap, window.bubble_anchor_rect())
    assert bubble.is_showing_image() is True
    shown = bubble.image_label.pixmap()
    assert max(shown.width(), shown.height()) <= 320


def test_bubble_repositions_after_scale_change(app, window) -> None:
    window.say("放大也要跟住")
    bubble = window.bubble
    before = bubble.pos()
    window.set_scale(1.1, persist=False)
    app.processEvents()
    assert bubble.isVisible() is True
    assert bubble.pos() != before
    assert not bubble.geometry().intersects(window.bubble_anchor_rect())


def test_standalone_bubble_defaults_to_text(app) -> None:
    bubble = SpeechBubble()
    try:
        assert bubble.is_showing_image() is False
        assert bubble.text_scale() == pytest.approx(1.0)
    finally:
        bubble.close()


def test_set_text_scale_enlarges_the_text_style(app) -> None:
    bubble = SpeechBubble()
    try:
        bubble.show_text("放大一点", QRect(200, 400, 80, 80))
        before = bubble.label.styleSheet()
        assert "font-size:13px" in before
        assert "padding:10px 14px" in before
        height_before = bubble.height()

        bubble.set_text_scale(2.0)

        assert bubble.text_scale() == pytest.approx(2.0)
        after = bubble.label.styleSheet()
        assert "font-size:26px" in after
        assert "padding:20px 28px" in after
        assert "font-size:24px" in bubble.caption_label.styleSheet()
        assert bubble.height() > height_before, "字号变大后气泡要重新 adjustSize"
        assert bubble.isVisible() is True
        assert not bubble.geometry().intersects(bubble.anchor())
    finally:
        bubble.close()


def test_set_text_scale_is_clamped(app) -> None:
    bubble = SpeechBubble()
    try:
        bubble.set_text_scale(10.0)
        assert bubble.text_scale() == pytest.approx(3.0)
        assert "font-size:39px" in bubble.label.styleSheet()
        bubble.set_text_scale(float("nan"))
        assert bubble.text_scale() == pytest.approx(1.0)
        assert "font-size:13px" in bubble.label.styleSheet()
    finally:
        bubble.close()


def test_show_image_respects_the_image_scale(app, window) -> None:
    bubble = window.bubble
    anchor = window.bubble_anchor_rect()
    pixmap = QPixmap(1280, 640)
    pixmap.fill(QColor("#30a0ff"))

    assert bubble.show_image(pixmap, anchor) is True
    assert bubble.image_label.pixmap().size().toTuple() == (320, 160)

    assert bubble.show_image(pixmap, anchor, image_scale=2.0) is True
    assert bubble.image_label.pixmap().size().toTuple() == (640, 320)
    assert not bubble.geometry().intersects(anchor)

    # 超过 3.0 的系数被钳位：最大边 = 320 × 3
    assert bubble.show_image(pixmap, anchor, image_scale=10.0) is True
    assert bubble.image_label.pixmap().size().toTuple() == (960, 480)


def test_text_and_image_content_do_not_leak_into_each_other(app, window, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "egg.png", width=400, height=200)
    bubble = window.bubble
    anchor = window.bubble_anchor_rect()

    assert bubble.show_image(image_path, anchor, caption="带说明") is True
    bubble.show_text("回到文字", anchor)
    assert bubble.is_showing_image() is False
    assert bubble.image_label.isVisible() is False
    assert bubble.image_label.pixmap().isNull()
    assert bubble.caption_label.isVisible() is False
    assert bubble.caption_label.text() == ""

    bubble.show_image(image_path, anchor)
    assert bubble.is_showing_image() is True
    assert bubble.label.isVisible() is False
    assert bubble.label.text() == ""


def test_window_applies_and_persists_text_scale(app, tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("bubble_text_scale", 150)
    instance = PetWindow(config, tmp_path, FakeHost([fallback()]))
    instance.start(fallback())
    try:
        assert instance.bubble.text_scale() == pytest.approx(1.5)
        assert "font-size:20px" in instance.bubble.label.styleSheet()

        instance.set_text_scale(200, persist=False)
        assert config.get("bubble_text_scale") == 200
        assert instance.bubble.text_scale() == pytest.approx(2.0)

        # 设置页只写配置：下一条气泡要读到新字号
        config.set("bubble_text_scale", 75)
        instance.say("配置改了")
        assert instance.bubble.text_scale() == pytest.approx(0.75)
    finally:
        instance.shutdown()


def test_hidden_pet_does_not_show_a_bubble(app, window) -> None:
    window.say("先冒一个泡")
    assert window.bubble.isVisible()
    assert window.bubble.label.text() == "先冒一个泡"

    window.set_visible(False)
    assert window.isVisible() is False
    assert window.bubble.isVisible() is False

    window.say("隐藏后不该冒泡")
    assert window.bubble.isVisible() is False
    assert window.bubble.label.text() == "先冒一个泡"


def test_bubble_keeps_the_pet_layer(app, window) -> None:
    """置顶必须跟着宿主走：图片气泡比文字气泡大，掉层会直接被桌宠盖住。"""
    bubble = window.bubble
    assert bubble.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    window.set_always_on_top(False, persist=False)
    assert bubble.host_on_top() is False
    assert not (bubble.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    window.set_always_on_top(True, persist=False)
    assert bubble.host_on_top() is True
    assert bubble.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_text_and_image_bubbles_share_the_same_window(app, window, tmp_path) -> None:
    image = _write_image(tmp_path / "egg.png", 640, 480)
    window.say("文字气泡")
    text_window = id(window.bubble)
    flags_before = window.bubble.windowFlags()

    assert window.show_image(image, "配图") is True
    assert id(window.bubble) == text_window
    assert window.bubble.windowFlags() == flags_before
    assert window.bubble.is_showing_image() is True
