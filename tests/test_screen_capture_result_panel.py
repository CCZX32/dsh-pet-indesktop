# -*- coding: utf-8 -*-
"""「快速识屏」结果浮层：可复制、Esc 可关、贴边、不抢焦点（offscreen）。

面板是三条截图链路共同的落点，它的契约只有四条，逐条都有对应用例：

1. **可复制**：OCR 文本 / 问答答复靠鼠标点按钮进剪贴板——面板是
   ``WS_EX_NOACTIVATE``（``WindowDoesNotAcceptFocus``）窗，用户没法用
   Ctrl+C，复制入口必须是一个鼠标可点的按钮；
2. **Esc 可关**：同上，面板拿不到键盘焦点，Esc 只能走应用级过滤器；而过滤器
   **绝不吞事件**（返回 False），所以"关面板"永远不挡主人的其它 Esc 语义；
3. **贴边**：锚在岛旁，越界夹回当刻可用几何——不许跑到屏幕外；
4. **不抢焦点**：显示本身不得激活窗口（``WA_ShowWithoutActivating``），
   否则用户正在打的字会被截断。

纪律：offscreen，同步直调，不 sleep 赌时序。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from pet.screen_capture.result_panel import (  # noqa: E402
    SHORT_RESULT_LIMIT,
    SYSTEM_STYLE,
    ScreenResult,
    ScreenResultPanel,
    resolve_style,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _escape_event() -> QKeyEvent:
    return QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


def test_result_summary_is_bounded_to_the_island_line():
    """岛的短文案单行、限长——岛是"一眼"面，不承载长文本。"""
    short = ScreenResult(title="截图提取文字", primary="确定")
    assert short.summary == "确定"

    long_text = "行" * 200
    summary = ScreenResult(title="截图提取文字", primary=long_text).summary
    assert len(summary) <= SHORT_RESULT_LIMIT + 1
    assert summary.endswith("…")

    multiline = ScreenResult(title="截图问答", primary="第一行\n第二行")
    assert "\n" not in multiline.summary


def test_panel_shows_copy_and_close_widgets_for_primary_text():
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字",
                                  status="本地识别 · 5 字"))

    assert panel.title_text() == "截图提取文字"
    assert panel.primary_text() == "识别到的文字"
    assert panel.status_text() == "本地识别 · 5 字"
    assert panel.has_secondary() is False
    assert panel.copy_button().text() == "复制"
    # 关面板的鼠标入口（面板是防抢焦点窗，收不到键盘）：断言它真的建出来了
    assert panel.close_button().objectName() == "screen-result-close"
    panel.close_panel()


def test_copy_button_puts_the_primary_text_on_the_clipboard():
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="要复制的文字"))

    assert panel.copy_primary() is True
    assert QApplication.clipboard().text() == "要复制的文字"
    # 空文本不冒充成功（否则用户以为复制到了，粘出来却是上一次的内容）
    panel.show_result(ScreenResult(title="截图提取文字", primary="   "))
    assert panel.copy_primary() is False
    panel.close_panel()


def test_secondary_slot_appears_only_for_bilingual_results():
    """双语对照位：无译文时不占地方，有译文时两个槽各自可复制。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图翻译", primary="Hello world",
                                   secondary="你好，世界"))

    assert panel.has_secondary() is True
    assert panel.secondary_text() == "你好，世界"
    assert panel.copy_button().text() == "复制原文"
    assert panel.copy_secondary_button().text() == "复制译文"
    assert panel.copy_secondary() is True
    assert QApplication.clipboard().text() == "你好，世界"

    panel.show_result(ScreenResult(title="截图翻译", primary="Hello world"))
    assert panel.has_secondary() is False
    panel.close_panel()


def test_panel_never_steals_focus_and_esc_closes_it_without_swallowing():
    panel = ScreenResultPanel()
    assert panel.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    assert Qt.WindowType.WindowDoesNotAcceptFocus in panel.windowFlags()

    panel.show_result(ScreenResult(title="截图提取文字", primary="内容"))
    panel.show()
    app = QApplication.instance()
    assert app is not None

    # Esc 走应用级过滤器（面板是防抢焦点窗，收不到键盘焦点）：关掉面板，
    # 但**不吞**事件——别的窗口要用 Esc（弹弓取消 / 关设置页）照旧收得到。
    # 这里按真实投递路径验：事件发给另一个窗口，过滤器顺手关面板，事件继续
    # 走到目标自己手里（probe 记到就算没被吞）。
    received: list[int] = []

    class _Probe(QWidget):
        def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
            received.append(event.key())
            super().keyPressEvent(event)

    probe = _Probe()
    probe.show()
    QApplication.sendEvent(probe, _escape_event())
    assert received == [Qt.Key.Key_Escape]
    assert panel.isVisible() is False
    probe.deleteLater()

    # 非 Esc 的按键一律直通
    other = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    assert panel.eventFilter(panel, other) is False
    panel.close_panel()


