# -*- coding: utf-8 -*-
"""设置页「按区直找」的共用件：旧页分区顺序 + 页内分区跳转条 + 组描述。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算（``tests/
test_architecture.py``）没有余量，而本功能的主体是一张「组标题 → 一句人话」的描述表、
一段页内跳转条装配逻辑和一处布局顺序遍历，与对话框框体无关——按本仓库既有口径
（``settings_network`` / ``settings_quiet`` / ``settings_search`` /
``settings_default_marks`` / ``settings_music`` 都是同一个原因拆出来的）落在这里。

口径：

- **布局顺序而不是创建顺序**：域装配把旧页的行整表捞出来塞进共享卡片时，
  ``findChildren`` 给的是**创建顺序**——两处偶然一致，一处不一致就静默错位。
  ``sections_in_layout_order`` 走真实布局树，与用户在旧页看到的顺序同源。
- **跳转条只做「页内直达到区」**：不做新导航层、不改侧栏 10 域契约、不动任何行键。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from .settings_widgets import SettingRow, SettingsSection


def section_title(section: SettingsSection) -> str:
    """分区的正式标题：高级组在折叠按钮上，普通组在 ``sectionTitle`` 标签上。"""
    if section.toggle is not None:
        return section.toggle.text()
    label = section.findChild(QLabel, "sectionTitle")
    return label.text() if label is not None else ""


def _walk(widget, found: list[tuple[str, list[SettingRow]]]) -> None:
    layout = widget.layout()
    if layout is None:
        return
    for position in range(layout.count()):
        child = layout.itemAt(position).widget()
        if child is None:
            continue
        if isinstance(child, SettingsSection):
            found.append((section_title(child), list(child.rows)))
        else:
            # 折叠框等容器不进表：它的子分区才是用户眼里的「区」。
            _walk(child, found)


def sections_in_layout_order(page) -> list[tuple[str, list[SettingRow]]]:
    """旧页里按**布局顺序**排列的子分区（标题，行表）。

    ``page`` 可以是旧页（``QWidget``）、页内标签容器或任何含分区布局的控件。
    """
    found: list[tuple[str, list[SettingRow]]] = []
    _walk(page, found)
    return found


def rows_in_layout_order(page) -> list[SettingRow]:
    """旧页全部设置行，按布局顺序；没被任何分区收走的行按创建顺序垫在后面。"""
    rows = [row for _title, section_rows in sections_in_layout_order(page) for row in section_rows]
    seen = {id(row) for row in rows}
    rows.extend(row for row in page.findChildren(SettingRow) if id(row) not in seen)
    return rows
