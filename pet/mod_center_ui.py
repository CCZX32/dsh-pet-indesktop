# -*- coding: utf-8 -*-
"""MOD 中心界面：一串清单行 + 导入/筛选/批处理动作。

移植自 DLC 分支的 ``pet/mod_center_ui.py``。改动只在两处：

1. DLC 版从 ``pet/feature_management_ui.py`` 借 ``_BreakableLabel`` 与
   ``_WrappingActionButton``（那个模块属功能扩展面，本仓库没有）——两个助手都很小，
   按同样的可视行为落在本模块内（中文长串的断行点、按宽度定高的按钮），
   对外可视行为不变：长描述不撑横向滚动条、超长标识符能被强制断行。
2. 筛选按钮的种类来自 ``kinds``，不再写死三个（功能扩展侧未接入时，一个永远空着的
   分类按钮只是噪音）。默认值 = 全部已知种类，因此本模块对后端协议仍是通用的
   ——后端给什么种类就筛什么种类。

控件对后端只有一个鸭子类型契约（``controller``）：``entries()`` / ``perform()`` /
``import_source()`` / ``busy`` 四个属性方法，加 ``changed`` / ``busy_changed`` /
``result`` / ``batch_finished`` 四个信号。这条契约由 ``pet.mod_center_controller``
兑现，测试用桩对象同样能兑现（见 ``tests/test_mod_center_ui.py``）。

**ZIP 导入探针缺陷（S4 收口）**：「导入 ZIP」在 DLC 侧对**功能扩展**示例包会报
``worker_probe_failed``。S4 的判定是**逐环**的，不笼统说"已修复"：冻结版依赖目录的
长路径查找已修（``pet/frozen_runtime_paths.py``，before/after 证据见
``.scratch/dlc-fusion/S4-HANDOFF.md``）；而它上面那层 LPAC 原生探针沙箱在本仓库不存在，
功能包导入在更上游就按 ``self_check_sandbox_unavailable`` 如实拒绝——详见
``pet/mod_center_controller.py`` 的同名小节。本片只接角色资源，故该缺陷在本仓库不可达。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from .mod_center_controller import KIND_EXTENSION
from .mod_management import KIND_RESOURCE, ModSelection
from .settings_widgets import ResponsiveActionRow, SettingsPopupMenu

ALL_KINDS = "全部"

_LONG_TOKEN = re.compile(r"[!-~]{24,}")


class _PlainLabel(QLabel):
    """纯文本标签：长标识符按显示宽度插入断行点，原文留在提示与读屏描述里。

    QLabel 的 ``WordWrap`` 只在词边界断行，一长串没有空格的标识符会撑出横向滚动条
    （DLC 的 ``_BreakableLabel`` 就是为这个存在的）。断行点是**零宽空格**，只影响
    呈现；提示与读屏给的一直是原文。

    构造期先留空再调自己的 ``setText``：Qt 的 C++ 构造器内联调 ``QLabel.setText``，
    不会回到 Python 覆写上（那样第一串文本就漏掉了断行点）。
    """

    def __init__(self, text="", parent=None):
        super().__init__("", parent)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(_LONG_TOKEN.sub(lambda match: "\u200b".join(match.group()), str(text)))
        self.setToolTip(str(text))
        self.setAccessibleDescription(str(text))


def _label(text, parent=None, *, hint=False):
    label = _PlainLabel(str(text), parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    if hint:
        label.setObjectName("settingHint")
    return label


class _WrappingActionButton(QPushButton):
    """按钮文字按可用宽度定高（本地化长文案不裁切）。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(text)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.setMinimumHeight(self.heightForWidth(self.width()))

    def _padding(self) -> tuple[int, int]:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        size = self.style().sizeFromContents(QStyle.ContentsType.CT_PushButton, option, QSize(0, 0), self)
        return max(20, size.width()), max(10, size.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        _horizontal, vertical = self._padding()
        return QSize(160, self.fontMetrics().height() + vertical)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True


class ModRow(QWidget):
    """一行一件已安装/可用的 MOD：选择框、名字与版本、来源、说明、动作按钮。"""

    def __init__(self, entry, center):
        super().__init__(center)
        self.entry, self.center = entry, center
        self.setObjectName("modRow")
        self.setAccessibleName(entry.name + " " + entry.kind)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        header = QHBoxLayout()
        self.check = QCheckBox(self)
        self.check.setAccessibleName("选择 " + entry.name)
        self.check.toggled.connect(lambda checked: center.select(entry.key, checked))
        header.addWidget(self.check)
        header.addWidget(_label(entry.name + "  " + entry.version, self), 1)
        layout.addLayout(header)
        source = {"bundled": "内置", "legacy": "手动目录", "installed": "已安装"}.get(entry.source, entry.source)
        layout.addWidget(_label(entry.kind + " · " + source + " · " + (entry.pending or ("已启用" if entry.enabled else "未启用")), self, hint=True))
        self.description = _label((entry.description[:180] + "…" if len(entry.description) > 180 else entry.description) or "作者未提供说明", self, hint=True)
        layout.addWidget(self.description)
        self.toggle = QPushButton("停用" if entry.enabled else "启用", self)
        self.toggle.setEnabled(entry.managed and not entry.pending)
        self.toggle.clicked.connect(lambda: center.controller.perform("disable" if entry.enabled else "enable", [entry.key]))
        action = "使用" if entry.kind == KIND_RESOURCE else "设置"
        self.settings = QPushButton(action, self)
        self.settings.setEnabled(center.can_use if entry.kind == KIND_RESOURCE else not entry.pending)
        self.settings.setToolTip(center.use_hint if entry.kind == KIND_RESOURCE else "")
        self.settings.clicked.connect(self._settings)
        self.update = QPushButton("更新", self)
        self.update.setEnabled(entry.managed and not entry.pending)
        self.update.clicked.connect(lambda: center.choose_update(entry))
        self.more = QPushButton("更多", self)
        menu = SettingsPopupMenu(self.more)
        self.delete_action = menu.addAction("删除安装副本")
        self.delete_action.setEnabled(entry.managed)
        self.delete_action.triggered.connect(lambda: center.delete([entry.key]))
        menu.addAction("完整说明").triggered.connect(self._details)
        menu.addAction("打开所在目录").triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(entry.path))))
        rollback = menu.addAction("回滚上一版")
        rollback.setEnabled(entry.managed and not entry.pending)
        rollback.triggered.connect(lambda: center.controller.perform("rollback", [entry.key]))
        self.more.setMenu(menu)
        layout.addWidget(ResponsiveActionRow(self.toggle, [self.settings, self.update, self.more], self))
        self.message = _label(center.messages.get(entry.key, ""), self)
        self.message.setVisible(bool(self.message.text()))
        layout.addWidget(self.message)

    def _settings(self):
        if self.entry.kind == KIND_RESOURCE:
            self.center.controller.perform("use", [self.entry.key])
        else:
            self.center.settings_requested.emit(self.entry.id)

    def _details(self):
        box = QMessageBox(self)
        box.setWindowTitle(self.entry.name)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(self.entry.description or "作者未提供说明")
        box.setInformativeText(f"{self.entry.id}\n{self.entry.path}")
        box.exec()


