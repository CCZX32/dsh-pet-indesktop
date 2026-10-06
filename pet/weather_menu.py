# -*- coding: utf-8 -*-
"""「查看天气」与「天气城市」菜单：建造器、城市对话框、城市列表读写。

**为什么独立成模块**：``context_menus/shared.py``（912 行）与
``modern_settings_dialog.py``（行数预算反复触顶）都不该再长；菜单行为本身又是
"联网搜索 + 模态对话框 + 配置写入"三件事的组合，放在这里可独立单测。

**菜单结构**（注册表动作 id → 建造器）：

    weather          「查看天气」      → pet.on_show_weather(pet)
    weather_cities   「天气城市」子菜单 → 城市清单（当前打勾 / 点击切换 /
                                        添加城市…（联网搜索或手填）/ 删除城市）

为什么是两个平级入口而不是一个「天气」子菜单：规格要求「查看天气」**点一下**
就出气泡，藏进子菜单会多一步；城市列表必须常驻可见（当前城市打勾），所以它自己
是个子菜单。两者同属 ``tools`` 段，默认布局相邻（见 modern-default-v1.json）。

**城市列表的读写口径**：``pet.cfg`` 在两条拓扑下都指向"用户那份全局配置"——
窗口路径是主 ``Config``，overlay 路径是 ``_SpriteConfig`` 视图（``get`` 转发主
配置、``set``/``save`` 经 ``__getattr__`` 转发到主配置对象）。因此城市列表是
全局设置：右键任意一只肥鱼加/删城市，所有肥鱼共用同一份清单。

**联网**：只有「添加城市…」的搜索会联网（走 ``WeatherClient.search_cities``，即
国内源直连那一条），后台线程执行、结果经 queued 信号回填对话框；搜索不阻塞菜单
关闭流程。

**口径**（与余额/音乐菜单一致）：动作 ``close_on_trigger``，回调在原生菜单跟踪
循环结束后才执行（macOS 上菜单未关时建顶层窗口/弹对话框会被 AppKit 抑制）。
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .weather import (
    WeatherClient,
    add_city,
    current_city,
    normalize_city_list,
    normalize_city_name,
    remove_city,
)

log = logging.getLogger(__name__)

EMPTY_HINT = "（还没有城市，先点下面的「添加城市…」）"
ADD_LABEL = "添加城市…"
REMOVE_LABEL = "删除城市"
SEARCH_IDLE_TEXT = "输入城市名后点「搜索」，或直接添加手填的名字（如 鹿城区）"


# ---------------------------------------------------------------- 配置读写
def _config_of(pet):
    cfg = getattr(pet, "cfg", None)
    return cfg if cfg is not None and callable(getattr(cfg, "get", None)) else None


def _save(cfg) -> None:
    saver = getattr(cfg, "save", None)
    if callable(saver):
        saver()


def _notify(pet, text: str) -> None:
    """用户可见的提示（城市上限/重名这类"操作没能生效"的原因），绝不静默。"""
    parent = getattr(pet, "dialog_parent", None) or pet
    try:
        QMessageBox.warning(parent, "天气城市", text)
    except Exception:  # noqa: BLE001 - 提示失败不该让菜单回调炸掉
        log.exception("天气城市提示失败")


def _show_weather(pet) -> None:
    callback = getattr(pet, "on_show_weather", None)
    if callable(callback):
        callback(pet)


def apply_added_city(pet, name) -> tuple[bool, str]:
    """把城市写进列表并设为当前城市；返回 ``(是否成功, 失败原因)``。"""
    cfg = _config_of(pet)
    if cfg is None:
        return False, "配置不可用"
    cities = normalize_city_list(cfg.get("weather_city_list"))
    updated, error = add_city(cities, name)
    if error:
        return False, error
    cfg.set("weather_city_list", updated)
    cfg.set("weather_city", normalize_city_name(name))
    _save(cfg)
    return True, ""


def switch_city(pet, city) -> None:
    """切换当前城市并落盘（城市不在列表里时顺手补进列表，保持两者一致）。"""
    cfg = _config_of(pet)
    if cfg is None:
        return
    selected = normalize_city_name(city)
    if not selected:
        return
    cfg.set("weather_city", selected)
    cities = normalize_city_list(cfg.get("weather_city_list"))
    if selected not in cities:
        updated, error = add_city(cities, selected)
        if not error:
            cfg.set("weather_city_list", updated)
    _save(cfg)


def remove_city_from_config(pet, city) -> None:
    """从列表删掉城市；删的是当前城市时当前切到剩下的第一个（列表空了就清空）。"""
    cfg = _config_of(pet)
    if cfg is None:
        return
    cities = normalize_city_list(cfg.get("weather_city_list"))
    remaining, new_current = remove_city(cities, city, current_city(cfg))
    cfg.set("weather_city_list", remaining)
    cfg.set("weather_city", new_current)
    _save(cfg)


# ---------------------------------------------------------------- 城市对话框
class WeatherCityDialog(QDialog):
    """添加城市：联网搜索候选 + 手填兜底（搜索不可用时仍能加城市）。

    **为什么手填必须留着**：源 A（中国天气网）搜不到的输入不该变成死路
    （真机实测「鹿城区」搜不到、「鹿城」才行；国外源也只认部分中文地名）。
    搜不到时状态栏明说"可以直接添加"，输入的垃圾名由取数阶段如实报失败。
    """

    search_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("weatherCityDialog")
        self.setWindowTitle("添加天气城市")
        self.setModal(True)
        self.setMinimumWidth(360)

        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("weatherCityName")
        self.name_edit.setPlaceholderText("城市名，如 鹿城区 / 北京 / Tokyo")
        self.search_btn = QPushButton("搜索", self)
        self.search_btn.setObjectName("weatherCitySearch")

        self.results = QListWidget(self)
        self.results.setObjectName("weatherCityResults")
        self.results.setMinimumHeight(120)
        self.results.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        self.status_label = QLabel(SEARCH_IDLE_TEXT, self)
        self.status_label.setObjectName("weatherCityStatus")
        self.status_label.setWordWrap(True)

        self.add_btn = QPushButton("添加", self)
        self.add_btn.setObjectName("weatherCityAdd")
        self.add_btn.setDefault(True)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.setObjectName("weatherCityCancel")

        query_row = QHBoxLayout()
        query_row.addWidget(self.name_edit, 1)
        query_row.addWidget(self.search_btn)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(self.add_btn)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("城市名", self))
        root.addLayout(query_row)
        root.addWidget(self.results, 1)
        root.addWidget(self.status_label)
        root.addLayout(buttons)

        self.search_btn.clicked.connect(self._request_search)
        self.name_edit.returnPressed.connect(self._request_search)
        self.name_edit.textChanged.connect(self._refresh_add_enabled)
        self.results.itemSelectionChanged.connect(self._refresh_add_enabled)
        self.add_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        self._refresh_add_enabled()

    # ---- 状态
    def typed_name(self) -> str:
        return self.name_edit.text().strip()

    def chosen_name(self) -> str:
        """最终要添加的城市名：选中的候选优先，否则用归一化后的手填值。"""
        item = self.results.currentItem()
        if item is not None:
            selected = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if selected:
                return selected
        return normalize_city_name(self.typed_name())

    def begin_search(self) -> None:
        self.search_btn.setEnabled(False)
        self.status_label.setText("搜索中…")

    def set_search_results(self, results, error: str = "") -> None:
        """回填搜索结果（GUI 线程调用）。空结果/失败时保留手填这条路。"""
        self.search_btn.setEnabled(True)
        self.results.clear()
        for candidate in results or ():
            label = candidate.name
            if candidate.region and candidate.region not in label:
                label = f"{candidate.name}（{candidate.region}）"
            item = QListWidgetItem(label, self.results)
            item.setData(Qt.ItemDataRole.UserRole, candidate.name)
        if self.results.count():
            self.results.setCurrentRow(0)
            self.status_label.setText(
                f"找到 {self.results.count()} 个候选，选中一个后点「添加」；也可以直接添加手填的名字。"
            )
        elif error:
            self.status_label.setText(f"搜索失败：{error}（可以直接添加你输入的城市名）")
        else:
            self.status_label.setText("没有找到这个城市（可以直接添加你输入的城市名）")
        self._refresh_add_enabled()

    def _refresh_add_enabled(self, *_args) -> None:
        self.add_btn.setEnabled(bool(self.chosen_name()))

    def _request_search(self) -> None:
        query = self.typed_name()
        if not query or not self.search_btn.isEnabled():
            return
        # 立即进入"搜索中"：对话框自己管这个状态，不等归属方回调（否则归属方
        # 没接上搜索链路时按钮会永远停在可点状态，用户以为点了没反应）。
        self.begin_search()
        self.search_requested.emit(query)


class _SearchBridge(QObject):
    """搜索线程 → GUI 线程的结果桥（queued 信号，同 weather_service 口径）。"""

    done = Signal(object, str)

    def __init__(self, dialog, query: str) -> None:
        super().__init__()
        self._dialog = dialog
        self.done.connect(self._apply)
        self._query = query

    def _apply(self, results, error) -> None:
        self._dialog.set_search_results(results, error)

    def run(self, searcher) -> None:
        try:
            results, error = searcher(self._query)
        except Exception as exc:  # noqa: BLE001 - 搜索失败要如实显示，不炸线程
            log.exception("天气城市搜索异常")
            results, error = [], f"{type(exc).__name__}: {exc}"
        self.done.emit(list(results or ()), str(error or ""))


def start_search(dialog, query: str, searcher, runner=None) -> None:
    """在后台跑一次城市搜索，结果经 queued 信号回填对话框。"""
    if not query:
        return
    runner = runner or _run_in_thread
    bridge = _SearchBridge(dialog, query)
    dialog._search_bridge = bridge  # 保活到结果落地
    dialog.begin_search()
    try:
        runner(lambda: bridge.run(searcher))
    except Exception as exc:  # noqa: BLE001 - 起线程失败也要把对话框从"搜索中"放出来
        log.exception("天气城市搜索线程启动失败")
        dialog.set_search_results([], f"{type(exc).__name__}: {exc}")


def _run_in_thread(work) -> None:
    threading.Thread(target=work, daemon=True, name="pet-weather-search").start()


def open_add_city_dialog(pet, *, dialog_factory=None, search=None, run_async=None) -> str:
    """打开「添加城市」对话框，返回用户选定的城市名（取消返回空串）。

    ``search`` / ``run_async`` / ``dialog_factory`` 可注入：测试用假对话框与假
    搜索函数，生产路径默认走 ``WeatherClient.search_cities``（国内源直连）。
    """
    factory = dialog_factory or (lambda parent=None: WeatherCityDialog(parent))
    searcher = search or (lambda query: WeatherClient().search_cities(query))
    parent = getattr(pet, "dialog_parent", None)
    if not isinstance(parent, QWidget):
        parent = pet if isinstance(pet, QWidget) else None
    dialog = factory(parent)
    dialog.search_requested.connect(
        lambda query: start_search(dialog, query, searcher, runner=run_async)
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return ""
    return dialog.chosen_name()


def add_city_flow(pet, *, dialog_factory=None, search=None, run_async=None,
                  notify=None) -> str:
    """「添加城市…」的完整流程：对话框 → 写入列表 → 设为当前 → 冒泡。

    返回实际加进去的城市名（取消/失败返回空串）；失败原因经 ``notify`` 告知用户
    （上限 12、重名这类"没生效"的原因绝不静默）。
    """
    name = open_add_city_dialog(
        pet, dialog_factory=dialog_factory, search=search, run_async=run_async
    )
    if not name:
        return ""
    ok, error = apply_added_city(pet, name)
    if not ok:
        (notify or (lambda text: _notify(pet, text)))(error)
        return ""
    _show_weather(pet)
    return normalize_city_name(name)


# ---------------------------------------------------------------- 菜单建造器
# 为什么这两个建造器在函数内导入 shared：``pet.weather_menu`` 被
# ``context_menus.legacy`` / ``registry`` 反向引用，而 shared 经包 ``__init__``
# 会带着 legacy 一起跑——模块级导入就成了循环。建造器只在真正建菜单时才需要
# 那两个原语，故按调用点导入（与 ``balance`` 的惰性 import 同一手法）。
def add_show_weather(menu: QMenu, pet, *, icons: bool = True):
    """「查看天气」：点一次就用气泡报当前城市的天气。"""
    from .context_menus.shared import add_action

    callback = getattr(pet, "on_show_weather", None)
    if callback is None:
        return None
    return add_action(menu, "查看天气", "weather" if icons else None,
                      lambda: callback(pet), close_on_trigger=True)


def add_weather_cities(menu: QMenu, pet, *, icons: bool = True):
    """「天气城市」子菜单：城市清单 + 切换 + 添加 + 删除。"""
    from .context_menus.shared import add_action, add_submenu, connect_action

    cfg = _config_of(pet)
    if cfg is None:
        return None
    submenu = add_submenu(menu, "天气城市", "weather" if icons else None)
    cities = normalize_city_list(cfg.get("weather_city_list"))
    current = current_city(cfg)
    if not cities:
        empty = submenu.addAction(EMPTY_HINT)
        empty.setEnabled(False)
    for city in cities:
        action = submenu.addAction(city)
        action.setCheckable(True)
        action.setChecked(city == current)
        action.setProperty("closeOnTrigger", True)
        connect_action(action, lambda city=city: _on_city_picked(pet, city))
    submenu.addSeparator()
    add_action(submenu, ADD_LABEL, None, lambda: add_city_flow(pet), close_on_trigger=True)
    if cities:
        remove_menu = add_submenu(submenu, REMOVE_LABEL)
        for city in cities:
            add_action(remove_menu, city, None,
                       lambda city=city: remove_city_from_config(pet, city),
                       close_on_trigger=True)
    return submenu


def _on_city_picked(pet, city: str) -> None:
    """点城市 = 切换 + 立刻冒一次泡（否则用户还要再点一次「查看天气」）。"""
    switch_city(pet, city)
    _show_weather(pet)
