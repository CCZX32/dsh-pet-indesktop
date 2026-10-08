# -*- coding: utf-8 -*-
"""设置页「按区直找」：旧页分区顺序 + 页内分区跳转条 + 组描述。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算（``tests/
test_architecture.py``）没有余量，而本功能的主体是一段页内跳转条装配逻辑、一个换行
用的流式布局和一张「组标题 → 一句人话」的描述表，与对话框框体无关——按本仓库既有
口径（``settings_network`` / ``settings_quiet`` / ``settings_search`` /
``settings_default_marks`` / ``settings_music`` 都是同一个原因拆出来的）落在这里，
对话框只留一行 ``install(self)`` 接线。

口径：

- **布局顺序而不是创建顺序**：域装配把旧页的行整表捞出来塞进共享卡片时，
  ``findChildren`` 给的是**创建顺序**——两处偶然一致，一处不一致就静默错位。
  ``sections_in_layout_order`` 走真实布局树，与用户在旧页看到的顺序同源。
- **跳转条只做「页内直达到区」**：不做新导航层、不改侧栏 10 域契约、不动任何行键。
  点一下把目标区顶到视口上沿（``setValue``），不用 ``ensureWidgetVisible``——后者
  只保证「看得见」，长卡片会把目标压在屏幕下沿，等于没跳。
- **组描述是「这里是什么」的一句人话**：文案全部集中在本模块的 ``SECTION_GUIDE``，
  控件只负责呈现；高级组收起时描述照常可见（否则要先展开才知道里面是什么）。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from .settings_widgets import CollapsibleGroup, SettingRow, SettingsSection, SettingsTabContainer

#: 少于这么多「区」就不装跳转条：两三个区一眼扫得完，多一条横条只是噪音。
ANCHOR_MIN_BLOCKS = 4


def section_title(section: SettingsSection) -> str:
    """分区的正式标题：高级组在折叠按钮上，普通组在 ``sectionTitle`` 标签上。"""
    if section.toggle is not None:
        return section.toggle.text()
    label = section.findChild(QLabel, "sectionTitle")
    return label.text() if label is not None else ""


def _layout_children(widget) -> list[QWidget]:
    """布局顺序的直接子控件（不是 ``findChildren`` 的创建顺序）。"""
    layout = widget.layout()
    if layout is None:
        return []
    children = []
    for position in range(layout.count()):
        child = layout.itemAt(position).widget()
        if child is not None:
            children.append(child)
    return children


def blocks_in_layout_order(page) -> list[tuple[str, QWidget]]:
    """页内**顶层块**（分区 / 折叠框）按布局顺序；跳转条一格对一块。"""
    blocks = []
    for child in _layout_children(page):
        if isinstance(child, CollapsibleGroup):
            blocks.append((child.toggle.text(), child))
        elif isinstance(child, SettingsSection):
            blocks.append((section_title(child), child))
    return blocks


def sections_in_layout_order(page) -> list[tuple[str, list[SettingRow]]]:
    """页内所有分区（含折叠框里的子分区）按布局顺序，返回 (标题, 行表)。"""
    found: list[tuple[str, list[SettingRow]]] = []

    def walk(node) -> None:
        for child in _layout_children(node):
            if isinstance(child, SettingsSection):
                found.append((section_title(child), list(child.rows)))
            elif isinstance(child, CollapsibleGroup):
                walk(child.body)

    walk(page)
    return found


def rows_in_layout_order(page) -> list[SettingRow]:
    """页内全部设置行按布局顺序；没被任何分区收走的行按创建顺序垫在后面。"""
    rows = [row for _title, section_rows in sections_in_layout_order(page) for row in section_rows]
    seen = {id(row) for row in rows}
    rows.extend(row for row in page.findChildren(SettingRow) if id(row) not in seen)
    return rows


def tab_container(widget) -> SettingsTabContainer | None:
    """页内容里的页内标签容器（没有就是 ``None``）。"""
    if isinstance(widget, SettingsTabContainer):
        return widget
    return widget.findChild(SettingsTabContainer, "settingsTaskTabs") if widget is not None else None


def current_page_content(scroll: QScrollArea) -> QWidget:
    """跳转条要列的那一屏内容：页内标签域取当前标签页，否则就是滚动内容本身。"""
    content = scroll.widget()
    tabs = tab_container(content)
    return tabs.stack.currentWidget() if tabs is not None else content


# --------------------------------------------------------------------------- 组描述
#: 组标题 → 一句人话（显示在组标题 / 折叠头下面，12px 灰字）。
#:
#: 写法：说「这里是什么、改了会怎样」，一句话，不出现黑话（同一判据见
#: ``tests/test_settings_copy_lint.py``）。新增组必须在这里补一行，
#: ``tests/test_settings_page_guide.py`` 的覆盖率守卫会盯住。
SECTION_GUIDE: dict[str, str] = {
    # 常规
    "应用启动": "开机后要不要自动把桌宠叫起来。",
    "窗口与系统": "它压在别的窗口上面还是能被盖住，全屏玩游戏时让不让位。",
    "启动项（高级）": "随桌宠启动（不是开机）时顺手把 dsh 服务拉起来；可以只起服务，也可以连界面一起打开。",
    # 桌宠
    "显示": "桌宠和它的气泡显示多大、多透明。",
    "音乐关联": "听到音乐就唱歌、显示歌词；按你在用的播放器挑对应开关。",
    "播放器路径与标题格式（高级）": "播放器装在哪儿、歌名从哪儿取。默认值对大多数人是好的。",
    # 非 Windows 上不存在「标题格式」行，组名跟着退化（见 settings_music）。
    "播放器路径（高级）": "播放器装在哪儿。默认值对大多数人是好的。",
    "动画与移动": "动作播放多快、待机时自己走动还是原地待着。",
    "拖拽与弹射": "拖它、甩它、把它弹出去时的手感。",
    "边缘探头": "拖到屏幕边上，它会探出身子看一眼再缩回去。",
    "生小肥鱼": "再生成一只时它多大，以及随不随主桌宠的设置。",
    "多开碰撞": "多只桌宠之间撞来撞去，撞出声音。",
    "碰撞参数（高级）": "调撞击的弹跳、摩擦和力度；数值越小越文静。",
    # 互动
    "输入": "鼠标点在它身上时，点击要不要穿到底下的窗口。",
    "点击反馈": "点它一下会发生什么：音效、说句话、转个圈、报余额。",
    "自言自语": "没人理它的时候，它多久冒一句话、说什么。",
    "天气": "在气泡里带上你所在城市的天气。",
    # 菜单
    "内容与布局": "右键菜单长什么样：有哪些项、按什么顺序排。",
    "已配置应用": "菜单里「快捷启动」子菜单放哪些应用。",
    "菜单外观": "菜单的配色、圆角、字体和透明度。",
    "高级配色": "逐项指定浅色、深色菜单的底色与文字色。",
    "彩蛋入口": "菜单里那个小彩蛋，以及它弹出来的图和话。",
    # 桌面组件
    "桌面胶囊（灵动岛）": "屏幕边上那条小胶囊：显示什么、点它做什么、怎么收起来。",
    "网络延迟检测（高级）": "胶囊多久测一次网络延迟（开了「网络」这条信息才有用）；速率监测不产生额外流量，和这一项无关。",
    # AI 与对话
    "API 列表": "你配过的服务商清单，在这里增删和切换。",
    "模型与连接": "当前用哪家、哪个模型、密钥填什么、人设提示词写什么。",
    "系统通知": "你没在看聊天窗时（切去干别的），回复和失败会弹到桌面右下角；点一下跳回聊天窗。",
    "视觉能力": "看图的活儿交给谁：跟聊天用同一家，还是单独配一个。",
    "生成参数（高级）": "等待上限、随机程度、回复长度这些底层旋钮。",
    "对话窗口": "聊天窗的配色、背景图和透明度。",
    "余额与服务状态": "余额多久刷一次，以及高峰、空闲时段各显示什么话。",
    # 自动化与联动
    "待办提醒": "到点了提醒你该做什么；待办条目在右键菜单「待办提醒」面板里增删改。",
    "免打扰": "开启后普通提醒先攒着，退出免打扰时统一汇报；审批、报错这类要你回应的提示照常冒出来。",
    "主动识屏 · 开关与节奏": "它偶尔看看你正在用的软件，说句话。截图不保存。",
    "主动识屏 · 什么时候看": "什么时候才看：要不要先闲置才看，以及桌宠处于鼠标穿透状态时算不算数。",
    "主动识屏 · 看哪些软件": "只看你点名的软件；看过留下的痕迹随时能清掉。",
    "主动识屏 · 细调（高级）": "看得多勤、多久搭一次话、一天最多看几次，以及不花钱的试运行。"
                        "预设选「自定义参数」时这些参数才生效；手动改参数保存后会自动落成自定义预设。",
    "消费统计": "每一轮结束时报一报这轮花了多少钱。",
    "Agent 联动": "编程助手开始干活、干完活、出错时的提示音。",
    "提示音效": "三种时机各用哪段声音、多大声、多久内不重复。",
    "文案风格与模板": "它说话是什么风格，以及一份可以整体替换的文案模板。",
    "自定义台词（逐事件文案）": "每个事件各说什么，逐条改；不改也能正常用。",
    "事件气泡文案": "按事件分组的气泡台词，一行一条。",
    # 语音
    "语音报时 · 何时报": "几点说话、多久说一次。",
    "语音报时 · 用什么声音": "用哪个音色，语速、音调、音量各是多少。",
    "语音报时 · 说什么": "报完时间加不加台词、冒不冒气泡，以及先试听一句。",
    "节日提醒 · 开关": "开不开节日提醒、提醒哪些节日、要不要一起念出来。",
    "节日提醒 · 时间": "一天提醒几次，或者自己排几个时间点。",
    "节日提醒 · 文案": "节日文案从哪儿来，以及先预览一次看看效果。",
    # 文件识别
    "拖文件解读": "把文件拖到桌宠身上，它会读一遍并说点什么。",
}


def apply_descriptions(root) -> None:
    """把 ``SECTION_GUIDE`` 注入 ``root``（一个域页的滚动内容）里的分区 / 折叠框。

    ``root`` 是域页 ``settingsScroll`` 的 widget，不是整个对话框：域装配末尾旧的散页
    已被 ``deleteLater``，整框遍历会顺手碰这些待销毁的壳（无害，但没有一处需要它们）。
    标题做键，缺项留空。
    """
    for section in root.findChildren(SettingsSection):
        section.set_description(SECTION_GUIDE.get(section_title(section), ""))
    for box in root.findChildren(CollapsibleGroup):
        box.set_description(SECTION_GUIDE.get(box.toggle.text(), ""))


# ------------------------------------------------------------------------- 跳转条
class _FlowLayout(QLayout):
    """把 chip 横向排开、放不下就换行的简易流式布局（Qt 没有内置 FlowLayout）。"""

    def __init__(self, parent=None, *, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = int(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt API
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt API
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt API
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        return self._reflow(QRect(0, 0, int(width), 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt API
        super().setGeometry(rect)
        self._reflow(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._visible_items():
            size = size.expandedTo(item.minimumSize())
        return size

    def _visible_items(self) -> list:
        # 整组被依赖隐藏时 chip 跟着藏起来，藏起来的不能继续占位（否则留空洞）。
        return [item for item in self._items
                if item.widget() is None or not item.widget().isHidden()]

    def _reflow(self, rect: QRect, *, dry_run: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._visible_items():
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right():
                x, y, line_height = rect.x(), y + line_height + self._spacing, 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class _SettingsAnchorBar(QWidget):
    """页头标题下方那一排 chip：一个可见分区一格，点一下顶对齐滚过去。"""

    def __init__(self, heading_host: QWidget, scroll: QScrollArea):
        super().__init__(heading_host)
        self.setObjectName("settingsPageAnchors")
        self._scroll = scroll
        self._layout = _FlowLayout(self)
        self._chips: list[QPushButton] = []
        self._blocks: list[tuple[str, QWidget]] = []
        self._tabs = tab_container(scroll.widget())
        if self._tabs is not None:
            # 页内标签各是一组区：换标签就把跳转条换成那一组的。
            self._tabs.currentKeyChanged.connect(self._on_tab_changed)
        heading_host.layout().addWidget(self)
        self.rebuild()

    # ---------------------------------------------------------------- 装配
    def rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._chips = []
        self._blocks = blocks_in_layout_order(current_page_content(self._scroll))
        for title, block in self._blocks:
            chip = QPushButton(title, self)
            chip.setObjectName("settingsPageAnchor")
            chip.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            chip.setAccessibleName(f"跳到「{title}」分区")
            chip.clicked.connect(lambda _checked=False, target=block: self.jump_to(target))
            block.installEventFilter(self)
            self._chips.append(chip)
            self._layout.addWidget(chip)
        self.setVisible(len(self._blocks) >= ANCHOR_MIN_BLOCKS)
        self._sync_visibility()

    def _on_tab_changed(self, _key: str) -> None:
        self.rebuild()

    def _sync_visibility(self) -> None:
        """整组被依赖隐藏时 chip 同步隐藏（``isHidden`` 才是「显式藏了」）。"""
        for chip, (_title, block) in zip(self._chips, self._blocks):
            chip.setVisible(not block.isHidden())

    # ---------------------------------------------------------------- 跳转
    def jump_to(self, block: QWidget) -> None:
        """顶对齐滚到该区；目标是高级组 / 折叠框时先展开（口径同搜索跳转）。"""
        self._reveal(block)
        content = self._scroll.widget()
        y = block.mapTo(content, QPoint(0, 0)).y() - 8
        self._scroll.verticalScrollBar().setValue(max(0, y))

    def _reveal(self, block: QWidget) -> None:
        if isinstance(block, CollapsibleGroup):
            if block.is_expanded():
                return
            block.set_expanded(True)
        elif isinstance(block, SettingsSection) and block.advanced:
            if block.toggle.isChecked():
                return
            block.toggle.setChecked(True)
        else:
            return
        # 展开把下面所有块都推下去了：先把布局算一遍再取 y，否则量到的是旧位置。
        content = self._scroll.widget()
        layout = content.layout()
        if layout is not None:
            layout.activate()
        # 只 activate 布局还不够：它按内容**旧的**高度重排，量出来的 y 落在半更新的
        # 布局上（实测页尾目标少算 74px，滚过去仍差那么多）；滚动范围也要等内容真的
        # resize 才更新，否则 setValue 会被旧 maximum 截住。adjustSize() 让内容按新
        # sizeHint 真 resize，布局与滚动范围一次到位——同步、不需要定时器，
        # 也就没有「延后一拍时目标已被销毁」的悬空问题。
        content.adjustSize()

    # ---------------------------------------------------------------- 跟手
    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self._sync_visibility()
        return super().eventFilter(watched, event)


def install(dialog) -> None:
    """给每个设置域页装跳转条、给每个分区注入描述（域装配末尾调一次）。

    没有 ``settingsScroll`` 的页（如「更新」的命令面板）自然跳过：那不是设置表单，
    没有「区」可直达，也没有分区要写描述。
    """
    for index in range(dialog.pages.count()):
        page = dialog.pages.widget(index)
        scroll = page.findChild(QScrollArea, "settingsScroll")
        if scroll is None:
            continue
        apply_descriptions(scroll.widget())
        heading_host = getattr(page, "heading_host", None)
        if heading_host is None:
            continue
        _SettingsAnchorBar(heading_host, scroll)
