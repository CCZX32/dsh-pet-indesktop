# -*- coding: utf-8 -*-
"""「快速识屏」结果浮层：可复制、Esc 可关、可拖可缩、贴边、不抢焦点（offscreen）。

面板是四条截图链路共同的落点，它的契约有五条，逐条都有对应用例：

1. **可复制**：OCR 文本 / 问答答复靠鼠标点按钮进剪贴板——面板是
   ``WS_EX_NOACTIVATE``（``WindowDoesNotAcceptFocus``）窗，用户没法用
   Ctrl+C，复制入口必须是一个鼠标可点的按钮（主按钮是 accent 蓝）；
2. **Esc 可关**：同上，面板拿不到键盘焦点，Esc 只能走应用级过滤器；而过滤器
   **绝不吞事件**（返回 False），所以"关面板"永远不挡主人的其它 Esc 语义；
3. **贴边**：锚在岛旁，越界夹回当刻可用几何——不许跑到屏幕外；
4. **不抢焦点**：显示本身不得激活窗口（``WA_ShowWithoutActivating``），
   否则用户正在打的字会被截断；
5. **可拖动 / 可缩放**（2026-10-14 实机反馈后加的）：标题栏拖动 + 右下角
   ``QSizeGrip``；用户调过的尺寸/位置是他要的，复用同一件面板时不许被排版没收。

纪律：offscreen，同步直调，不 sleep 赌时序。
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QSizeGrip,
    QWidget,
)

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


def _drag(widget, start, end) -> None:
    """按住 ``start`` 拖到 ``end``（局部坐标；全局坐标 = 窗口位置 + 局部坐标）。

    真实现读的是 ``event.globalPosition()``，所以这里必须把两套坐标都给对：
    只给局部坐标的话"按下点"与"窗口位置"的差值算错，一次拖拽会跳着走。
    """
    origin = widget.pos()

    def _pos(local):
        return QPointF(origin.x() + local[0], origin.y() + local[1])

    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(*start), _pos(start),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(*end), _pos(end),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(*end), _pos(end),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    widget.mousePressEvent(press)
    widget.mouseMoveEvent(move)
    widget.mouseReleaseEvent(release)


def _style_rule(stylesheet: str, selector: str) -> str:
    """从 QSS 里抠出某个选择器的规则体（按选择器断言，不比对整份样式表）。"""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", stylesheet)
    assert match is not None, f"样式表里没有 {selector} 的规则"
    return match.group(1)


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


def test_copy_is_the_accent_button(qapp):
    """复制是面板的主按钮：accent 蓝（与图里/问答浮窗同一支 #1677e8）。

    只比对"有背景色"是不够的——读 QSS 里**那条规则**，才不会因为别处
    也出现过同一个色值而自证通过。
    """
    panel = ScreenResultPanel()
    rule = _style_rule(panel.styleSheet(), "QPushButton#screen-result-copy")

    assert "#1677e8" in rule
    assert panel.copy_button().objectName() == "screen-result-copy"
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


def test_the_panel_lands_below_the_selection_it_came_from(qapp):
    """定位契约（round 2 实机反馈）：给选区就落在选区正下方，不再甩到屏幕角落。

    落点是"这块图的下文"，用户的视线不用在选区和屏幕角落之间来回跳。
    """
    from pet.screen_capture.session import SelectionRect

    rect = SelectionRect(200, 200, 300, 100)
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字"), below=rect)

    geo = panel.geometry()
    assert geo.top() >= rect.y + rect.height, "面板压在选区上了"
    assert abs(geo.center().x() - (rect.x + rect.width // 2)) <= 2, "没有对齐选区中线"
    panel.close_panel()


def test_the_selection_beats_the_anchor_and_the_screen_corner(qapp):
    """选区优先级最高：同一次展示既给锚（岛）又给选区时，跟选区。

    （锚/角落是"没有选区上下文"时的退路——两套口径混用会让结果卡在岛边、问答窗
    在选区边，用户看到的是同一张图的两个落点。）
    """
    from pet.screen_capture.session import SelectionRect

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    anchor = QWidget()
    anchor.setGeometry(available.right() - 40, available.bottom() - 20, 40, 20)
    rect = SelectionRect(120, 120, 260, 80)

    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字"),
                      anchor, below=rect)

    geo = panel.geometry()
    assert abs(geo.center().x() - (rect.x + rect.width // 2)) <= 2
    assert geo.top() >= rect.y + rect.height
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
    """定高按内容实测，**复用同一件**照样跟随：涨、封顶、落都钉住。

    面板是复用件（presenter 只造一件，每张结果原地换内容），所以这条必须在
    **同一个实例**上量——"每次换张新的量一量"会把复用路径整个漏掉。

    2026-10-14 起面板有最小高度（``QSizeGrip`` 要抓得住一个像样的窗口），所以
    "空结果比一行结果矮"这条老断言不再成立：地板以下的一切都停在地板上。

    （无裁切由同一份度量保证，视觉证据是离屏截图 probe_panel_ocr.png：
    四行中文完整可见、没有滚动条。）

    历史：这条曾经真红过——首张结果是矮结果时，实例被钉死在 140 px，后面的长文本
    只能靠滚动条读（``show_near`` 的 ``_applying_size`` 挡不住首次 show 的补投递
    resize，排版尺寸被当成了"用户拉的尺寸"）。现在那一环已修好，这条用例连
    "再换回短结果要收回去"一起钉住，防止再退回去。
    """
    panel = ScreenResultPanel()
    floor = panel.minimumHeight()

    panel.show_result(ScreenResult(title="截图提取文字", status="本地文字识别引擎尚未接入"))
    empty_h = panel.height()
    panel.show_result(ScreenResult(title="截图提取文字", primary="一行文字"))
    one_line_h = panel.height()
    panel.show_result(ScreenResult(title="截图提取文字", primary="行\n" * 8))
    many_lines_h = panel.height()
    panel.show_result(ScreenResult(title="截图问答", primary="答" * 4000))
    capped_h = panel.height()
    panel.show_result(ScreenResult(title="截图提取文字", primary="一行文字"))
    shrunk_h = panel.height()

    assert empty_h == one_line_h == floor, "地板以内的短内容都停在最小高度"
    assert one_line_h < many_lines_h <= capped_h
    assert capped_h <= 240 + 120            # 上限附近，不无限拉高
    assert shrunk_h == one_line_h, "复用同一件时尺寸没跟着内容收回来"
    panel.close_panel()


def test_the_continue_button_needs_an_image_and_hands_it_over_with_the_text(qapp):
    """「继续提问…」是把结果卡接回问答浮窗的入口（图 + 已识别文字）。

    两条都要钉：没有图时**不出现**（没有上下文的"继续问"是空转），有图时点了
    要把（图, 正文）原样交出去——面板自己不打开浮窗，那是编排层的事。
    """
    seen: list[tuple] = []
    panel = ScreenResultPanel()
    image = QImage(12, 9, QImage.Format.Format_RGB32)
    image.fill(QColor(1, 2, 3))

    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字"))
    assert panel.continue_button().isVisibleTo(panel) is False

    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字", image=image),
                      on_continue_ask=lambda img, text: seen.append((img, text)))
    assert panel.continue_button().isVisibleTo(panel) is True
    panel.continue_button().click()

    assert seen == [(image, "识别到的文字")]
    panel.close_panel()


# ------------------------------------------------- 渐进式结果卡片（2026-10-14 round 3）


def _loading(panel):
    """面板上的加载动画控件（objectName 固定；画的**内容**随美术迭代）。

    曾经是三点跳动，现在是项目吉祥物的小鱼摆尾——所以用例只钉"这个控件在、
    计时器在跑、它真的画了东西"，不钉具体形状。
    """
    area = panel.findChild(QWidget, "screen-result-loading")
    assert area is not None, "面板上没有加载动画控件"
    return area


def test_a_loading_result_shows_the_animation_and_hides_the_actions(qapp):
    """过程态卡片：正文区摆加载动画，复制/语言行/状态文字一律收起。

    实机反馈"等待白屏像卡死"：等待期间要给"在跑"的信号，而不是一句文案。
    """
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图翻译", status="正在翻译…", force_panel=True,
                                   loading=True, language_selector=True),
                      on_language_change=lambda _target: None)

    animation = _loading(panel)
    assert animation.isVisibleTo(panel) is True
    assert animation._timer.isActive() is True, "过程态的动画必须真的在跑"
    assert panel.copy_button().isVisibleTo(panel) is False
    assert panel.language_row().isVisibleTo(panel) is False
    status = panel.findChild(QLabel, "screen-result-status")
    assert status.isVisibleTo(panel) is False, "文案位让给动画（有字也不摆）"
    assert panel.continue_button().isVisibleTo(panel) is False
    panel.close_panel()


def test_a_loading_result_actually_paints_something(qapp):
    """不只是摆了个空控件：动画真的画在面板上（否则"等待白屏"照旧）。

    只断"控件可见 + 计时器在跑"会漏掉"画了个空白"这种失败——那时动画是个空框，
    用户看到的仍是白屏，正是本轮要解决的问题。（实测踩到过：美术换了一版动画，
    ``paintEvent`` 里用了一个没 import 的符号，控件在、计时器在跑、一个像素没画。）
    """
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", force_panel=True, loading=True))
    panel.show()

    canvas = _render(panel, background=QColor(255, 255, 255))
    area = _loading(panel).geometry()
    pixels = [canvas.pixelColor(x, y).getRgb()
              for x in range(area.x(), area.x() + area.width())
              for y in range(area.y(), area.y() + area.height())]

    assert any(pixel != (255, 255, 255, 255) for pixel in pixels), "动画区是一片空白"
    accent = QColor("#1677e8").getRgb()
    assert any(pixel[:3] == accent[:3] for pixel in pixels), "没画出产品的 accent 色"
    panel.close_panel()


def test_a_loading_result_keeps_the_primary_text_it_already_has(qapp):
    """翻译第二段：原文已就位就留着（只是复制按钮收起），动画摆在它下面。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图翻译", primary="Hello world",
                                   primary_label="原文", force_panel=True, loading=True))

    assert panel.primary_text() == "Hello world"
    assert panel.primary_text() != ""
    assert _loading(panel).isVisibleTo(panel) is True
    panel.close_panel()


