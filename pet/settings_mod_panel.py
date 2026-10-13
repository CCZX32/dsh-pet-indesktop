# -*- coding: utf-8 -*-
"""owner 设置面板容器：把作者的小部件挂进 Core 拥有的壳，并转发草稿四件套。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算（``tests/
test_architecture.py``）没有余量，而"一个扩展自己的设置界面"是自足的一组控件——照
``settings_proactive_worker.py`` / ``settings_quiet.py`` 的先例拆出来。

容器只做三件事，别的什么都不做：

1. **挂载**：``settings_factory(context, parent)`` 的返回可能是 QWidget，也可能是一个
   "组件"对象（自己持协议、``.widget`` 才是要挂的界面）。后者挂它的 ``.widget``，
   协议仍转发给组件本身——草稿属于组件，不属于它的界面。
2. **转发**：``dirty`` / ``draft`` / ``confirm_save`` / ``discard_changes`` / ``dispose``
   原样转给作者组件；作者只给界面、不给协议时**如实降级**为"没有可保存的设置"，绝不
   假造一个草稿层（假造会让事务层的草稿门对空面板永远说不清）。
3. **收口**：Core 自己建的容器由 Core ``deleteLater``；作者的组件由它自己的
   ``dispose()``（缺失时 ``deleteLater``）带走。``dispose()`` 幂等，并**清掉草稿快照**
   ——面板没了就不能再卡住事务层。

草稿快照（:meth:`OwnerSettingsPanel.push_drafts`）是 GUI 线程在**派发前**喂给
:class:`pet.plugins.lifecycle.FeatureHostLifecycle` 的那份不可变表；后台线程只读它，
面板对象一次都不进后台线程（并发纪律见 ``pet/plugins/lifecycle.py`` 的模块 docstring）。

撤回前的三键询问（:func:`prepare_revocation`）与事务层的 ``draft_blocked`` 是**同一条
判据的两个入口**，读的是同一份快照；两个入口同源才不会出现"预检说可以、事务层说不行"。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

__all__ = [
    "DRAFT_SAVE_FAILED",
    "DRAFT_SAVED",
    "DISCARDED",
    "OwnerSettingsPanel",
    "REVOCATION_TEXT",
    "REVOCATION_TITLE",
    "prepare_revocation",
    "resolve_revocation",
]

#: 面板自己的状态行文案（只在这里改；设置页文案 lint 口径：不出现大写缩写黑话）。
DRAFT_SAVED = "已保存此扩展的设置。"
DRAFT_SAVE_FAILED = "未能保存：这个扩展的配置已在别处变化。请复制草稿后点「放弃修改」重新读取。"
DRAFT_SAVE_REFUSED = "未能保存：这个扩展的设置界面拒绝了这次保存。请复制草稿后点「放弃修改」重新读取。"
DISCARDED = "已放弃草稿，重新读取了这个扩展的配置。"
READ_ONLY = "这个扩展没有提供可保存的设置。"
DISPOSE_FAILED = "这个扩展的设置界面收尾时报错，已按未知状态收走；重开设置页即可。"

#: 撤回（停用 / 删除 / 更新）前的三键询问。
REVOCATION_TITLE = "扩展有未保存编辑"
REVOCATION_TEXT = "此扩展有未保存编辑。保存、放弃，还是取消本次操作？"

#: 三键询问的三个结果（字符串而不是 Qt 枚举，`resolve_revocation` 才好被无对话框地测）。
_CHOICES = ("save", "discard", "cancel")


class OwnerSettingsPanel(QWidget):
    """一个 owner 的设置面板容器；协议缺项一律如实降级，不猜。"""

    def __init__(self, owner: str, component: Any, *, title: str = "", lifecycle=None, parent=None) -> None:
        super().__init__(parent)
        self.owner = str(owner)
        self.component = component
        self.title = str(title or self.owner)
        self.lifecycle = lifecycle
        self.embedded = self._resolve_widget(component)
        self._disposed = False

        self.status = QLabel("", self)
        self.status.setObjectName("settingValue")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)

        self.save_button = QPushButton("保存此扩展设置", self)
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._on_save)

        row = QHBoxLayout()
        row.addWidget(self.save_button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.embedded)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.push_drafts()

    # --------------------------------------------------------- 作者组件面

    def _resolve_widget(self, component: Any) -> QWidget:
        if isinstance(component, QWidget):
            return component
        candidate = getattr(component, "widget", None)
        if isinstance(candidate, QWidget):
            return candidate
        raise TypeError("a settings component must be a QWidget or expose a .widget QWidget")

    def _forward(self, name: str, *args, default=None, error_text: str = ""):
        """把一次调用转给作者组件。

        三种结局要分开，不许混成一句「失败了」：

        ``ok``      作者组件有这个面，调用返回了；
        ``missing`` 作者组件没有这个面——如实降级（没有可保存的设置），不是错误；
        ``error``   有这个面但抛了错——落一条脱敏状态，绝不冒进 Qt 事件循环。
        """
        method = getattr(self.component, name, None)
        if not callable(method):
            return default, "missing"
        try:
            return method(*args), "ok"
        except Exception as exc:
            self.status.setText(error_text or f"这个扩展的设置界面在「{name}」时报错：{type(exc).__name__}")
            return default, "error"

    # ------------------------------------------------------------- 协议

    def dirty(self) -> bool:
        value, outcome = self._forward("dirty", default=False)
        return bool(value) if outcome == "ok" else False

    def draft(self) -> Any:
        value, outcome = self._forward("draft", default={})
        return value if outcome == "ok" else {}

    def confirm_save(self) -> bool:
        # 配置 CAS 冲突（`configuration_changed`）是作者侧最可能的失败：它抛的是
        # 仓库统一的 StateError，映射成"下一步怎么做"那句，而不是一个错误类名。
        saved, outcome = self._forward("confirm_save", default=False, error_text=DRAFT_SAVE_FAILED)
        if outcome == "missing":
            self.status.setText(READ_ONLY)
            return False
        if outcome == "error":
            return False
        self.status.setText(DRAFT_SAVED if saved else DRAFT_SAVE_REFUSED)
        self.push_drafts()
        return bool(saved)

    def discard_changes(self) -> bool:
        done, outcome = self._forward("discard_changes", default=False)
        if outcome == "missing":
            self.status.setText(READ_ONLY)
            return False
        if outcome == "error":
            return False
        self.status.setText(DISCARDED if done else READ_ONLY)
        self.push_drafts()
        return bool(done)

    def _on_save(self) -> None:
        self.confirm_save()

    # ------------------------------------------------------- 草稿快照面

    @property
    def disposed(self) -> bool:
        """已经收尾过（``deleteLater`` 还没轮到也一样算）：容器不可再用。"""
        return self._disposed

    def push_drafts(self) -> None:
        """GUI 线程：把这个面板当下的草稿名推进事务层读的那份快照。

        名字取面板标题（作者包的显示名），不是渲染出来的一行文本——快照会出现在
        事务层的理由里，读的人要能对上"是哪一个扩展的面板"。面板已 dispose 时推空。
        """
        if self.lifecycle is None:
            return
        if self._disposed:
            self.lifecycle.note_drafts(self.owner, ())
            return
        self.lifecycle.note_drafts(self.owner, (self.title,) if self.dirty() else ())

    # ------------------------------------------------------------- 收口

    def dispose(self) -> None:
        """幂等收尾：作者的组件自己走，Core 建的容器由 Core 收。"""
        if self._disposed:
            return
        self._disposed = True
        self.push_drafts()
        try:
            self._forward("dispose")
        except Exception:  # _forward 已吞异常；这里只兜住极端情况
            self.status.setText(DISPOSE_FAILED)
        self.hide()
        self.setParent(None)
        self.deleteLater()


# --------------------------------------------------------- 撤回前的三键询问

def resolve_revocation(panel: OwnerSettingsPanel | None, choice: str) -> bool:
    """把一次三键选择落成"能不能继续"（``cancel`` / 保存失败 = 不能继续）。

    保存失败必须返回 False：动作要动的是这个包的安装副本，而配置根本没存下去——
    继续就是拿旧配置去停用/删除它。
    """
    if panel is None or not panel.dirty():
        return True
    if choice not in _CHOICES:
        return False
    if choice == "discard":
        return panel.discard_changes()
    if choice == "save":
        return panel.confirm_save()
    return False


def prepare_revocation(panel: OwnerSettingsPanel | None, parent=None) -> bool:
    """有草稿时问一次「保存 / 放弃 / 取消」；返回 False = 中止这次撤回动作。

    没有面板、或面板干净 = 直接放行（不弹窗）。
    """
    if panel is None or not panel.dirty():
        return True
    answer = QMessageBox.question(
        parent or panel,
        REVOCATION_TITLE,
        REVOCATION_TEXT,
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer == QMessageBox.StandardButton.Save:
        return resolve_revocation(panel, "save")
    if answer == QMessageBox.StandardButton.Discard:
        return resolve_revocation(panel, "discard")
    return resolve_revocation(panel, "cancel")