def test_panel_docks_beside_the_anchor_and_stays_inside_the_screen():
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()

    anchor = QWidget()
    anchor.setGeometry(available.right() - 40, available.bottom() - 20, 40, 20)
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图问答", primary="答" * 400))
    panel.show_near(anchor)

    rect = panel.frameGeometry()
    assert rect.left() >= available.left()
    assert rect.top() >= available.top()
    assert rect.right() <= available.right()
    assert rect.bottom() <= available.bottom()
    assert panel.width() <= available.width()
    assert panel.height() <= available.height()

    # 锚缺席时也不许把面板丢到屏幕外（回落到右下角）
    panel.show_near(None)
    rect = panel.frameGeometry()
    assert available.contains(rect)
    panel.close_panel()
    anchor.deleteLater()


def test_panel_flips_above_an_anchor_that_sits_on_the_bottom_edge():
    """屏幕边缘翻转：锚（灵动岛）贴底时，面板往**上**弹而不是压出屏外。"""
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()

    anchor = QWidget()
    anchor.setGeometry(available.right() - 40, available.bottom() - 20, 40, 20)
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图问答", primary="答" * 400))
    panel.show_near(anchor)

    rect = panel.frameGeometry()
    assert rect.bottom() <= anchor.geometry().top(), "贴底的锚点没有把面板翻到上方"
    assert rect.bottom() <= available.bottom()
    panel.close_panel()
    anchor.deleteLater()


def test_empty_result_renders_without_crashing():
    """空输入（引擎没认到文字 / 引擎缺席）：面板照旧能开，复制如实返回 False。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", status="本地文字识别引擎尚未接入"))
    assert panel.primary_text() == ""
    assert panel.secondary_text() == ""
    assert panel.has_secondary() is False
    assert panel.copy_primary() is False
    assert panel.status_text() == "本地文字识别引擎尚未接入"
    panel.close_panel()


def test_panel_height_tracks_the_content():
    """定高按内容实测：空的比一行矮、多行的更高、超长封顶（滚动条接管）。

    （无裁切由同一份度量保证，视觉证据是离屏截图 probe_panel_ocr.png：
    四行中文完整可见、没有滚动条。）
    """
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", status="本地文字识别引擎尚未接入"))
    empty_h = panel.height()

    panel.show_result(ScreenResult(title="截图提取文字", primary="一行文字"))
    one_line_h = panel.height()

    panel.show_result(ScreenResult(title="截图提取文字", primary="行\n" * 8))
    many_lines_h = panel.height()

    panel.show_result(ScreenResult(title="截图问答", primary="答" * 4000))
    capped_h = panel.height()

    assert empty_h < one_line_h < many_lines_h <= capped_h
    assert capped_h <= 240 + 120            # 上限附近，不无限拉高
    panel.close_panel()


def test_close_panel_detaches_the_escape_filter_and_can_be_reused():
    """面板是复用件：关掉之后过滤器要摘干净，再展示一次照旧好使。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="第一次"))
    panel.show()
    panel.close_panel()
    assert panel.isVisible() is False

    panel.show_result(ScreenResult(title="截图提取文字", primary="第二次"))
    panel.show()
    assert panel.isVisible() is True
    assert panel.primary_text() == "第二次"
    assert panel.eventFilter(panel, _escape_event()) is False
    assert panel.isVisible() is False
    panel.close_panel()


# ------------------------------------------------- 主题（2026-10-13 交叉审查 m2）


def _palette(window: QColor):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    return palette


def test_style_follows_the_host_palette_unless_it_is_pinned(qapp):
    """``_STYLES["light"]`` 以前是死代码（style 缺省写死 dark，没人传得进来）。

    现在缺省/``system`` 按宿主调色板判——判据与菜单层同一条（窗口底色亮度）。
    """
    dark_host = _palette(QColor(24, 26, 32))
    light_host = _palette(QColor(245, 246, 248))

    assert resolve_style(None, dark_host) == "dark"
    assert resolve_style(SYSTEM_STYLE, light_host) == "light"
    assert resolve_style("", light_host) == "light"
    # 明确指定的一律照用（宿主是暗色也让用户/宿主选浅色）
    assert resolve_style("light", dark_host) == "light"
    assert resolve_style("dark", light_host) == "dark"
    # 不认识的值不许抛：面板样式不该成为一次截图失败的理由
    assert resolve_style("neon", light_host) == "light"


def test_light_panel_is_reachable_and_renders_the_light_palette(qapp):
    light = ScreenResultPanel(style="light")
    dark = ScreenResultPanel(style="dark")

    assert light.style == "light" and dark.style == "dark"
    assert "#ffffff" in light.styleSheet()
    assert "#1c1e26" in dark.styleSheet()

    light.show_result(ScreenResult(title="截图提取文字", primary="浅色宿主上的结果"))
    assert light.primary_text() == "浅色宿主上的结果"
    light.close_panel()