def test_the_terminal_result_stops_and_hides_the_animation(qapp):
    """终态到了：动画停下来并收起（留着滴答就是白耗电）。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", force_panel=True, loading=True))
    animation = _loading(panel)
    assert animation._timer.isActive() is True

    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字",
                                   force_panel=True))

    assert animation.isVisibleTo(panel) is False
    assert animation._timer.isActive() is False, "出结果还在后台滴答"
    assert panel.copy_button().isVisibleTo(panel) is True
    panel.close_panel()


def test_hiding_the_panel_stops_the_animation(qapp):
    """面板收起（Esc / 继续提问 / 手动关）时定时器必须停：不留后台空转。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", force_panel=True, loading=True))
    animation = _loading(panel)
    assert animation._timer.isActive() is True

    panel.close_panel()

    assert animation._timer.isActive() is False


# ------------------------------------------------------------ 语言行（round 3）


def test_the_language_row_needs_both_the_flag_and_a_callback(qapp):
    """「译为」语言行：只有翻译结果（``language_selector``）**且**编排层给了回调才出现。"""
    panel = ScreenResultPanel()
    translated = ScreenResult(title="截图翻译", primary="Hello world",
                              secondary="你好，世界", language_selector=True,
                              force_panel=True)

    panel.show_result(translated)
    assert panel.language_row().isVisibleTo(panel) is False, "没有回调就没有可切换的目标"

    panel.show_result(ScreenResult(title="截图提取文字", primary="识别到的文字",
                                   force_panel=True),
                      on_language_change=lambda _target: None)
    assert panel.language_row().isVisibleTo(panel) is False, "不是翻译结果就不出语言行"

    panel.show_result(translated, on_language_change=lambda _target: None)
    assert panel.language_row().isVisibleTo(panel) is True
    combo = panel.language_combo()
    assert isinstance(combo, QComboBox)
    assert [combo.itemData(index) for index in range(combo.count())] == [
        "auto", "中文", "English", "日本語"]
    assert combo.currentData() == "auto", "缺省是自动检测"
    panel.close_panel()