class ModCenterWidget(QWidget):
    """MOD 中心控件：导入、搜索、分类、批处理、清单。

    除下面这条契约外，后端还可以声明两个**可选**能力（没有就按"能"处理，桩后端因此
    只写协议也行）：``can_use``（能不能直接给本设置页所属的桌宠换装）与 ``use_hint``
    （不能时按钮上那句说明）。
    """

    settings_requested = Signal(str)

    def __init__(self, controller, parent=None, *, kinds=None):
        super().__init__(parent)
        self.controller = controller
        self.selection = ModSelection()
        self.messages = {}
        self.rows = {}
        self.kind = ALL_KINDS
        self.kinds = tuple(kinds) if kinds is not None else (KIND_RESOURCE, KIND_EXTENSION)
        self.setObjectName("modCenter")
        self.setAccessibleName("MOD 管理中心")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.import_zip = _WrappingActionButton("导入 ZIP", self)
        self.import_directory = _WrappingActionButton("导入目录", self)
        for button, archive in ((self.import_zip, True), (self.import_directory, False)):
            button.setAccessibleName(button.text())
            button.setAccessibleDescription("选择完整 MOD 包；新包默认停用，导入后点击启用。")
            button.clicked.connect(lambda _checked=False, archive=archive: self.choose_source(archive))
        layout.addWidget(ResponsiveActionRow(self.import_zip, [self.import_directory], self))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索名称或说明")
        self.search.setAccessibleName("搜索 MOD")
        self.search.textChanged.connect(self._filter_changed)
        layout.addWidget(self.search)
        filter_row = QHBoxLayout()
        self.filters = {}
        self.group = QButtonGroup(self)
        for kind in (ALL_KINDS, *self.kinds):
            button = QPushButton(kind, self)
            button.setAccessibleName(kind)
            button.setCheckable(True)
            button.setChecked(kind == self.kind)
            button.clicked.connect(lambda _checked=False, kind=kind: self._set_kind(kind))
            self.filters[kind] = button
            self.group.addButton(button)
            filter_row.addWidget(button)
        layout.addLayout(filter_row)
        layout.addWidget(_label("选择完整包即可导入；新包默认停用，导入后点「启用」再使用。只导入可信来源。", self, hint=True))
        self.select_all = QCheckBox("全选当前结果", self)
        self.select_all.toggled.connect(self._select_all)
        layout.addWidget(self.select_all)
        self.batch = QWidget(self)
        batch_layout = QVBoxLayout(self.batch)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        self.enable_selected = QPushButton("启用", self.batch)
        self.disable_selected = QPushButton("停用", self.batch)
        self.delete_selected = QPushButton("删除", self.batch)
        self.enable_selected.clicked.connect(lambda: self.controller.perform("enable", self._selected()))
        self.disable_selected.clicked.connect(lambda: self.controller.perform("disable", self._selected()))
        self.delete_selected.clicked.connect(lambda: self.delete(self._selected()))
        batch_layout.addWidget(ResponsiveActionRow(self.enable_selected, [self.disable_selected, self.delete_selected], self.batch))
        layout.addWidget(self.batch)
        self.summary = _label("", self)
        self.summary.setAccessibleName("MOD 操作结果")
        layout.addWidget(self.summary)
        self.list = QWidget(self)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        layout.addWidget(self.list)
        controller.changed.connect(self.refresh)
        controller.result.connect(self._result)
        controller.batch_finished.connect(self._batch_finished)
        controller.busy_changed.connect(self._busy)
        self.refresh()

    # --------------------------------------------------------- 宿主能力

    @property
    def can_use(self) -> bool:
        """后端能不能直接给本设置页所属的桌宠换装（不能时按钮置灰，而不是点了才失败）。"""
        return bool(getattr(self.controller, "can_use", True))

    @property
    def use_hint(self) -> str:
        return str(getattr(self.controller, "use_hint", "") or "")

    # ------------------------------------------------------------- 选择

    def _selected(self) -> list[str]:
        return [key for key in self.rows if key in self.selection.selected]

    def select(self, key, checked) -> None:
        if checked and key in self.rows:
            self.selection.selected.add(key)
        else:
            self.selection.selected.discard(key)
        self.batch.setVisible(bool(self.selection.selected))

    def _select_all(self, checked) -> None:
        for row in self.rows.values():
            row.check.setChecked(checked)

    def _set_kind(self, kind) -> None:
        self.kind = kind
        self._filter_changed()

    def _filter_changed(self, *_args) -> None:
        self.selection.selected.clear()
        self.select_all.blockSignals(True)
        self.select_all.setChecked(False)
        self.select_all.blockSignals(False)
        self.refresh()

    # ------------------------------------------------------------- 清单

    def refresh(self) -> None:
        query = self.search.text().strip().casefold()
        entries = [row for row in self.controller.entries() if (self.kind == ALL_KINDS or row.kind == self.kind)
                   and (not query or query in (row.name + " " + row.description + " " + row.id).casefold())]
        self.selection.visible = {entry.key for entry in entries}
        self.selection.selected.intersection_update(self.selection.visible)
        signature = tuple(entries)
        if getattr(self, "_entries_signature", None) == signature:
            for key, row in self.rows.items():
                row.check.blockSignals(True)
                row.check.setChecked(key in self.selection.selected)
                row.check.blockSignals(False)
            self.batch.setVisible(bool(self.selection.selected))
            self._busy(self.controller.busy)
            return
        self._entries_signature = signature
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.rows = {}
        for entry in entries:
            if self.rows:
                line = QFrame(self.list)
                line.setFrameShape(QFrame.Shape.HLine)
                self.list_layout.addWidget(line)
            row = ModRow(entry, self)
            self.rows[entry.key] = row
            row.check.setChecked(entry.key in self.selection.selected)
            self.list_layout.addWidget(row)
        if not entries:
            self.list_layout.addWidget(_label("没有符合条件的 MOD。可导入 ZIP 或目录。", self.list, hint=True))
        self.batch.setVisible(bool(self.selection.selected))
        self._busy(self.controller.busy)

    def _busy(self, busy) -> None:
        self.list.setEnabled(not busy)
        self.batch.setEnabled(not busy)
        self.import_zip.setEnabled(not busy)
        self.import_directory.setEnabled(not busy)
        if busy:
            self.summary.setText("正在处理，请稍候…")

    def _result(self, key, outcome) -> None:
        if key:
            self.messages[key] = outcome.message
            if key in self.rows:
                self.rows[key].message.setText(outcome.message)
                self.rows[key].message.show()
        self.summary.setText(outcome.message)

    def _batch_finished(self, results) -> None:
        if len(results) == 1:
            self.summary.setText(results[0][1].message)
        elif len(results) > 1:
            succeeded = sum(outcome.success for _key, outcome in results)
            pending = sum(outcome.pending for _key, outcome in results)
            self.summary.setText(f"已处理 {len(results)} 项：成功 {succeeded}，等待退出 {pending}，未完成 {len(results)-succeeded-pending}。详情见对应行。")

    # ------------------------------------------------------------- 动作

    def choose_source(self, archive, expected=None) -> None:
        path = QFileDialog.getOpenFileName(self, "选择 MOD ZIP", "", "MOD ZIP (*.zip)")[0] if archive else QFileDialog.getExistingDirectory(self, "选择完整 MOD 包目录")
        if path:
            self.controller.import_source(path, expected=expected)

    def choose_update(self, entry) -> None:
        menu = SettingsPopupMenu(self)
        menu.addAction("选择新版 ZIP").triggered.connect(lambda: self.choose_source(True, entry.key))
        menu.addAction("选择新版目录").triggered.connect(lambda: self.choose_source(False, entry.key))
        menu.exec(self.mapToGlobal(self.rect().center()))

    def delete(self, keys) -> None:
        entries = [self.rows[key].entry for key in keys if key in self.rows and self.rows[key].entry.managed]
        if not entries:
            self.summary.setText("内置资源和手动目录不由管理中心删除。")
            return
        names = "\n".join(entry.name for entry in entries)
        box = QMessageBox(QMessageBox.Icon.Warning, "删除 MOD", f"删除以下 {len(entries)} 个 MOD 的安装副本？\n{names}",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setInformativeText("原始 ZIP、外部源目录和个人配置保留。正在使用的角色包要先换装才能删除。")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.controller.perform("delete", [entry.key for entry in entries])
