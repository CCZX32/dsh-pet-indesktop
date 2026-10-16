"""The author page is a read-only page in both settings variants."""
from __future__ import annotations

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog
from pet.settings_about import AboutPage

app = QApplication.instance() or QApplication([])


def test_about_actions_remain_visible_on_dark_surfaces():
    original = app.palette()
    palette = QPalette(original)
    palette.setColor(QPalette.ColorRole.Window, QColor("#202024"))
    app.setPalette(palette)
    page = AboutPage()
    try:
        button = page.findChild(QPushButton)
        image = button.icon().pixmap(24, 24).toImage()
        pixels = [image.pixelColor(x, y) for y in range(image.height()) for x in range(image.width())]
        assert any(color.alpha() > 200 and color.lightness() > 180 for color in pixels)
    finally:
        page.deleteLater()
        app.setPalette(original)
        app.processEvents()


@pytest.mark.parametrize("include_ai", [True, False])
def test_about_page_accounts_copy_links_and_config_are_consistent(tmp_path, monkeypatch, include_ai):
    cfg = Config(base=tmp_path)
    dialog = ModernSettingsDialog(cfg, include_ai=include_ai)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    previous_clipboard = app.clipboard().text()
    try:
        dialog.show()
        app.processEvents()
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        assert labels[-2:] == ["更新", "关于"]
        dialog.select_page("关于")
        app.processEvents()
        page = dialog.pages.currentWidget()
        before = copy.deepcopy(cfg.data)
        for platform, handle in [("BiliBili", "@張墨林"), ("BiliBili", "@快乐小咸鱼a"),
                                 ("抖音", "@Eager"), ("GitHub", "@MerZlin")]:
            assert any(label.text() == handle for label in page.findChildren(QLabel))
            button = next(button for button in page.findChildren(QPushButton)
                          if button.accessibleName() == f"复制 {platform} 账号 {handle}")
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert app.clipboard().text() == handle
        link = next(button for button in page.findChildren(QPushButton)
                    if button.accessibleName() == "打开 GitHub 主页")
        QTest.mouseClick(link, Qt.MouseButton.LeftButton)
        assert opened == ["https://github.com/MerZlin"]
        assert cfg.data == before
    finally:
        app.clipboard().setText(previous_clipboard)
        dialog.deleteLater()
        app.processEvents()
