from __future__ import annotations

import logging
from contextlib import contextmanager

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .tabs import SettingsTabContainer

_FOCUSABLE = (QCheckBox, QComboBox, QLineEdit, QPushButton)

#: 页内分页里内嵌的 SettingsPage 自带滚动体：给个下限，免得被外层滚动区压成一条。
TAB_STACK_MIN_HEIGHT = 320

logger = logging.getLogger("petcore.ui.settings.page")


class SettingsCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(0)
        self._rows = 0

    def add_row(
        self,
        label: str,
        control: QWidget,
        hint: str = "",
        *,
        expand: bool = False,
        sub: bool = False,
    ) -> QWidget:
        row = QWidget(self)
        if sub:
            row.setProperty("subRow", True)

        text_widget = QWidget(row)
        text_widget.setObjectName("settingTextBlock")
        text_column = QVBoxLayout(text_widget)
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        title = QLabel(label, text_widget)
        title.setObjectName("settingLabel")
        title.setWordWrap(True)
        text_column.addWidget(title)
        if hint:
            hint_label = QLabel(hint, text_widget)
            hint_label.setObjectName("settingHint")
            hint_label.setWordWrap(True)
            text_column.addWidget(hint_label)
        text_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        if isinstance(control, _FOCUSABLE):
            title.setBuddy(control)
            control.setAccessibleName(label)
            if hint:
                control.setAccessibleDescription(hint)
        if control.parent() is None:
            control.setParent(row)

        if expand:
            # 宽控件（路径、台词、结果框）另起一行：文字块独占整行宽度，
            # 否则扩展管理这种窄内容区会把提示压成一字一行。
            outer = QVBoxLayout(row)
            outer.setContentsMargins(16 if not sub else 44, 10, 16, 10)
            outer.setSpacing(6)
            outer.addWidget(text_widget)
            outer.addWidget(control)
        else:
            outer = QHBoxLayout(row)
            outer.setContentsMargins(16 if not sub else 44, 10, 16, 10)
            outer.setSpacing(18)
            text_widget.setMinimumWidth(180)
            outer.addWidget(text_widget, 1)
            outer.addWidget(
                control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            )
        self._append(row)
        return row

    def add_widget(self, widget: QWidget) -> None:
        row = QWidget(self)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.addWidget(widget)
        self._append(row)

    def add_buttons(self, buttons: list[QWidget]) -> None:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)
        layout.addStretch(1)
        for button in buttons:
            layout.addWidget(button)
        self._append(row)

    def _append(self, row: QWidget) -> None:
        if self._rows:
            divider = QFrame(self)
            divider.setObjectName("cardDivider")
            divider.setFixedHeight(1)
            wrapper = QWidget(self)
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(14, 0, 14, 0)
            wrapper_layout.addWidget(divider)
            self._layout.addWidget(wrapper)
        self._layout.addWidget(row)
        self._rows += 1


