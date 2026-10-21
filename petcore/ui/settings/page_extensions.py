from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .base import SettingsPage
from .page_mods import ModsPage

logger = logging.getLogger("petcore.ui.settings.extensions")

#: 不进组、固定排在最前面的页面（扩展管理本体）。
STANDALONE_GROUP = ""
BASE_GROUP = "base"
ADDON_GROUP = "addon"
CORE_GROUP = "core"
GROUP_TITLES = ((BASE_GROUP, "基础扩展"), (ADDON_GROUP, "加装扩展"))
EMPTY_GROUP_TEXT = "（暂无）"
GROUP_ARROW_EXPANDED = "▾"
GROUP_ARROW_COLLAPSED = "▸"
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1
NAV_MIN_WIDTH = 190
NAV_MAX_WIDTH = 260


def _group_of(spec) -> str:
    return ADDON_GROUP if str(getattr(spec, "group", "") or "") == ADDON_GROUP else BASE_GROUP


class _NavList(QListWidget):
    """QListWidget 的默认 sizeHint 是 256 宽：导航固定取窄宽度，把空间留给右侧内容。"""

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(NAV_MIN_WIDTH, super().sizeHint().height())


class _HostedWidgetPage(SettingsPage):
    """把非 SettingsPage 的第三方控件收进扩展管理，明确标注不参与保存。"""

    def __init__(self, host, widget: QWidget, title: str, parent=None):
        super().__init__(host, parent)
        self.add_note(
            f"「{title}」没有实现 SettingsPage 接口，改动不会随设置保存；"
            "请联系扩展作者改用 petcore.ui.settings.base.SettingsPage。"
        )
        container = QWidget(self.content)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        self.body.insertWidget(self.body.count() - 1, container)


class _NavFacade:
    """兼容旧的页内标签门面：`labels/currentKey/setCurrentKey` 代理到左侧导航。"""

    def __init__(self, owner: "ExtensionsPage"):
        self._owner = owner

    def labels(self) -> tuple[str, ...]:
        return tuple(label for _key, label in self._owner._page_labels)

    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _label in self._owner._page_labels)

    def currentKey(self) -> str:  # noqa: N802
        return self._owner.current_key()

    def setCurrentKey(self, key: str) -> None:  # noqa: N802
        self._owner.select_tab(key)

    def key_for_label(self, label: str) -> str:
        for key, current in self._owner._page_labels:
            if current == label:
                return key
        return ""


