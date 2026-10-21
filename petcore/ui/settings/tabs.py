"""设置页内的任务分页（与主分支 SettingsTabContainer 同构）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

TAB_HEIGHT = 34
ARROW_STEP = 180


class SettingsTabContainer(QWidget):
    currentKeyChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsTaskTabs")
        self._keys: list[str] = []
        self._labels: list[str] = []
        self._buttons: list[QPushButton] = []

        self.tab_bar = QWidget(self)
        self.tab_bar.setObjectName("settingsTaskTabBar")
        self.tab_bar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.tab_layout = QHBoxLayout(self.tab_bar)
        self.tab_layout.setContentsMargins(3, 3, 3, 3)
        self.tab_layout.setSpacing(2)
        self.tab_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # 窗口变窄时标签条会超出可视宽度：装进横向滚动区，两侧给翻页箭头，
        # 否则右侧的标签页就点不到了（设置窗口最小宽度 720 也会截断 8 个标签）。
        self.tab_scroll = QScrollArea(self)
        self.tab_scroll.setObjectName("settingsTaskTabScroll")
        self.tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tab_scroll.setWidgetResizable(True)
        self.tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tab_scroll.setFixedHeight(TAB_HEIGHT + 8)
        self.tab_scroll.setWidget(self.tab_bar)

        self.prev_button = QToolButton(self)
        self.prev_button.setObjectName("settingsTaskTabArrow")
        self.prev_button.setText("‹")
        self.prev_button.setAccessibleName("上一组分页")
        self.prev_button.clicked.connect(lambda: self._scroll_by(-ARROW_STEP))
        self.next_button = QToolButton(self)
        self.next_button.setObjectName("settingsTaskTabArrow")
        self.next_button.setText("›")
        self.next_button.setAccessibleName("下一组分页")
        self.next_button.clicked.connect(lambda: self._scroll_by(ARROW_STEP))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.prev_button)
        row.addWidget(self.tab_scroll, 1)
        row.addWidget(self.next_button)
        self._row = row

        self.stack = QStackedWidget(self)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(row)
        layout.addWidget(self.stack, 1)

        bar = self.tab_scroll.horizontalScrollBar()
        bar.rangeChanged.connect(lambda _lo, _hi: self._update_arrows())
        self._update_arrows()

    def _scroll_by(self, delta: int) -> None:
        bar = self.tab_scroll.horizontalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + delta)))
        self._update_arrows()

    def _update_arrows(self) -> None:
        try:
            bar = self.tab_scroll.horizontalScrollBar()
            overflow = bar.maximum() > bar.minimum()
            self.prev_button.setVisible(overflow and bar.value() > bar.minimum())
            self.next_button.setVisible(overflow and bar.value() < bar.maximum())
        except RuntimeError:
            # 页面已销毁时 singleShot 仍会回调，静默忽略。
            return

    def _ensure_visible(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self.tab_scroll.ensureWidgetVisible(self._buttons[index], 48, 0)
            self._update_arrows()

    def addTab(self, key: str, label: str, page: QWidget) -> None:  # noqa: N802
        key = str(key)
        button = QPushButton(str(label), self.tab_bar)
        button.setObjectName("settingsTaskTab")
        button.setProperty("navigationStyle", "plugin")
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setAccessibleName(f"切换到{label}")
        index = len(self._keys)
        button.clicked.connect(lambda _checked=False, index=index: self.setCurrentIndex(index))
        self._keys.append(key)
        self._labels.append(str(label))
        self._buttons.append(button)
        self.tab_layout.addWidget(button)
        self.stack.addWidget(page)
        if index == 0:
            button.setChecked(True)
            self.stack.setCurrentIndex(0)
        QTimer.singleShot(0, self._update_arrows)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._keys)

    def labels(self) -> tuple[str, ...]:
        return tuple(self._labels)

    def currentKey(self) -> str:  # noqa: N802
        index = self.stack.currentIndex()
        return self._keys[index] if 0 <= index < len(self._keys) else ""

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self._ensure_visible(index)
        self.stack.updateGeometry()
        self.updateGeometry()
        self.currentKeyChanged.emit(self.currentKey())

    def setCurrentKey(self, key: str) -> None:  # noqa: N802
        if key in self._keys:
            self.setCurrentIndex(self._keys.index(key))

    def key_for_label(self, label: str) -> str:
        for key, current in zip(self._keys, self._labels):
            if current == label:
                return key
        return ""
