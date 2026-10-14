# -*- coding: utf-8 -*-
"""「快速识屏」结果浮层：岛旁的临时结果面板（可复制 / Esc 可关 / 不抢焦点）。

为什么要有这个面板，而不是全部塞进灵动岛或气泡：

- 岛是"一眼"面（定宽胶囊 + 卡片里两行消息），OCR 出来的一整段文字放不下；
- 气泡（``show_bubble``）是短反馈面，不能选中、不能复制，长文本会在屏上摊开一大片；
- 所以长结果落在一个**跟在岛旁**的临时浮层里：查完就关，不常驻、不进任何列表。

三个硬约束（都在 ``tests/test_screen_capture_result_panel.py`` 里钉死）：

1. **不抢焦点**：窗口带 ``WindowDoesNotAcceptFocus``（= Windows 的
   ``WS_EX_NOACTIVATE``）与 ``WA_ShowWithoutActivating``——主人正在别的窗口打字时
   弹出结果，输入焦点不许被抢走（与灵动岛、桌面通知同口径）。
2. **鼠标交互照常**：防抢焦点窗仍然收得到鼠标事件（岛上的卡片按钮就是先例），
   所以"复制"做成**按钮**而不是指望用户 Ctrl+C——这个窗口拿不到键盘焦点。
3. **Esc 可关**：同上，面板收不到键盘事件，Esc 只能走应用级事件过滤器；过滤器
   **永不吞事件**（恒返回 ``False``）——主人的 Esc 语义（弹弓取消、关设置页）
   一个都不能被结果面板挡住。

隐私：本模块只做展示，不碰像素、不落盘。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

__all__ = ["SHORT_RESULT_LIMIT", "SYSTEM_STYLE", "ScreenResult", "ScreenResultPanel",
           "resolve_style"]

#: 岛上"短结果"的字数上限：超过就只在岛上留个摘要，全文去面板。
SHORT_RESULT_LIMIT = 40

_GAP = 8          # 面板与锚（岛）之间的间距
_MARGIN = 12      # 无锚时贴屏幕边的留白
_MIN_WIDTH = 300
_MAX_WIDTH = 520
_PRIMARY_MIN_H = 56
_PRIMARY_MAX_H = 240
_SECONDARY_MIN_H = 48
_SECONDARY_MAX_H = 160
#: 文本槽定高的安全余量（px）：QPlainTextEdit 的文档行高比 QFontMetrics.lineSpacing
#: 大一点点（中文字形实测约 0.5px/行），不留这点余量末行会被切掉半行。
_TEXT_SAFETY_PX = 6

#: 这些控件里 Esc 有自己的语义（撤销编辑 / 关闭输入），面板不许抢。
_ESC_OWNING_WIDGETS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)

_STYLES = {
    "dark": {
        "surface": "#1c1e26", "text": "#ebedf3", "hint": "#a0aabe",
        "border": "#3a3a42", "divider": "#33333a", "button": "#2f3138",
    },
    "light": {
        "surface": "#ffffff", "text": "#1f2328", "hint": "#6b7280",
        "border": "#e2e4e8", "divider": "#eceef1", "button": "#f0f1f3",
    },
}

#: 宿主没给明确主题时的判定阈值：窗口底色亮度低于它算暗（与菜单层
#: ``context_menus/menu_styles/modern.py`` 的 ``theme == "system"`` 同一口径）。
_DARK_LIGHTNESS = 128


def position_below_rect(widget: QWidget, rect, gap: int = _GAP) -> None:
    """把窗口摆到选区矩形正下方（放不下翻上缘，再不行贴屏幕边）。

    实机反馈（2026-10-14）：结果面板/问答窗落在屏幕角落 = 视线要从选区跳到角落
    再跳回来；跟在选区旁边才是"这块图的下文"。``rect`` 是逻辑像素下的屏幕坐标
    （采集选区就是它）。
    """
    from PySide6.QtCore import QRect

    if rect is None:
        return
    bounds = QRect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    screen = QGuiApplication.screenAt(bounds.center()) or QGuiApplication.primaryScreen()
    available = screen.availableGeometry() if screen is not None else None
    if available is None:
        return
    width, height = widget.width(), widget.height()
    x = bounds.center().x() - width // 2
    y = bounds.bottom() + gap
    if y + height > available.bottom():
        y = bounds.top() - height - gap           # 下方放不下 → 翻上缘
    if y < available.top():
        y = available.bottom() - height - _MARGIN  # 选区贴顶 → 贴屏幕下边
    x = max(available.left(), min(x, available.right() - width))
    y = max(available.top(), min(y, available.bottom() - height))
    widget.move(x, y)

#: ``style`` 参数里代表"跟着宿主走"的取值（含缺省 ``None``）。
SYSTEM_STYLE = "system"


def resolve_style(style: str | None, palette=None) -> str:
    """把 ``style`` 归一成 ``"dark"`` / ``"light"``。

    三档输入：

    - ``"dark"`` / ``"light"``：照用（用户/宿主明确选了）；
    - ``None`` / 空 / ``"system"``：**跟着宿主走**——按宿主调色板判（``palette``
      缺省用 ``QGuiApplication.palette()``），判据与菜单层同一条；
    - 其它不认识的值：同上（不抛异常——面板样式不该成为一次截图失败的理由）。
    """
    key = "" if style is None else str(style).strip().lower()
    if key in _STYLES:
        return key
    if palette is None:
        app = QApplication.instance()
        palette = app.palette() if app is not None else None
    if palette is not None:
        window = palette.color(QPalette.ColorRole.Window)
        return "dark" if window.lightness() < _DARK_LIGHTNESS else "light"
    return "dark"   # 连调色板都问不到（无 QApplication）：退回本片原有的暗色


class _LoadingFish(QWidget):
    """加载动画：DeepSeek 官方鲸鱼轻轻浮动 + 喷泡泡（项目吉祥物；素材
    ``assets/chat/ds_whale.png`` 随包分发，simple-icons CC0 渲出的渐变蓝 PNG）。
    素材缺席时回退为三点跳动（绝不让"加载动画"自己成为故障点）。

    面板是防抢焦点的复用件，动画用自己的 QTimer：``hideEvent``/非 loading 结果
    都会停掉它，绝不会在面板收起后还占着定时器空转。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-result-loading")
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._phase = 0.0
        self._whale = self._load_whale()
        self._timer = QTimer(self)
        self._timer.setInterval(50)   # 20fps 足够顺滑又省电
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _load_whale() -> QPixmap:
        import sys
        from pathlib import Path

        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "chat" / "ds_whale.png")
        candidates.append(Path(__file__).resolve().parents[2] / "assets" / "chat" / "ds_whale.png")
        for path in candidates:
            if path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap
        return QPixmap()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.13
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        phase = self._phase
        cx, cy = self.width() / 2, self.height() / 2 + 10

        if self._whale.isNull():
            # 素材缺席的回退：三点跳动（形状简单但绝不能不画）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1677e8"))
            spacing = 22
            for i in range(3):
                lift = max(0.0, math.sin((phase * 2.2 - i * 0.9))) * 8
                painter.drawEllipse(QPointF(cx + (i - 1) * spacing, cy - 6 - lift), 5, 5)
            painter.end()
            return

        # 泡泡：从鲸鱼头顶（喷水孔位置）往上升、越来越淡
        for i in range(3):
            t = (phase * 0.5 + i / 3.0) % 1.0          # 0..1 循环
            bubble_x = cx - 6 + math.sin(t * math.pi * 2 + i) * 4
            bubble_y = cy - 24 - t * 30
            r = 2.2 + t * 1.8
            if t < 0.2:
                # 最新生的泡泡：实心 accent 蓝（空心描边在小尺寸下会全被抗锯齿
                # 糊掉，实心才有纯 accent 像素——这一点有测试守着）
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#1677e8"))
            else:
                alpha = int(220 * (1.0 - t * 0.75))
                painter.setPen(QPen(QColor(22, 119, 232, alpha), 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(bubble_x, bubble_y), r, r)
            painter.drawEllipse(QPointF(bubble_x, bubble_y), r, r)

        # 鲸鱼：随相位轻轻上下浮动 + 极轻微摇摆（像浮在水里）
        bob = math.sin(phase) * 2.4
        tilt = math.sin(phase * 0.7) * 0.06
        size = 44
        painter.save()
        painter.translate(cx, cy + bob)
        painter.rotate(math.degrees(tilt))
        painter.drawPixmap(-size // 2, -size // 2, size, size, self._whale)
        painter.restore()
        painter.end()


@dataclass(frozen=True)
class ScreenResult:
    """一次截图动作的结果（展示层的唯一输入模型）。

    ``primary`` = 主文本（OCR 文字 / 问答答复 / 翻译原文），``secondary`` =
    双语对照的第二槽（译文——翻译已接通：聊天模型文本互译），``status`` =
    一句话口径（"本地识别 · 12 字" / "已翻译 · N 字"），写在标题右侧。

    ``image`` = 这次截下的选区图（纯内存，不落盘）：非空时面板底部出现
    「继续提问…」入口——把图（与已识别文字）带进问答浮窗接着聊（豆包式
    "结果卡底部继续问"的等价物：我们的面板是防抢焦点窗，输入落在问答浮窗里）。
    """

    title: str
    primary: str = ""
    secondary: str = ""
    status: str = ""
    primary_label: str = ""
    secondary_label: str = ""
    force_panel: bool = False
    image: object = None
    #: 翻译结果专用：面板底部出「译为」语言行（切换即重翻，回调由编排层注入）。
    language_selector: bool = False
    #: 过程态占位卡片（"正在识别/翻译"）：True 时正文区摆跳动三点动画，
    #: 不摆文字（实机反馈：等待文字说明看着像卡死，动画才像"在跑"）。
    loading: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.primary.strip() and not self.secondary.strip()

    @property
    def summary(self) -> str:
        """岛的短文案：压平成一行、限长（岛是定宽胶囊，多行会撑坏几何）。"""
        text = " ".join(self.primary.split())
        if not text:
            return " ".join(self.status.split())
        if len(text) <= SHORT_RESULT_LIMIT:
            return text
        return text[:SHORT_RESULT_LIMIT] + "…"


class ScreenResultPanel(QFrame):
    """岛旁的结果浮层（复用一件：每次展示只换内容与位置）。

    ``style`` 三档同 :func:`resolve_style`：``"dark"`` / ``"light"`` 明写，
    ``None``（缺省）/ ``"system"`` 跟着宿主调色板走。**缺省不再是写死的暗色**：
    写死的那一版让 ``_STYLES["light"]`` 成了死代码（浅色宿主上永远弹一块深色
    浮层），现在宿主主题由调用方（``ScreenCapturePresenter``）从配置里读出来传进来。

    可调性（2026-10-14 实机反馈"太丑、不能调"后加的）：

    - **真圆角**：``WA_TranslucentBackground`` 打开 + ``paintEvent`` 手画卡片
      （实测：透明背景窗口上 QSS 的 ``background`` 不落像素，只能靠画）；
      （之前不透明背景把 ``border-radius`` 吃成了直角白盒）；
    - **可拖动**：按住标题栏区域拖（标题/状态标签对鼠标透明，事件落到面板上）；
    - **可缩放**：右下角 ``QSizeGrip``；用户拉过的尺寸在本实例上记住
      （面板是复用件，下一张结果沿用你调好的大小——只记进程内，不碰配置）。
    """

    def __init__(self, parent: QWidget | None = None, *, style: str | None = None) -> None:
        super().__init__(parent)
        self._style = resolve_style(style, self.palette())
        self._palette = _STYLES[self._style]
        self.setObjectName("screen-result-panel")
        self.setWindowTitle("")
        self.setFrameShape(QFrame.Shape.NoFrame)  # 卡片由 paintEvent 手画（见下）
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # 真圆角靠透明背景 + paintEvent 手画卡片；不透明会把圆角吃成直角
        # （实机"白盒"观感之源），而透明窗上 QSS 又不画自身背景（A/B 实测）。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 显示不激活：主人正在打字时不许把焦点抢过来
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setMinimumSize(_MIN_WIDTH, 140)
        self._user_size = None       # 用户用 grip 拉过的尺寸（QSize；进程内记忆）
        self._drag_offset: QPoint | None = None
        self._applying_size = False  # 预留：程序化排版的同步标记
        # 首次 show() 前的 resize 事件会被 Qt 挂起到显示那一刻才投递（那时
        # _applying_size 早复位了），所以"程序化尺寸"要靠值比对而不是旗标——
        # 否则第一张结果的排版尺寸会被误记成用户尺寸，之后每张结果都被钉死在
        # 第一张的高度上（2026-10-14 测试适配期发现的真实缺陷）。
        self._last_programmatic_size = None
        self._escape_installed = False
        self._on_continue_ask = None  # show_result 注入的"继续提问"回调
        self._continue_image = None
        self._on_language_change = None  # show_result 注入的语言行回调
        self._build()
        self._grip = QSizeGrip(self)
        self._grip.setObjectName("screen-result-grip")
        self._grip.resize(16, 16)

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        colors = self._palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel("")
        self._title.setObjectName("screen-result-title")
        self._title.setWordWrap(False)
        # 标题栏同时是拖拽把手：标签对鼠标透明，按下/拖动落到面板本体上。
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header.addWidget(self._title)
        self._status = QLabel("")
        self._status.setObjectName("screen-result-status")
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header.addWidget(self._status)
        header.addStretch(1)
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setObjectName("screen-result-copy")
        self._copy_btn.clicked.connect(self.copy_primary)
        header.addWidget(self._copy_btn)
        self._copy_secondary_btn = QPushButton("复制译文")
        self._copy_secondary_btn.setObjectName("screen-result-copy-secondary")
        self._copy_secondary_btn.clicked.connect(self.copy_secondary)
        self._copy_secondary_btn.setVisible(False)
        header.addWidget(self._copy_secondary_btn)
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("screen-result-close")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.clicked.connect(self.close_panel)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._primary_label = QLabel("")
        self._primary_label.setObjectName("screen-result-slot")
        self._primary_label.setVisible(False)
        layout.addWidget(self._primary_label)
        self._primary_view = self._make_view(_PRIMARY_MIN_H, _PRIMARY_MAX_H)
        layout.addWidget(self._primary_view)

        # 加载动画（过程态占位卡片的正文区；出结果即收起停表）
        self._loading = _LoadingFish(self)
        self._loading.setVisible(False)
        layout.addWidget(self._loading)

        self._divider = QFrame()
        self._divider.setObjectName("screen-result-divider")
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.setFixedHeight(1)
        self._divider.setVisible(False)
        layout.addWidget(self._divider)
        self._secondary_label = QLabel("")
        self._secondary_label.setObjectName("screen-result-slot")
        self._secondary_label.setVisible(False)
        layout.addWidget(self._secondary_label)
        self._secondary_view = self._make_view(_SECONDARY_MIN_H, _SECONDARY_MAX_H)
        self._secondary_view.setVisible(False)
        layout.addWidget(self._secondary_view)

        # 翻译语言行（仅翻译结果出现）：自动检测 / 中文 / English / 日本語
        self._lang_row = QFrame()
        self._lang_row.setObjectName("screen-result-langrow")
        lang_layout = QHBoxLayout(self._lang_row)
        lang_layout.setContentsMargins(0, 0, 0, 0)
        lang_layout.setSpacing(6)
        lang_label = QLabel("译为")
        lang_label.setObjectName("screen-result-slot")
        lang_layout.addWidget(lang_label)
        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("screen-result-lang")
        for key, label in (("auto", "自动检测"), ("中文", "中文"),
                           ("English", "English"), ("日本語", "日本語")):
            self._lang_combo.addItem(label, key)
        self._lang_combo.currentIndexChanged.connect(self._language_changed)
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch(1)
        self._lang_row.setVisible(False)
        layout.addWidget(self._lang_row)

        # 底部「继续提问」入口（有图可带时才出现；豆包式结果卡续聊的等价物）
        self._continue_btn = QPushButton("继续提问…")
        self._continue_btn.setObjectName("screen-result-continue")
        self._continue_btn.setVisible(False)
        self._continue_btn.clicked.connect(self._continue_ask)
        layout.addWidget(self._continue_btn)

        self.setStyleSheet(f"""
            QLabel#screen-result-title {{
                color: {colors["text"]}; font-size: 13px; font-weight: 600;
            }}
            QLabel#screen-result-status, QLabel#screen-result-slot {{
                color: {colors["hint"]}; font-size: 11px;
            }}
            QPlainTextEdit {{
                background: transparent; color: {colors["text"]};
                border: none; font-size: 13px;
                selection-background-color: #1677e8;
            }}
            QPlainTextEdit QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px;
            }}
            QPlainTextEdit QScrollBar::handle:vertical {{
                background: {colors["border"]}; border-radius: 4px; min-height: 24px;
            }}
            QPlainTextEdit QScrollBar::handle:vertical:hover {{
                background: {colors["hint"]};
            }}
            QPlainTextEdit QScrollBar::add-line:vertical,
            QPlainTextEdit QScrollBar::sub-line:vertical {{ height: 0; }}
            QPlainTextEdit QScrollBar::add-page:vertical,
            QPlainTextEdit QScrollBar::sub-page:vertical {{ background: transparent; }}
            QFrame#screen-result-divider {{ background: {colors["divider"]}; border: none; }}
            QPushButton {{
                background: {colors["button"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]}; border-radius: 7px;
                padding: 3px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {colors["hint"]}; }}
            QPushButton#screen-result-copy {{
                background: #1677e8; border-color: #1677e8; color: #ffffff;
            }}
            QPushButton#screen-result-copy:hover {{ background: #3d8ef0; }}
            QPushButton#screen-result-close {{
                padding: 0; font-size: 14px; border: none; background: transparent;
                color: {colors["hint"]};
            }}
            QPushButton#screen-result-close:hover {{ color: {colors["text"]}; }}
            QPushButton#screen-result-continue {{
                background: transparent; color: {colors["hint"]};
                border: 1px dashed {colors["border"]}; border-radius: 8px;
                padding: 5px 10px; font-size: 12px; text-align: center;
            }}
            QPushButton#screen-result-continue:hover {{
                color: #1677e8; border-color: #1677e8;
            }}
            QComboBox#screen-result-lang {{
                background: {colors["button"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]}; border-radius: 6px;
                padding: 2px 8px; font-size: 12px;
            }}
            QComboBox#screen-result-lang QAbstractItemView {{
                background: {colors["surface"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]};
            }}
            QSizeGrip#screen-result-grip {{ background: transparent; }}
        """)

    def _make_view(self, min_h: int, max_h: int) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setObjectName("screen-result-text")
        view.setReadOnly(True)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setMinimumHeight(min_h)
        view.setMaximumHeight(max_h)
        # 只读文本视图不许在点击时抢键盘焦点（面板本来也激活不了）
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return view

    # ---------------------------------------------------------------- 只读视图
    @property
    def style(self) -> str:
        """实际生效的样式（``"dark"`` / ``"light"``，主题跟着宿主走之后的结论）。"""
        return self._style

    def title_text(self) -> str:
        return self._title.text()

    def status_text(self) -> str:
        return self._status.text()

    def primary_text(self) -> str:
        return self._primary_view.toPlainText()

    def secondary_text(self) -> str:
        return self._secondary_view.toPlainText()

    def has_secondary(self) -> bool:
        return self._secondary_view.isVisibleTo(self)

    def copy_button(self) -> QPushButton:
        return self._copy_btn

    def copy_secondary_button(self) -> QPushButton:
        return self._copy_secondary_btn

    def close_button(self) -> QPushButton:
        return self._close_btn

    def continue_button(self) -> QPushButton:
        """「继续提问…」入口（测试断言用；产品代码不碰）。"""
        return self._continue_btn

    def _continue_ask(self) -> None:
        callback = self._on_continue_ask
        if callback is None or self._continue_image is None:
            return
        callback(self._continue_image, self._primary_view.toPlainText())

    def _language_changed(self, _index: int) -> None:
        callback = self._on_language_change
        if callback is None:
            return
        callback(self._lang_combo.currentData())

    def language_row(self) -> QWidget:
        """「译为」语言行（测试断言用；产品代码不碰）。"""
        return self._lang_row

    def language_combo(self) -> QComboBox:
        return self._lang_combo

    # ---------------------------------------------------------------- 展示
    def show_result(self, result: ScreenResult, anchor: QWidget | None = None,
                    on_continue_ask=None, below=None, on_language_change=None) -> None:
        """换内容 + 定位 + 显示（复用同一件面板，不重复造窗）。

        ``on_continue_ask``：签名 ``(image, recognized_text) -> None``——面板底部
        「继续提问…」的回调（由编排层注入，把图带进问答浮窗）。``result.image``
        为空时入口不出现（没有上下文的"继续问"是空转）。

        ``on_language_change``：签名 ``(target) -> None``——翻译语言行的回调。
        只在 ``result.language_selector`` 为真且回调存在时出现该行。

        ``below``：采集选区（SelectionRect 或矩形）——给定时面板落在选区正下方
        （实机反馈：落在屏幕角落视线要来回跳），缺省维持锚/屏幕边的旧定位。
        """
        self._title.setText(str(result.title))
        self._status.setText(str(result.status))
        self._primary_view.setPlainText(str(result.primary))
        self._secondary_view.setPlainText(str(result.secondary))

        self._primary_label.setText(str(result.primary_label))
        self._primary_label.setVisible(bool(result.primary_label))
        # 加载态：复制/语言行/继续提问收起；正文槽有内容就留着（翻译第二段：
        # 原文已就位，动画摆在下面表示"还在跑"），空正文就只有动画。
        loading = bool(result.loading)
        self._loading.setVisible(loading)
        if loading:
            self._loading.start()
        else:
            self._loading.stop()
        self._copy_btn.setVisible(not loading)
        # 空正文（引擎缺席/没认到字）不占地方：面板只剩标题栏与状态说明
        self._primary_view.setVisible(bool(result.primary.strip()))
        # 双语对照位只在真有译文时出现（翻译引擎接入前不占地方）；译文槽的
        # 标题可由调用方覆盖，缺省「译文」。
        bilingual = bool(result.secondary.strip())
        self._secondary_label.setText(str(result.secondary_label or "译文"))
        self._secondary_label.setVisible(bilingual)
        self._divider.setVisible(bilingual)
        self._secondary_view.setVisible(bilingual)
        self._copy_secondary_btn.setVisible(bilingual)
        self._copy_btn.setText("复制原文" if bilingual else "复制")

        # 「继续提问」只在有图可带且非加载态时出现（复制/纯状态/加载中都没有下文可续）。
        self._on_continue_ask = (
            on_continue_ask if (result.image is not None and not loading) else None
        )
        self._continue_btn.setVisible(self._on_continue_ask is not None)
        self._continue_image = result.image
        # 加载态不摆"正在识别…"这类文字（实机反馈：动画即可，文字像卡死说明）
        self._status.setVisible(bool(result.status) and not loading)

        # 翻译语言行：翻译结果且编排层给了重翻回调才出现；过程态/其它结果不出现。
        self._on_language_change = (
            on_language_change if (result.language_selector and not loading) else None
        )
        self._lang_row.setVisible(self._on_language_change is not None)

        self.show_near(anchor, below=below)
        self.show()
        self.raise_()

    def show_near(self, anchor: QWidget | None = None, below=None) -> None:
        """贴边定位：有选区矩形优先跟选区；否则优先锚（岛）左边，再贴屏幕边。

        用户用 grip 拉过尺寸后（``_user_size`` 非 None）沿用用户的大小——面板是
        复用件，"每张结果都重置回默认大小"会把用户刚调好的布局没收掉。
        """
        available = self._available_geometry(anchor)
        width = min(self.sizeHint().width(), available.width())
        width = max(width, min(_MIN_WIDTH, available.width()))
        self._applying_size = True
        try:
            self.resize(width, self.height())
            # 文本槽按内容实测高度（上下限之间）：一行结果不该撑出满高面板，
            # 一行也放不下时由各自的滚动条接住。
            self._fit_view_height(self._primary_view, _PRIMARY_MIN_H, _PRIMARY_MAX_H, width)
            self._fit_view_height(self._secondary_view, _SECONDARY_MIN_H, _SECONDARY_MAX_H,
                                  width)
            self.adjustSize()
            height = min(self.sizeHint().height(), available.height())
            if self._user_size is not None:
                width = max(_MIN_WIDTH, min(self._user_size.width(), available.width()))
                height = max(140, min(self._user_size.height(), available.height()))
            # 记录的必须是**实际会交付的尺寸**——最小高度地板会把 resize(300,115)
            # 钳成 (300,140)，记 115 的话延迟投递的事件就被误当成"用户拉的"
            # （短结果首发永久锁高度的缺陷就是这么来的）。
            width = max(self.minimumWidth(), width)
            height = max(self.minimumHeight(), height)
            self._last_programmatic_size = QSize(width, height)
            self.resize(width, height)
        finally:
            self._applying_size = False

        if anchor is not None:
            geo = anchor.frameGeometry()
            if not geo.isValid() or geo.isNull():
                geo = anchor.geometry()
            x = geo.left() - width - _GAP          # 左侧（岛常贴右/上边）
            if x < available.left():
                x = geo.right() + _GAP             # 右边
            y = geo.center().y() - height // 2
            if y + height > available.bottom():
                y = geo.top() - height - _GAP      # 上方
        else:
            x = available.right() - width - _MARGIN
            y = available.bottom() - height - _MARGIN
        x = max(available.left(), min(x, available.right() - width))
        y = max(available.top(), min(y, available.bottom() - height))
        if below is not None:
            position_below_rect(self, below)       # 选区优先于角落定位
        else:
            self.move(QPoint(x, y))

    def _fit_view_height(self, view: QPlainTextEdit, min_h: int, max_h: int,
                         panel_width: int) -> None:
        """按内容实测给文本槽定高（一行结果不撑满高面板，长文由滚动条接住）。

        用字体度量算折行高度（``view.font()`` 就是 QSS 生效后的那份字体，实测
        pixelSize=13 与渲染一致）：**不能**问 ``document().size()``——QPlainTextEdit
        的专用 layout 那份尺寸不是折行后的高度（900 字实测报 48px）。宽度一律
        预留竖向滚动条的位置，让"要不要滚动条"和"要不要换行"不互相追着改。
        """
        if not view.isVisibleTo(self):
            return
        margin = int(view.document().documentMargin())
        inner = max(80, int(panel_width) - 2 * 14 - 2 * margin - 15)
        metrics = QFontMetrics(view.font())
        bounds = metrics.boundingRect(
            0, 0, inner, 100000,
            int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs),
            view.toPlainText(),
        )
        needed = (int(bounds.height()) + 2 * margin
                  + int(view.frameWidth()) * 2 + _TEXT_SAFETY_PX)
        view.setFixedHeight(max(int(min_h), min(int(max_h), needed)))

    def _available_geometry(self, anchor: QWidget | None):
        screen = None
        if anchor is not None:
            screen = QGuiApplication.screenAt(anchor.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return self.geometry()
        return screen.availableGeometry()

    # ---------------------------------------------------------------- 交互
    def copy_primary(self) -> bool:
        """复制主文本；空文本返回 False（不冒充成功）。"""
        return self._copy_text(self.primary_text())

    def copy_secondary(self) -> bool:
        return self._copy_text(self.secondary_text())

    @staticmethod
    def _copy_text(text: str) -> bool:
        if not str(text).strip():
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(str(text))
        return True

    def close_panel(self) -> None:
        """收口：藏起来 + 摘掉 Esc 过滤器（复用件，下一次展示重新装）。"""
        self._detach_escape_filter()
        self.hide()

    # ------------------------------------------------------------ 拖动与缩放
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 透明背景窗口上 QSS 不画自身背景（实测 A/B：WA_TranslucentBackground 一开，
        # background/background-color 都不落像素）——卡片圆角矩形只能手画。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()),
                            float(rect.width()), float(rect.height()), 14.0, 14.0)
        painter.fillPath(path, QColor(self._palette["surface"]))
        painter.setPen(QColor(self._palette["border"]))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._grip.move(self.width() - 16, self.height() - 16)
        # 程序化排版（show_near）不记；只有 grip/WM 拉出来的才算用户尺寸。
        # 首次显示前的尺寸事件是延迟投递的，单靠 _applying_size 旗标挡不住，
        # 必须再比对一次值（延迟事件被 Qt 合并成最后一次排版的尺寸）。
        if self._applying_size:
            return
        if self._last_programmatic_size is not None and event.size() == self._last_programmatic_size:
            return
        self._user_size = event.size()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 面板本体（标题栏/留白）上的按下 = 拖动起点；子控件（按钮/文本槽/grip）
        # 的事件根本到不了这里，不用排除。
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ Esc 过滤器
    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._attach_escape_filter()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._detach_escape_filter()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._detach_escape_filter()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """兜底：万一某平台给了键盘焦点，Esc 同样可关。"""
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _attach_escape_filter(self) -> None:
        app = QApplication.instance()
        if app is None or self._escape_installed:
            return
        app.installEventFilter(self)
        self._escape_installed = True

    def _detach_escape_filter(self) -> None:
        app = QApplication.instance()
        if app is None or not self._escape_installed:
            return
        app.removeEventFilter(self)
        self._escape_installed = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt 命名)
        """应用级 Esc 兜底——**永不吞事件**。

        面板是防抢焦点窗，拿不到键盘焦点，Esc 只能从应用级过滤器进来；而应用级
        过滤器看得到**所有**窗口的 Esc，一旦返回 True 就等于把主人的弹弓取消 /
        关设置页一起吃掉。这里只做"顺手把面板关掉"，事件照旧传下去（返回
        False）；真正的 Esc 归属（弹窗、菜单、输入框里的撤销编辑）一律让路。
        """
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() != Qt.Key.Key_Escape:
            return False
        if not self.isVisible():
            return False
        app = QApplication.instance()
        if app is not None:
            if app.activeModalWidget() is not None:
                return False
            if app.activePopupWidget() is not None:
                return False
        focus = app.focusWidget() if app is not None else None
        if (
            focus is not None
            and not self.isAncestorOf(focus)
            and isinstance(focus, _ESC_OWNING_WIDGETS)
        ):
            return False
        self.close_panel()
        return False