class ExtensionsPage(SettingsPage):
    title = "扩展管理"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._pages: list[tuple[str, SettingsPage]] = []
        self._page_labels: list[tuple[str, str]] = []
        self._entries: dict[str, tuple[str, SettingsPage]] = {}
        self._grouped: dict[str, list[tuple[str, str]]] = {
            STANDALONE_GROUP: [],
            BASE_GROUP: [],
            ADDON_GROUP: [],
        }
        self._row_keys: dict[int, str] = {}
        self._header_items: dict[str, QListWidgetItem] = {}
        self._group_items: dict[str, list[QListWidgetItem]] = {}
        self._collapsed: dict[str, bool] = {}
        self._current_key = ""

        container = QWidget(self.content)
        container.setObjectName("extensionsBrowser")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.nav = _NavList(container)
        self.nav.setObjectName("extensionsNav")
        self.nav.setAccessibleName("扩展页面列表")
        self.nav.setMinimumWidth(NAV_MIN_WIDTH)
        self.nav.setMaximumWidth(NAV_MAX_WIDTH)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nav.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.nav.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.nav.currentRowChanged.connect(self._on_row_changed)
        self.nav.itemClicked.connect(self._on_nav_clicked)

        self.stack = QStackedWidget(container)
        self.stack.setObjectName("extensionsPages")
        self.stack.currentChanged.connect(self._on_stack_changed)
        # 右侧页面自带滚动体：给一个最小高度，避免被外层滚动区压成 0。
        self.stack.setMinimumHeight(420)
        self.stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.body.insertWidget(self.body.count() - 1, container)

        self.tabs = _NavFacade(self)

        mods_page = ModsPage(host, self)
        mods_page.prepare_embedded()
        self._register("mods", "扩展管理", mods_page, STANDALONE_GROUP)

        for spec, page in self._contributed_pages():
            self._register_contribution(spec, page)

        self._fill_nav()
        self.select_tab("mods")

    # ------------------------------------------------------------ 页面装载
    def _contributed_pages(self) -> list[tuple[object, QWidget]]:
        provider = getattr(self.host, "settings_pages", None)
        if not callable(provider):
            return []
        try:
            specs = list(provider() or ())
        except Exception:
            logger.warning("settings_pages provider failed", exc_info=True)
            return []
        try:
            specs.sort(
                key=lambda spec: (
                    int(getattr(spec, "order", 500) or 0),
                    str(getattr(spec, "id", "")),
                )
            )
        except Exception:
            pass
        created: list[tuple[object, QWidget]] = []
        for spec in specs:
            # 已并入 Core 的页由 Core 设置页内嵌，不再在这里建第二份实例。
            if str(getattr(spec, "group", "") or "") == CORE_GROUP:
                continue
            factory = getattr(spec, "factory", None)
            if not callable(factory):
                continue
            try:
                page = factory(self.host)
            except Exception:
                logger.warning(
                    "settings page %s failed to build", getattr(spec, "id", "?"), exc_info=True
                )
                continue
            if isinstance(page, QWidget):
                created.append((spec, page))
        return created

    def _register_contribution(self, spec, page: QWidget) -> None:
        raw_key = str(getattr(spec, "id", "") or getattr(page, "title", ""))
        if not raw_key:
            return
        key = f"extension:{raw_key}"
        if key in self._entries:
            logger.warning("duplicate settings page id: %s", raw_key)
            return
        title = str(getattr(spec, "title", "") or getattr(page, "title", "") or raw_key)
        label = str(getattr(spec, "label", "") or title)
        if isinstance(page, SettingsPage):
            page.prepare_embedded()
        else:
            logger.warning(
                "settings page %s is not a SettingsPage; hosting it read-only", raw_key
            )
            page = _HostedWidgetPage(self.host, page, label, self)
        self._register(key, label, page, _group_of(spec))

    def _register(self, key: str, label: str, page: SettingsPage, group: str) -> None:
        self._pages.append((key, page))
        self._entries[key] = (label, page)
        self._grouped.setdefault(group, []).append((key, label))
        self.stack.addWidget(page)
        try:
            page.changed.connect(self.changed.emit)
        except Exception:
            pass

    # ------------------------------------------------------------ 左侧导航
    def _fill_nav(self) -> None:
        self.nav.blockSignals(True)
        self.nav.clear()
        self._row_keys = {}
        self._header_items = {}
        self._group_items = {}
        ordered: list[tuple[str, str]] = []
        for key, label in self._grouped.get(STANDALONE_GROUP, []):
            self._add_nav_page(key, label)
            ordered.append((key, label))
        for group, title in GROUP_TITLES:
            self._header_items[group] = self._add_nav_header(group, title)
            items: list[QListWidgetItem] = []
            entries = self._grouped.get(group, [])
            if not entries:
                items.append(self._add_nav_placeholder())
            for key, label in entries:
                items.append(self._add_nav_page(key, label))
                ordered.append((key, label))
            self._group_items[group] = items
        self._apply_collapsed_groups()
        self.nav.blockSignals(False)
        # labels 与导航同序（分组顺序），不是贡献注册顺序。
        self._page_labels = ordered

    def _add_nav_header(self, group: str, text: str) -> QListWidgetItem:
        item = QListWidgetItem(f"{GROUP_ARROW_EXPANDED} {text}")
        # 可点击（折叠开关）但不可选中：不给选中态，也不进 _row_keys。
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setData(GROUP_ROLE, group)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setToolTip(f"展开/收起「{text}」")
        self.nav.addItem(item)
        return item

    def _add_nav_placeholder(self) -> QListWidgetItem:
        item = QListWidgetItem(EMPTY_GROUP_TEXT)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.nav.addItem(item)
        return item

    def _add_nav_page(self, key: str, label: str) -> QListWidgetItem:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setToolTip(label)
        self.nav.addItem(item)
        self._row_keys[self.nav.row(item)] = key
        return item

    def _apply_collapsed_groups(self) -> None:
        for group, title in GROUP_TITLES:
            header = self._header_items.get(group)
            if header is None:
                continue
            collapsed = bool(self._collapsed.get(group, False))
            arrow = GROUP_ARROW_COLLAPSED if collapsed else GROUP_ARROW_EXPANDED
            header.setText(f"{arrow} {title}")
            for item in self._group_items.get(group, ()):
                item.setHidden(collapsed)

    def is_group_collapsed(self, group: str) -> bool:
        return bool(self._collapsed.get(str(group), False))

    def _on_nav_clicked(self, item: QListWidgetItem) -> None:
        group = item.data(GROUP_ROLE)
        if not group:
            return
        group = str(group)
        self._collapsed[group] = not self._collapsed.get(group, False)
        self._apply_collapsed_groups()
        self._restore_current_row()

    def _restore_current_row(self) -> None:
        """点组头只是折叠开关：把选中还给当前页，别让组头看起来被选中。"""
        row = next(
            (row for row, key in self._row_keys.items() if key == self._current_key),
            None,
        )
        if row is None or self.nav.currentRow() == row:
            return
        self.nav.blockSignals(True)
        try:
            self.nav.setCurrentRow(row)
        finally:
            self.nav.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        key = self._row_keys.get(int(row))
        if key is None:
            return
        entry = self._entries.get(key)
        if entry is None:
            return
        page = entry[1]
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
        self._current_key = key
        self.changed.emit()

    def _on_stack_changed(self, index: int) -> None:
        """搜索定位等外部入口直接切 stack 时，把左侧选中同步过来。"""
        page = self.stack.widget(index)
        if page is None:
            return
        for key, (_label, entry_page) in self._entries.items():
            if entry_page is not page or key == self._current_key:
                continue
            for row, row_key in self._row_keys.items():
                if row_key == key:
                    self.nav.setCurrentRow(row)
                    return

    # ------------------------------------------------------------ 选择接口
    def current_key(self) -> str:
        return self._current_key

    def select_tab(self, key: str) -> None:
        key = str(key)
        self._expand_group_of(key)
        for row, row_key in self._row_keys.items():
            if row_key != key:
                continue
            if self.nav.currentRow() == row:
                self._on_row_changed(row)
            else:
                self.nav.setCurrentRow(row)
            return

    def _expand_group_of(self, key: str) -> None:
        """深链/搜索跳到折叠组里的页时先把组展开，否则选中项在导航里看不见。"""
        for group, entries in self._grouped.items():
            if not any(entry_key == key for entry_key, _label in entries):
                continue
            if self._collapsed.get(group):
                self._collapsed[group] = False
                self._apply_collapsed_groups()
            return

    def select_label(self, label: str) -> None:
        for key, current in self._page_labels:
            entry = self._entries.get(key)
            title = str(getattr(entry[1], "title", "")) if entry is not None else ""
            if label in (current, title):
                self.select_tab(key)
                return

    # ------------------------------------------------------------ 聚合接口
    def dirty(self) -> bool:
        return any(page.dirty() for _key, page in self._pages)

    def draft(self) -> None:
        for _key, page in self._pages:
            page.draft()

    def confirm_save(self) -> None:
        for _key, page in self._pages:
            page.confirm_save()

    def discard_changes(self) -> None:
        for _key, page in self._pages:
            page.discard_changes()

    def dispose(self) -> None:
        for _key, page in self._pages:
            page.dispose()

    def keywords(self) -> list[str]:
        values = ["扩展", "模组", "mod", "插件", "安装", "卸载", "启用", "停用", "诊断"]
        for key, page in self._pages:
            values.append(str(getattr(page, "title", "")))
            entry = self._entries.get(key)
            if entry is not None:
                values.append(entry[0])
            getter = getattr(page, "keywords", None)
            if callable(getter):
                try:
                    values.extend(str(item) for item in getter())
                except Exception:
                    pass
        return values