def test_switching_the_language_reports_the_key(qapp):
    """切换语言行 = 换翻译目标：回调拿到的是 combo 的 ``currentData``（key）。"""
    seen: list[str] = []
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图翻译", primary="Hello world",
                                   secondary="你好，世界", language_selector=True,
                                   force_panel=True),
                      on_language_change=seen.append)

    combo = panel.language_combo()
    combo.setCurrentIndex(2)          # English

    assert seen == ["English"]
    assert combo.currentData() == "English"
    panel.close_panel()


def test_the_language_row_hides_while_loading(qapp):
    """重翻时（过程态）语言行收起：正在跑的时候不给用户再切一次的机会。"""
    seen: list[str] = []
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图翻译", primary="Hello world",
                                   language_selector=True, force_panel=True, loading=True),
                      on_language_change=seen.append)

    assert panel.language_row().isVisibleTo(panel) is False
    assert _loading(panel).isVisibleTo(panel) is True
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


# ------------------------------------------------------- 拖动 / 缩放（2026-10-14）


def test_panel_has_a_translucent_background_and_a_size_grip():
    """真圆角靠"透明窗口 + paintEvent 手画的圆角卡片"；缩放入口是右下角的 ``QSizeGrip``。"""
    panel = ScreenResultPanel()

    assert panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    grip = panel.findChild(QSizeGrip)
    assert grip is not None, "面板右下角没有可抓的缩放手柄"
    assert grip.isVisibleTo(panel) is True
    panel.close_panel()


