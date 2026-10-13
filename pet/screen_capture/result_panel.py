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

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPalette, QTextOption
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
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


@dataclass(frozen=True)
class ScreenResult:
    """一次截图动作的结果（展示层的唯一输入模型）。

    ``primary`` = 主文本（OCR 文字 / 问答答复 / 翻译原文），``secondary`` =
    双语对照的第二槽（译文，留给后续片的翻译引擎），``status`` = 一句话口径
    （"本地识别 · 12 字" / "翻译引擎将在后续片接入"），写在标题右侧。
    """

    title: str
    primary: str = ""
    secondary: str = ""
    status: str = ""
    primary_label: str = ""
    secondary_label: str = ""
    force_panel: bool = False

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
    """

    def __init__(self, parent: QWidget | None = None, *, style: str | None = None) -> None:
        super().__init__(parent)
        self._style = resolve_style(style, self.palette())
        self._palette = _STYLES[self._style]
        self.setObjectName("screen-result-panel")
        self.setWindowTitle("")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        # 显示不激活：主人正在打字时不许把焦点抢过来
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setMinimumWidth(_MIN_WIDTH)
        self.setMaximumWidth(_MAX_WIDTH)
        self._escape_installed = False
        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        colors = self._palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel("")
        self._title.setObjectName("screen-result-title")
        self._title.setWordWrap(False)
        header.addWidget(self._title)
        self._status = QLabel("")
        self._status.setObjectName("screen-result-status")
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

        self.setStyleSheet(f"""
            QFrame#screen-result-panel {{
                background: {colors["surface"]};
                border: 1px solid {colors["border"]};
                border-radius: 12px;
            }}
            QLabel#screen-result-title {{
                color: {colors["text"]}; font-size: 13px; font-weight: 600;
            }}
            QLabel#screen-result-status, QLabel#screen-result-slot {{
                color: {colors["hint"]}; font-size: 11px;
            }}
            QPlainTextEdit {{
                background: transparent; color: {colors["text"]};
                border: none; font-size: 13px;
            }}
            QFrame#screen-result-divider {{ background: {colors["divider"]}; border: none; }}
            QPushButton {{
                background: {colors["button"]}; color: {colors["text"]};
                border: 1px solid {colors["border"]}; border-radius: 7px;
                padding: 3px 10px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {colors["hint"]}; }}
            QPushButton#screen-result-close {{ padding: 0; font-size: 14px; }}
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

    # ---------------------------------------------------------------- 展示
    def show_result(self, result: ScreenResult, anchor: QWidget | None = None) -> None:
        """换内容 + 定位 + 显示（复用同一件面板，不重复造窗）。"""
        self._title.setText(str(result.title))
        self._status.setText(str(result.status))
        self._primary_view.setPlainText(str(result.primary))
        self._secondary_view.setPlainText(str(result.secondary))

        self._primary_label.setText(str(result.primary_label))
        self._primary_label.setVisible(bool(result.primary_label))
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

        self.show_near(anchor)
        self.show()
        self.raise_()

    def show_near(self, anchor: QWidget | None = None) -> None:
        """贴边定位：优先锚（岛）左边，放不下换右边，再放不下就贴屏幕边。"""
        available = self._available_geometry(anchor)
        width = min(self.sizeHint().width(), available.width())
        width = max(width, min(_MIN_WIDTH, available.width()))
        self.resize(width, self.height())
        # 文本槽按内容实测高度（上下限之间）：一行结果不该撑出满高面板，
        # 一行也放不下时由各自的滚动条接住。
        self._fit_view_height(self._primary_view, _PRIMARY_MIN_H, _PRIMARY_MAX_H, width)
        self._fit_view_height(self._secondary_view, _SECONDARY_MIN_H, _SECONDARY_MAX_H,
                              width)
        self.adjustSize()
        height = min(self.sizeHint().height(), available.height())
        self.resize(width, height)

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