class SettingsPage(QWidget):
    title = ""
    changed = Signal()

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        self.scroll = scroll
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 窄窗（720×500）下内容会比视口宽：允许横向滚动，否则右侧按钮直接不可达。
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget()
        self.content = content
        content.setObjectName("settingsPageContent")
        content.setAutoFillBackground(False)
        content.setMaximumWidth(860)
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(30, 24, 28, 20)
        self.body.setSpacing(18)

        heading = QLabel(self.title, content)
        self.heading = heading
        heading.setObjectName("pageTitle")
        heading.setWordWrap(True)
        self.body.addWidget(heading)
        self.body.addStretch(1)

        scroll.setWidget(content)
        scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        outer.addWidget(scroll)

        # 卡片默认落进整页；进入 `with self.tab(...)` 时临时改指向该分页。
        self._section_layout = self.body
        self._tab_container: SettingsTabContainer | None = None
        self._embedded_pages: list[SettingsPage] = []

    def prepare_embedded(self) -> None:
        """作为页内分页内容时隐藏重复标题、收紧边距。"""
        self.heading.setVisible(False)
        self.body.setContentsMargins(0, 8, 0, 8)
        self.content.setMaximumWidth(16777215)
        # 内嵌页被左侧导航压窄：内容比视口宽时给横向滚动条，别让控件被裁掉。
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

    # ------------------------------------------------------------ 页内分页
    @property
    def tab_container(self) -> SettingsTabContainer | None:
        return self._tab_container

    def _ensure_tab_container(self) -> SettingsTabContainer:
        if self._tab_container is None:
            container = SettingsTabContainer(self.content)
            container.setObjectName("pageTaskTabs")
            container.stack.setMinimumHeight(TAB_STACK_MIN_HEIGHT)
            self.body.insertWidget(self.body.count() - 1, container)
            self._tab_container = container
        return self._tab_container

    @contextmanager
    def tab(self, key: str, label: str):
        """把块内的卡片收进一个页内分页；第一次进入时插入标签容器。"""
        container = self._ensure_tab_container()
        page = QWidget(self.content)
        page.setObjectName(f"settingsTabPage_{key}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.body.spacing())
        layout.addStretch(1)
        previous = self._section_layout
        self._section_layout = layout
        try:
            yield page
        finally:
            self._section_layout = previous
            container.addTab(str(key), str(label), page)

    def embed_page(self, page: SettingsPage, key: str, label: str) -> None:
        """把一个扩展提供（或 Core 内嵌）的设置页作为本页的一个分页。"""
        page.prepare_embedded()
        container = self._ensure_tab_container()
        try:
            page.changed.connect(self.changed.emit)
        except Exception:
            logger.warning(
                "embedded page %s has no usable changed signal", key, exc_info=True
            )
        container.addTab(str(key), str(label), page)
        self._embedded_pages.append(page)

    def _embedded_dirty(self) -> bool:
        return any(page.dirty() for page in self._embedded_pages)

    def _embedded_confirm_save(self) -> None:
        for page in self._embedded_pages:
            page.confirm_save()

    def _embedded_discard(self) -> None:
        for page in self._embedded_pages:
            page.discard_changes()

    def _embedded_dispose(self) -> None:
        pages, self._embedded_pages = self._embedded_pages, []
        for page in pages:
            page.dispose()

    def _embedded_keywords(self) -> list[str]:
        values: list[str] = []
        for page in self._embedded_pages:
            title = str(getattr(page, "title", "") or "")
            if title:
                values.append(title)
            values.extend(str(item) for item in page.keywords())
        return values

    def _append_section_widget(self, widget: QWidget) -> None:
        layout = self._section_layout
        count = layout.count()
        if count and layout.itemAt(count - 1).spacerItem() is not None:
            layout.insertWidget(count - 1, widget)
        else:
            layout.addWidget(widget)

    def group_heading(self, title: str) -> QLabel:
        """mod 页的二级标题（H2）：一个 mod 的全部内容挂在它下面。"""
        label = QLabel(title, self.content)
        label.setObjectName("groupTitle")
        label.setWordWrap(True)
        self._append_section_widget(label)
        return label

    def section(self, title: str, *, level: int = 2) -> SettingsCard:
        """分组卡片。``level=3`` 是 mod 页内的三级标题（H3）。"""
        sub = int(level) >= 3
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12 if sub else 0, 0, 0, 0)
        layout.setSpacing(7)
        label = QLabel(title, wrapper)
        label.setObjectName("subsectionTitle" if sub else "sectionTitle")
        label.setWordWrap(True)
        card = SettingsCard(wrapper)
        if sub:
            wrapper.setProperty("subSection", True)
        layout.addWidget(label)
        layout.addWidget(card)
        self._append_section_widget(wrapper)
        return card

    def add_note(self, text: str) -> QLabel:
        note = QLabel(text, self)
        note.setObjectName("settingHint")
        note.setWordWrap(True)
        self._append_section_widget(note)
        return note

    def dirty(self) -> bool:
        return False

    def draft(self) -> None:
        return None

    def confirm_save(self) -> None:
        return None

    def discard_changes(self) -> None:
        return None

    def dispose(self) -> None:
        self._embedded_dispose()

    def keywords(self) -> list[str]:
        return []