def test_the_title_bar_drags_the_panel(qapp):
    """标题栏按下即可拖动整块面板（标题/状态标签对鼠标透明，事件落到面板本体）。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="内容"))
    panel.show()
    before = panel.pos()

    _drag(panel, (12, 10), (60, 40))

    assert panel.pos() - before == QPoint(48, 30)
    panel.close_panel()


def test_the_panel_has_no_maximum_width_cap(qapp):
    """``_MAX_WIDTH`` 上限取消：用户把面板拉宽不该被悄悄夹回去。"""
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="内容"))
    panel.show()

    panel.resize(700, 200)

    assert panel.maximumWidth() > 700, "宽度又被写死上限了"
    assert panel.width() == 700
    panel.close_panel()


def test_a_size_the_user_pulled_survives_the_next_result(qapp):
    """grip 拉过的尺寸在下一张结果上沿用——面板是复用件，不该没收用户的调整。

    ``QSizeGrip`` 拖完的结果就是一次 ``resize()``，所以这里直接 ``resize`` 模拟。
    反过来那一半由 ``test_panel_height_tracks_the_content`` 钉住：**排版自己算出来的
    尺寸不许被记成"用户拉的"**（记错了实例就被钉死在首张的尺寸上）。
    """
    panel = ScreenResultPanel()
    panel.show_result(ScreenResult(title="截图提取文字", primary="第一张"))
    panel.show()
    panel.resize(420, 260)

    panel.show_result(ScreenResult(title="截图问答", primary="第二张更长的内容" * 20))

    assert (panel.width(), panel.height()) == (420, 260)
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
    """真圆角 + 主题：卡片是**画出来**的，所以按渲染像素验，不按样式表验。

    （``WA_TranslucentBackground`` 一开，QSS 的 ``background`` 不再落像素——
    卡片底色/描边改由 ``paintEvent`` 手画。写样式表字符串的那版断言曾自证通过，
    实际屏幕上是什么颜色它一句话也没说。）
    """
    light = ScreenResultPanel(style="light")
    dark = ScreenResultPanel(style="dark")

    assert light.style == "light" and dark.style == "dark"
    assert light.styleSheet() != dark.styleSheet()

    light.show_result(ScreenResult(title="截图提取文字", primary="浅色宿主上的结果"))
    assert light.primary_text() == "浅色宿主上的结果"

    assert _card_color(light) == QColor("#ffffff").getRgb()
    assert _card_color(dark) == QColor("#1c1e26").getRgb()
    light.close_panel()
    dark.close_panel()


def _render(widget, background: QColor | None = None) -> QImage:
    canvas = QImage(widget.size(), QImage.Format.Format_ARGB32)
    canvas.fill(background if background is not None else QColor(0, 0, 0, 0))
    painter = QPainter(canvas)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    return canvas


def _card_color(panel) -> tuple:
    return _render(panel).pixelColor(panel.width() // 2, panel.height() // 2).getRgb()


def test_the_card_is_a_rounded_translucent_corner(qapp):
    """角上必须是透的：圆角靠"窗口透明 + 手画圆角矩形"成立。

    不透明背景会把圆角吃成直角白盒（实机"白盒"观感之源），所以这条按像素验：
    角落留得住底下画布的底色、中间是卡片色。
    """
    panel = ScreenResultPanel(style="dark")
    panel.show_result(ScreenResult(title="截图提取文字", primary="内容"))

    canvas = _render(panel, background=QColor(255, 0, 255))

    assert canvas.pixelColor(0, 0).getRgb() == (255, 0, 255, 255), "角上被涂实了，圆角没成形"
    assert canvas.pixelColor(panel.width() // 2, panel.height() // 2).getRgb() != (255, 0, 255, 255)
    panel.close_panel()


def test_loading_animation_alternates_between_brand_icons(qapp):
    """品牌图标对（DS 鲸鱼 ↔ 鲸蛙）：两只素材都在时主角随相位轮换。"""
    from pet.screen_capture import result_panel as rp

    fish = rp._LoadingFish()
    assert len(fish._icons) == 2, "两只品牌素材都应随包在场"
    fish._phase = 0.0
    assert fish._current_icon() is fish._icons[0]
    fish._phase = 3.2   # 过第一个换场点（3.1 ≈ 1.2s）
    assert fish._current_icon() is fish._icons[1]
    fish._phase = 6.3
    assert fish._current_icon() is fish._icons[0]


def test_loading_animation_single_brand_icon_never_alternates(qapp, monkeypatch):
    """只剩一只素材：它单独浮动（不轮换、不出空帧）；全缺席回退三点跳动。"""
    from pet.screen_capture import brand_icons, result_panel as rp
    from PySide6.QtGui import QPixmap

    monkeypatch.setattr(rp, "load_jingwa", lambda: QPixmap())
    fish = rp._LoadingFish()
    assert len(fish._icons) == 1
    fish._phase = 0.0
    solo = fish._current_icon()
    fish._phase = 6.3
    assert fish._current_icon() is solo

    monkeypatch.setattr(rp, "load_ds_whale", lambda: QPixmap())
    fish2 = rp._LoadingFish()
    assert fish2._icons == []