def embedded_page_specs(host, host_page: str) -> list:
    """Core 特性里声明 `host_page` 的设置页（按贡献者的 order 排好）。"""
    features = getattr(host, "features", None)
    getter = getattr(features, "embedded_pages", None)
    if not callable(getter):
        return []
    try:
        return list(getter(str(host_page)) or ())
    except Exception:
        logger.warning("embedded pages for %s failed", host_page, exc_info=True)
        return []


def build_embedded_page(spec, host) -> SettingsPage | None:
    factory = getattr(spec, "factory", None)
    if not callable(factory):
        return None
    try:
        page = factory(host)
    except Exception:
        logger.warning(
            "embedded page %s failed to build", getattr(spec, "id", "?"), exc_info=True
        )
        return None
    return page if isinstance(page, SettingsPage) else None


def page_label_texts(page: QWidget) -> list[str]:
    """页面内所有可见文案（标题 + 说明），供搜索做行级匹配。"""
    texts: list[str] = []
    for label in page.findChildren(QLabel):
        text = label.text().strip()
        if text:
            texts.append(text)
    return texts


def page_search_texts(page: QWidget) -> list[str]:
    """搜索口径：文字标签 + 按钮 + 勾选 + 下拉选项 + 列表项。

    只扫 ``QLabel`` 会漏掉「生成子宠」「重新加载扩展」这类**按钮**文案，
    用户照着菜单上的字搜却得到「没有匹配」（审计 AUD-29）。
    """
    texts = list(page_label_texts(page))
    for button in page.findChildren(QAbstractButton):
        text = button.text().strip()
        if text:
            texts.append(text)
    for combo in page.findChildren(QComboBox):
        for index in range(combo.count()):
            text = combo.itemText(index).strip()
            if text:
                texts.append(text)
    for view in page.findChildren(QListWidget):
        for row in range(view.count()):
            item = view.item(row)
            if item is not None and item.text().strip():
                texts.append(item.text().strip())
    return texts


def reveal_text(page: QWidget, needle: str) -> bool:
    """把命中文案的行滚到可见处，并切到它所在的页内分页。"""
    needle = str(needle or "").strip().lower()
    if not needle:
        return False
    for label in page.findChildren(QWidget):
        text = ""
        if isinstance(label, QLabel):
            text = label.text()
        elif isinstance(label, QAbstractButton):
            text = label.text()
        if not text or label.isHidden():
            continue
        if needle not in text.strip().lower():
            continue
        widget = label
        while widget is not None:
            parent = widget.parentWidget()
            if isinstance(parent, QStackedWidget):
                parent.setCurrentWidget(widget)
                # 直接切 stack 不会同步页内分页的按钮选中态；搜索定位要顺手切过去。
                container = parent.parentWidget()
                if isinstance(container, SettingsTabContainer):
                    container.setCurrentIndex(parent.indexOf(widget))
            elif isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(label, 0, 80)
            widget = parent
        return True
    return False


def make_button(text: str, parent=None, *, primary: bool = False) -> QPushButton:
    button = QPushButton(text, parent)
    if primary:
        button.setObjectName("primaryButton")
    return button


def make_slider(parent=None) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setAccessibleName("大小滑条")
    slider.setMinimumWidth(220)
    return slider


def make_spin(parent=None) -> QSpinBox:
    spin = QSpinBox(parent)
    spin.setAccessibleName("大小百分比")
    spin.setMinimumWidth(82)
    spin.setKeyboardTracking(False)
    return spin


def make_checkbox(parent=None) -> QCheckBox:
    box = QCheckBox(parent)
    palette = box.palette()
    accent = QColor("#0a84ff")
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        palette.setColor(accent_role, accent)
    box.setPalette(palette)
    return box


def value_field(text: str, parent=None) -> QLineEdit:
    field = QLineEdit(text, parent)
    field.setObjectName("valueField")
    field.setReadOnly(True)
    field.setMinimumWidth(260)
    field.setToolTip(text)
    field.setCursorPosition(0)
    return field
