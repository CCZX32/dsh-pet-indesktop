# -*- coding: utf-8 -*-
"""独立灵动岛胶囊窗口。

- 常驻顶层小窗，可显示图标、名称、信息槽、状态灯；
- 支持拖拽、四边停靠半隐藏（收成细条、鼠标靠近滑出）、位置持久化；
- 单击胶囊按 ``click_action`` 展开卡片（余额/最近消息/快捷按钮）或切换桌宠显隐；
  桌宠隐藏时（``hidden_chat`` 开启）单击改为弹岛对话气泡（island_chat.py）；
- 事件动效（``event_effects``）：AI 回复/余额刷新/峰谷切换时位移弹跳 +
  表面轻压 + 短暂呼吸，静止时完全无定时器开销；dsh 工作时状态灯变蓝；
- ``bump()`` 供碰撞系统调用：被撞时表面压扁回弹（史莱姆果冻形变只作用于
  胶囊外形，文字图标保持锐利）+ 按撞击方向轻微踢动；
- 外观：黑/白/玻璃质感自绘 + 背景不透明度 + 主题色（五级）。
"""
from __future__ import annotations

import logging
import math
import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from . import catalog, island_segments, net_monitor, sys_monitor

logger = logging.getLogger(__name__)

_CAPSULE_HEIGHT = 44
_CAPSULE_INSET = 6  # 胶囊绘制内缩：给果冻形变/悬停放大/踢动留出窗口内余量
_EDGE_MARGIN = 16
_DOCK_THRESHOLD = 40
_STRIP_THICKNESS = 16
_STRIP_SIDE = 64  # 左右停靠时竖条的长度
_CARD_WIDTH = 340
_CARD_HEIGHT = 148
_CARD_AUTO_COLLAPSE_MS = 15_000
_DOCK_BACK_MS = 800
_BREATHE_AFTER_EVENT_S = 5.0

# 弹簧参数：位移踢动（kick）、受击倾斜（tilt）、果冻形变（squish）
_KICK_STIFFNESS = 210.0
_KICK_DAMPING = 17.0
_SCALE_STIFFNESS = 170.0
_SCALE_DAMPING = 15.0
_TILT_STIFFNESS = 120.0
_TILT_DAMPING = 10.0
_TILT_MAX_DEG = 3.5
_SCALE_MIN = 0.97
_SCALE_MAX = 1.03
# 史莱姆形变：只作用于胶囊外形（背景/描边/阴影），文字图标绝不参与变换——
# 形变的是"表面"，内容保持锐利（1.0=休息态，<1 压扁，弹簧回摆产生果冻抖动）
_SQUISH_STIFFNESS = 150.0
_SQUISH_DAMPING = 8.5
_SQUISH_MIN = 0.85
_SQUISH_MAX = 1.12
# 受击速度上限：单次最强撞击（bump 的 strength 封顶 3.0）注入 -3.45 / ±39，
# 就是这两个上界的来源。连撞叠加不得越过它——越过只是把弹簧顶在形变钳位
# （_SQUISH_MIN）与 ±_TILT_MAX_DEG 倾斜钳位上反复过冲：形状不再变化（像素零
# 变化），_animating() 却长期为真，半透明顶层窗每 16ms 空转整窗重绘（实测连撞
# 60 次 _squish_v 累到 -207、同向连打 _tilt_v 累到 109，均无界）。
_SQUISH_V_MAX = 3.5
_TILT_V_MAX = 40.0
# bump 动效的动画时间上限（s）：从最后一次撞击起算，到点强制收尾归零。连撞把
# 弹簧顶在钳位上时"阈值判据"可能长期为真，上限是收敛的硬保证（按动画时间累计，
# 不是墙钟——停表期间的墙钟不计入）。
_BUMP_ANIM_MAX_S = 0.9
_ANIM_TICK_MS = 16  # ~60fps，仅动画活跃时运行，静止零开销

_DOCK_EDGES = ("none", "top", "bottom", "left", "right")

# 主题色预设（设置页可换）：图标底圈 / 事件闪光 / 停靠描边共用
_ACCENT_PRESETS = {
    "blue": "#40b8ff",
    "green": "#30a46c",
    "purple": "#9b7bff",
    "pink": "#ff7ab8",
    "orange": "#ffa94d",
}
_DEFAULT_ACCENT = "blue"

# 图标模式："auto"=鱼本体头像位图（默认）；"img:<路径>"=用户自定义图片；
# 其他字符串=文字/emoji 图标（用户主动选择，愿意付 emoji 字体栈的一次性税）。
_ICON_AUTO = "auto"
_ICON_IMG_PREFIX = "img:"
_ICON_PIXMAP_PX = 22  # 头像画进 26px 底圈内的尺寸
_ICON_STRIP_PX = 16  # 左右停靠细条里的头像尺寸


def spring_step(
    value: float, velocity: float, target: float, dt: float,
    stiffness: float = _KICK_STIFFNESS, damping: float = _KICK_DAMPING,
) -> tuple[float, float]:
    """阻尼弹簧积分一步（半隐式欧拉），返回新的 (value, velocity)。

    dt 由调用方按真实帧间隔传入（钳到 50ms 防切后台后爆炸）。
    """
    dt = max(0.0, min(float(dt), 0.05))
    accel = (target - value) * stiffness - velocity * damping
    velocity += accel * dt
    value += velocity * dt
    return value, velocity


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def dock_edge_for(
    rect: QRect, available: QRect, threshold: int = _DOCK_THRESHOLD,
) -> str:
    """按窗口矩形到屏幕可用区四边的距离判定停靠边，都不近则 "none"。

    四边等权、取最近者——顶部被系统栏/MyDockFinder 占用时用户可靠左右下。
    """
    distances = {
        "top": abs(rect.top() - available.top()),
        "bottom": abs(available.bottom() - rect.bottom()),
        "left": abs(rect.left() - available.left()),
        "right": abs(available.right() - rect.right()),
    }
    edge, distance = min(distances.items(), key=lambda item: item[1])
    return edge if distance <= threshold else "none"


def strip_rect_for(rect: QRect, edge: str, available: QRect) -> QRect:
    """停靠后的细条矩形：上下停靠压扁高度，左右停靠收成短竖条。

    左右竖条按参考矩形的真实几何中心（top + height//2）纵向居中，不用
    QRect::center()——它对偶数尺寸向下取整差 1px，与滑出方向（_target_rect
    的整数居中公式）不对称，滑出/收回每循环细条累计上漂 1px。
    """
    if edge in ("top", "bottom"):
        y = available.top() if edge == "top" else available.bottom() - _STRIP_THICKNESS + 1
        return QRect(rect.left(), y, rect.width(), _STRIP_THICKNESS)
    if edge in ("left", "right"):
        x = available.left() if edge == "left" else available.right() - _STRIP_THICKNESS + 1
        length = min(_STRIP_SIDE, available.height())
        center_y = rect.top() + rect.height() // 2
        y = max(available.top(), min(center_y - length // 2,
                                     available.bottom() - length + 1))
        return QRect(x, y, _STRIP_THICKNESS, length)
    return QRect(rect)


def _cfg_dict(config) -> dict:
    value = config.get("dynamic_island", {})
    return value if isinstance(value, dict) else {}


def _native_reassert_topmost(window) -> bool:
    """Windows：把窗口原生重插到 topmost 带最上（不激活/不移动/不改大小）。

    非 Windows 一律返回 ``False``，调用方回退 Qt ``raise_()``——macOS 的
    NSWindow level 与 Windows 的 topmost 带不是一回事，"重申后是否真的最上"
    在 macOS 上**未验证**（Linux 同理）。
    """
    if sys.platform != "win32":
        return False
    try:
        from .platform_win import _set_windows_topmost

        return bool(_set_windows_topmost(int(window.winId()), True))
    except Exception:
        logger.debug("灵动岛原生置顶重申失败", exc_info=True)
        return False


# ---------------------------------------------------------------- 段管线（P1 D1）
# 胶囊内容行 = 头像 + 角色名 + 主信息段 + 指标段… + 状态点（见设计稿 §1.1）。
# 下面的常量与两个纯函数是"行内几何"的全部来源：``_capsule_width`` 用它们算自然
# 宽，paintEvent 用它们落位——**同一份几何只有一个来源**，绘制层不做度量。
#: 字号阶梯（逻辑 px；``setPixelSize`` 不用 pt——pt 要过一次 DPI 换算的二次取整）。
#: L1 主信息 / L2 指标数值 / L3 角色名 / L4 段标签·单位。
_FONT_LAYERS = {
    "primary": (14, QFont.Weight.DemiBold),
    "value": (13, QFont.Weight.Medium),
    "name": (12, QFont.Weight.Normal),
    "label": (10, QFont.Weight.Normal),
}
#: 统一基线：所有字号层级共用一条（胶囊垂直中心线下方 5px，见设计稿 §2.1）。
#: 逐字号各自垂直居中会在单位跨档（10↔13px 混排）时上下跳。
_BASELINE_DY = 5.0
#: 段间竖线：槽位 19px = 9 + 1 + 9，竖线 1×14 垂直居中。
_SEG_SLOT_PX = 19.0
_DIVIDER_W_PX = 1.0
_DIVIDER_H_PX = 14.0
#: 内容行内边距左右各 19px（= 6 内缩 + 13 内容边距，沿用既有视觉）。
_CONTENT_PAD_PX = 19.0
_ICON_PX = 26.0
_ICON_GAP_PX = 8.0
#: 角色名上限 96px（超出右省略）：名字是身份不是数据，不该吃掉指标空间。
_NAME_MAX_PX = 96
_NAME_GAP_PX = 10.0
_STATUS_DOT_PX = 8.0
_STATUS_GAP_PX = 10.0
#: 自然宽下限（沿用既有 120px：极小内容下岛仍是可点可拖的胶囊）。
_MIN_CAPSULE_W = 120

#: 主信息段的测宽样本（按模式取最坏形态）。time 定宽是"时间不推邻居"的前提；
#: balance 的样本取 ``balance.format_balance`` 的真实单行形态（带 ¥ 与 5 位整数），
#: 比它更长的串（带充值/赠送明细）按现文案加宽而不静默吃字（见 place_info_segments）。
_PRIMARY_SAMPLES = {
    "time": "88:88",
    "balance": "余额 ¥88888.88",
    "balance_tier": "低谷 → 88:88",
}
#: 网络段盒宽样本：用真格式化器的**最坏档位**生成（速率 5 列上限 + 4 位毫秒），
#: 手写样本会和 ``format_network_slot`` 的定宽契约漂移。
_NETWORK_BOX_SAMPLE = net_monitor.format_network_slot(
    1023 * 1024 ** 3, 1023 * 1024 ** 3, 1000.0)
#: 设备槽段的标签（数值样本取 ``sys_monitor.MAX_TEXT``，与格式化器同源）。
_DEVICE_LABELS = {island_segments.CPU: "CPU", island_segments.MEM: "内存"}
#: 设备槽段 id（订阅 key 同 id；cpu/mem 共用一条采样线程）。
_SYS_METRIC_IDS = (island_segments.CPU, island_segments.MEM)


@dataclass(frozen=True)
class _InfoSeg:
    """一个待渲染段（主信息段或指标段）——**数据不是绘制串**。

    ``text`` 是"四态兜底之后"的显示文案（非 ``ok`` 一律同宽 ``--``）；``box_text``
    是测宽样本（指标段 = 声明的最坏形态，主信息段 = 模式样本）。段列表是数据，
    D2 的收缩流水线只需过滤列表（折尾段 / 省名字），不必改绘制。
    """

    kind: str        # "primary" / "metric"
    seg_id: str      # "primary" / "network" / "cpu" / "mem" / 配置里的未知 id
    label: str       # 段标签（L4 10px 层；主信息段为空）
    text: str        # 当前显示文案（运行期值）
    box_text: str    # 测宽样本（指标段 = max_text；主信息段 = 模式最坏形态）
    state: str       # island_segments 的状态词表


@dataclass(frozen=True)
class _SegPlacement:
    """一段在内容行里的落位（纯几何：绘制层只做装配，不做度量）。"""

    seg: _InfoSeg
    text: str            # 盒内实际绘制的文案（超宽时已右省略到盒宽）
    text_w: int          # 上述文案的实测宽（盒内右对齐用）
    label_x: float
    label_w: int
    box_x: float
    box_w: int
    divider_x: float | None   # 段前竖线的 x；首段为 None（竖线只出现在"段 ∧ 段"）

    @property
    def right(self) -> float:
        return self.box_x + self.box_w


def _box_sample(seg: _InfoSeg, value_fm) -> str:
    """段盒的测宽样本：指标段恒为声明样本，主信息段取样本与现文案的较宽者。

    指标段盒宽**与当前读数无关**，这就是"数字跳动不推邻居"的全部机制；主信息段
    允许被现文案撑宽——``HH:mm`` 这类等宽形态由样本兜住（值变化不改宽），而余额
    明细那种超长串宁可让岛变宽也不静默吃字（右省略由 D2 的 S3 负责 custom）。
    """
    if seg.kind != "primary":
        return seg.box_text
    if int(value_fm.horizontalAdvance(seg.text)) <= int(value_fm.horizontalAdvance(seg.box_text)):
        return seg.box_text
    return seg.text


def place_info_segments(segments, *, start_x, primary_fm, value_fm, label_fm):
    """把段序列摆成一行（纯函数）：段间 19px 槽位、竖线居中、盒内右对齐。

    为什么不用 ``island_segments.measure_segment_width``：那个函数只收**一个**
    度量对象（Slice A 的契约假设"标签与数值同字体"），而排版是两档字号——标签
    10px、数值 13px、主信息 14px。用 10px 度量数值会把盒子量小（13px 的字塞不
    进去，每帧吃一次右省略 warning），用 13px 度量标签又让段宽虚胖。所以标签宽走
    ``label_fm`` + :data:`island_segments.LABEL_GAP_PX`，数值盒宽走
    :func:`island_segments.format_field_box`（同一套 ``max_text`` 语义，且自带
    "超宽右省略 + warning"的硬护栏）。

    ``start_x`` 是内容行里第一个段的起点（头像/角色名之后），返回值里的 x 全是
    绝对坐标——绘制层只按它落笔。
    """
    placements: list[_SegPlacement] = []
    x = float(start_x)
    for index, seg in enumerate(segments):
        metrics = primary_fm if seg.kind == "primary" else value_fm
        display, box_w = island_segments.format_field_box(
            seg.text, _box_sample(seg, metrics), metrics)
        label_w = int(label_fm.horizontalAdvance(seg.label)) if seg.label else 0
        gap = island_segments.LABEL_GAP_PX if seg.label else 0
        divider_x = None
        if index > 0:
            divider_x = x + (_SEG_SLOT_PX - _DIVIDER_W_PX) / 2.0
            x += _SEG_SLOT_PX
        box_x = x + label_w + gap
        placements.append(_SegPlacement(
            seg=seg, text=display, text_w=int(metrics.horizontalAdvance(display)),
            label_x=x, label_w=label_w, box_x=box_x, box_w=box_w,
            divider_x=divider_x,
        ))
        x = box_x + box_w
    return placements


class DynamicIsland(QWidget):
    """胶囊形态的独立灵动岛窗口。"""

    clicked = Signal()  # click_action == "toggle_pet" 时的单击（旧行为）
    toggle_pet_requested = Signal()
    open_chat_requested = Signal()
    open_settings_requested = Signal()
    card_expanded = Signal()  # 卡片展开（AppShell 借此静默刷新余额）
    chat_requested = Signal()  # 桌宠隐藏时单击胶囊（hidden_chat 开启）：弹岛对话气泡

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._cfg = _cfg_dict(config)
        self.setObjectName("dynamic-island")
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._press_global: QPoint | None = None
        self._balance_tier_text = "余额峰谷 --"
        self._balance_text = "余额 --"
        self._pet_visible = True
        # 本构建是否具备聊天能力（AppShell 按 enable_chat 喂入，默认 True
        # 维持现状；纯桌宠版置 False 时 hidden_chat 单击路由回退展开卡片）
        self._chat_available = True
        self._agent_active = False
        self._last_message = ""
        # 几何变化回调（果冻墙碰撞体挂这里跟踪拖拽/停靠滑动）：AppShell 注入。
        self.on_geometry_changed = None
        # 桌宠聚合可见性回调（碰撞体据此挂起/恢复）：AppShell 注入。
        self.on_pet_visibility_changed = None

        # ---- 模式与动效状态（静止时全部为稳态，_anim_timer 不运行）----
        self._mode = "normal"  # normal / docked / expanded
        self._hover_peek = False  # 停靠状态下鼠标靠近的临时滑出
        # 位移弹跳（px）：事件下压回弹 / 受击定向踢动，绘制时整数化保持文字锐利
        self._kick_x = 0.0
        self._kick_y = 0.0
        self._kick_vx = 0.0
        self._kick_vy = 0.0
        self._tilt = 0.0
        self._tilt_v = 0.0
        # 果冻形变（史莱姆表面浮动）：只调制胶囊外形，不碰文字
        self._squish = 1.0
        self._squish_v = 0.0
        self._scale = 1.0  # 只做 ±3% 微缩放辅助（大缩放会糊文字，已弃用）
        self._scale_v = 0.0
        self._breathe_until = 0.0
        self._hover_scale_target = 1.0
        # bump 动效剩余动画时间（s）：每次撞击重置（见 _BUMP_ANIM_MAX_S）
        self._bump_anim_left = 0.0
        # 图标位图状态（icon="auto"/"img:<路径>" 时用；emoji 模式不碰）
        self._icon_provider = None  # 头像取图回调，AppShell 注入
        self._icon_pixmap_cache: QPixmap | None = None
        self._icon_img_failed = False  # img: 加载失败也记住，免每帧重试磁盘 IO
        self._icon_pixmap_token = 0  # 头像换代计数：内容层缓存按它判失效
        # 内容层位图缓存（paintEvent 的文字绘制是实测大头，见 _content_cache）
        self._content_pixmap: QPixmap | None = None
        self._content_cache_key: tuple | None = None
        # 段管线的字体/宽度缓存：字号层懒建（_FONT_LAYERS），度量对象按层缓存；
        # 自然宽按白名单键缓存（见 _capsule_width / _width_key）——采样值变化
        # 进不了这个键，所以"数字跳动不推邻居"是结构保证而不是纪律。
        self._fonts: dict[str, QFont] = {}
        self._font_metrics: dict[str, QFontMetrics] = {}
        self._width_cache_key: tuple | None = None
        self._width_cache = 0
        self._geo_from: QRect | None = None
        self._geo_to: QRect | None = None
        self._geo_t = 0.0

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(_ANIM_TICK_MS)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_last = 0.0

        self._dock_back_timer = QTimer(self)
        self._dock_back_timer.setSingleShot(True)
        self._dock_back_timer.setInterval(_DOCK_BACK_MS)
        self._dock_back_timer.timeout.connect(self._dock_back)

        self._card_collapse_timer = QTimer(self)
        self._card_collapse_timer.setSingleShot(True)
        self._card_collapse_timer.setInterval(_CARD_AUTO_COLLAPSE_MS)
        self._card_collapse_timer.timeout.connect(self.collapse_card)

        self._build_card()

        self._info_timer = QTimer(self)
        self._info_timer.setInterval(30_000)
        self._info_timer.timeout.connect(self._refresh)
        self._info_timer.start()

        # 网络段（``island_metrics`` 的 network 成员，默认关）：采样在后台线程里跑
        # （psutil 计数器单次调用实测 23ms，不能进 16ms 的动画帧预算），
        # 这里只按探测间隔读一次快照、文本变了才重绘。
        self._net_monitor: net_monitor.NetMonitor | None = None
        self._net_sample: net_monitor.NetSample | None = None
        self._net_timer = QTimer(self)
        self._net_timer.setSingleShot(False)
        self._net_timer.timeout.connect(self._tick_network)

        # 设备槽段（``island_metrics`` 的 cpu/mem 成员，默认关）：与网络段同一套
        # 生命周期纪律（岛可见才采样、段撤掉即收口），但采样器是**共享**的
        # （``SysMonitor`` 一条线程喂两个段），订阅按段 id 计：0 订阅零 syscall。
        self._sys_monitor: sys_monitor.SysMonitor | None = None
        self._sys_sample: sys_monitor.SysSample | None = None
        self._sys_timer = QTimer(self)
        self._sys_timer.setSingleShot(False)
        self._sys_timer.timeout.connect(self._tick_sys)

        # 余额峰谷档位切换的准点刷新：单次定时到下一切换边界，刷新后再排下一次。
        self._tier_tick_timer = QTimer(self)
        self._tier_tick_timer.setSingleShot(True)
        self._tier_tick_timer.timeout.connect(self._on_balance_tier_tick)
        self._schedule_next_balance_tier_refresh()

        # 置顶保活接线（见 reassert_topmost）：本进程窗口被激活 = 某个 topmost
        # 窗（聊天窗/设置窗/岛气泡/托盘菜单 popup）刚插到岛上面，这是零轮询里
        # 最精确的时机信号；Qt < 6.5 无 focusWindowChanged 时由
        # applicationStateChanged(Active) 覆盖"本进程回到前台"那一半。
        app = QApplication.instance()
        if app is not None:
            focus_changed = getattr(app, "focusWindowChanged", None)
            if focus_changed is not None:
                focus_changed.connect(self._on_own_window_focused)
            app.applicationStateChanged.connect(self._on_application_state_changed)

        self._apply_position()
        self._sync_network_slot()
        self._sync_sys_slot()

    # ------------------------------------------------------------ 模式/配置
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def dock_edge(self) -> str:
        # 「靠边半隐藏」总开关关着时，存储的停靠边视为无——停靠判定/细条
        # 绘制/碰撞跳过等所有读取处统一走"不停靠"，不留死状态（开关再开
        # 时存储的边恢复生效）
        if not self._edge_dock_enabled():
            return "none"
        return str(self._cfg.get("dock_edge") or "none")

    def _click_action(self) -> str:
        return str(self._cfg.get("click_action") or "expand")

    def _hidden_chat_enabled(self) -> bool:
        """桌宠隐藏时的对话气泡开关（点击岛弹气泡 + 回复到达自动预览）。"""
        return bool(self._cfg.get("hidden_chat", True))

    def _event_effects_enabled(self) -> bool:
        return bool(self._cfg.get("event_effects", True))

    def _net_enabled(self) -> bool:
        """网络段开关：``island_metrics`` 里有没有 network（默认关）。

        网络是**普通指标段**（P1 Slice D1 起）：它和信息槽内容各占各的位置，
        信息槽永远由 ``info_mode`` 决定，不再有"网络接管信息槽"的特殊形态。

        真值只有一个来源：列表的成员关系（P1 Slice C 起）。旧键
        ``island_network_enabled`` 只在归一化阶段单向迁移进列表，这里不再读它；
        非列表值（手改配置 / 桩对象）一律按"没开"处理，不做子串匹配。
        """
        return island_segments.NETWORK in self._metric_ids()

    def _net_interval(self) -> float:
        return net_monitor.clamp_interval(
            self.config.get("network_probe_interval_seconds", net_monitor.DEFAULT_INTERVAL_SECONDS))

    def _net_active(self) -> bool:
        """网络槽的**有效**开关：网络段在列表里 AND 信息槽可见（岛可见性另算）。

        信息槽被关掉时一条信息段都画不出来（``_visible_parts`` 的第 3 位），
        继续跑采样线程只是白烧 psutil 的 23ms/秒与探测包——所以"显示信息槽"是
        三态里的一态，不是只看网络段在不在列表里。
        """
        if not self._net_enabled():
            return False
        _icon, _name, info, _status = self._visible_parts()
        return bool(info)

    def _edge_dock_enabled(self) -> bool:
        return bool(self._cfg.get("edge_dock", True))

    def _opacity(self) -> float:
        """背景不透明度倍率（0.4~1.0），设置页可调；非法值回退 1.0。"""
        try:
            value = float(self._cfg.get("opacity", 1.0))
        except (TypeError, ValueError):
            return 1.0
        return max(0.4, min(1.0, value))

    def _accent_color(self) -> QColor:
        key = str(self._cfg.get("accent") or _DEFAULT_ACCENT)
        return QColor(_ACCENT_PRESETS.get(key, _ACCENT_PRESETS[_DEFAULT_ACCENT]))

    # ------------------------------------------------------------ 对外
    def reassert_topmost(self) -> bool:
        """把岛重新插到 topmost 带最上（置顶保活入口）。

        为什么需要：岛带 ``WindowStaysOnTopHint``（Windows = ``WS_EX_TOPMOST``）
        但 ``WindowDoesNotAcceptFocus``（= ``WS_EX_NOACTIVATE``）**从不被激活**，
        而 Windows 的 topmost 带内先后由"谁最近被激活/显示"决定——任何被激活的
        topmost 窗（本进程聊天窗/设置窗/岛对话气泡，或第三方置顶工具）都会盖在
        岛上面；Windows 又不提供"你被盖住了"的通知，岛不主动重申就永远回不来
        （Qt 也只在 flags 变化时写一次 ``WS_EX_TOPMOST``，``show()`` 对已可见的
        窗口是 no-op，所以"设置里保存一次"并不会把它顶回去）。

        触发点全部事件驱动或复用既有通道，不新增定时器/线程：
        ``showEvent``、本进程窗口被激活（前台/焦点信号）、单击岛、
        既有信息刷新心跳（``_refresh``：30s 心跳 + 余额/配置刷新各一次）。
        隐藏态直接返回 False——可见与否由用户决定，隐藏即静默。
        """
        if not self.isVisible():
            return False
        if _native_reassert_topmost(self):
            return True
        # 非 Windows（macOS / Linux **未验证**）：Qt 层 raise_() 兜底
        self.raise_()
        return True

    def _on_own_window_focused(self, window) -> None:
        """本进程有窗口被激活 → 把岛顶回去（``focusWindowChanged``）。

        只接本进程侧的信号：``focusWindowChanged`` 只报告本进程的窗口，
        焦点落到别的应用时它带 ``None``（Qt 语义：焦点移出本应用）——那种情况
        属于"外部应用抢到前台"，不重申（见 ``_on_application_state_changed``）。
        """
        if window is None:
            return
        self.reassert_topmost()

    def _on_application_state_changed(self, state) -> None:
        """本进程成为前台（Active）才重申；失去前台不动作。

        外部应用抢到前台（开始菜单、全屏游戏、第三方置顶工具）时重申会让岛
        反过来盖住系统级置顶面，与 legacy「全屏应用会暂时盖住桌宠」同口径。
        """
        if state == Qt.ApplicationState.ApplicationActive:
            self.reassert_topmost()

    def set_icon_provider(self, fn) -> None:
        """注入"鱼本体头像"取图回调（AppShell 提供：取首个桌宠窗的当前帧图标）。

        回调返回 QPixmap 或 None（帧尚未就绪，岛侧下次重建内容层时重试）。
        注入即作废已缓存头像/内容层：换形象后要立刻取到新头像。
        """
        self._icon_provider = fn if callable(fn) else None
        self._clear_icon_cache()
        self.update()

    def set_balance_info(self, tier_text: str, balance_text: str) -> None:
        self._balance_tier_text = str(tier_text or "余额峰谷 --")
        self._balance_text = str(balance_text or "余额 --")
        self._sync_card_labels()
        self._refresh()

    def set_pet_visible(self, visible: bool) -> None:
        self._pet_visible = bool(visible)
        callback = self.on_pet_visibility_changed
        if callable(callback):
            try:
                callback(bool(visible))
            except Exception:
                pass
        self._sync_card_labels()
        self.update()

    def set_chat_available(self, available: bool) -> None:
        """写入本构建是否具备聊天能力（AppShell 按 enable_chat 喂入）。

        纯桌宠版（无 pet.chat 的打包变体）置 False：hidden_chat 开且桌宠
        隐藏时，单击路由回退为展开卡片——卡片的「显示桌宠」是该形态下
        唯一的恢复入口；否则单击被路由到不存在的对话气泡，岛无任何
        反应，桌宠永远回不来（纯桌宠版实机死锁）。
        """
        self._chat_available = bool(available)

    def set_agent_active(self, active: bool) -> None:
        """dsh/agent 工作状态：点亮蓝色状态灯；上升沿弹一下提示开工。"""
        active = bool(active)
        rising = active and not self._agent_active
        self._agent_active = active
        if rising:
            self._bounce(impulse=3.0)
        self.update()

    def set_last_message(self, text: str) -> None:
        """记录最近一条 AI 消息（展开卡片里显示摘要）。"""
        self._last_message = str(text or "").strip()
        self._sync_card_labels()

    def notify_event(self, kind: str = "generic") -> None:
        """事件动效入口：reply / balance / tier / generic。尊重 event_effects 开关。"""
        if not self._event_effects_enabled():
            return
        impulse = {"reply": 5.0, "balance": 3.5, "tier": 4.0}.get(kind, 3.0)
        self._bounce(impulse=impulse)
        if kind == "reply":
            self._breathe_until = time.monotonic() + _BREATHE_AFTER_EVENT_S
            self._ensure_anim_timer()

    def bump(self, strength: float = 1.0, dir_x: float = 0.0, dir_y: float = 0.0) -> None:
        """被桌宠撞到（果冻墙→水波感）：撞击点荡开涟漪 + 轻微定向踢动。

        dir_x/dir_y 为岛被顶着的方向（单位向量，由碰撞侧从对方 dv 取反得到）；
        位移与形变只作用于绘制层，窗口几何不动（岛的位置永远由用户拖拽决定）。
        """
        if not self._event_effects_enabled():
            return
        strength = max(0.2, min(float(strength), 3.0))
        # 史莱姆受击：表面压扁（弹簧回摆出果冻抖动）+ 轻微定向踢动/倾斜。
        # 踢动速度钳制：窗口只有 44px 高，多鱼同撞叠加时位移超窗会被裁掉
        squish_v = self._squish_v - 1.15 * strength
        self._squish_v = max(-_SQUISH_V_MAX, min(_SQUISH_V_MAX, squish_v))
        self._kick_vx = max(-150.0, min(150.0, self._kick_vx + float(dir_x) * 110.0 * strength))
        self._kick_vy = max(-150.0, min(150.0, self._kick_vy + float(dir_y) * 110.0 * strength))
        tilt_v = self._tilt_v + 13.0 * strength * (1 if dir_x >= 0 else -1)
        self._tilt_v = max(-_TILT_V_MAX, min(_TILT_V_MAX, tilt_v))
        # 单次撞击动效的动画时间上限从这一击重新起算（连撞 = 每击各有一段动画，
        # 但最后一击之后最多再跑 _BUMP_ANIM_MAX_S）
        self._bump_anim_left = _BUMP_ANIM_MAX_S
        self._ensure_anim_timer()

    def refresh_from_config(self) -> None:
        old_edge = self.dock_edge
        old_icon = self._icon_spec()
        self._cfg = _cfg_dict(self.config)
        self._schedule_next_balance_tier_refresh()
        self._sync_card_labels()
        self._sync_network_slot()
        self._sync_sys_slot()
        # 头像必须跟着刷新作废：provider 取的是**当前形象**的帧，而角色热切换
        # 只调 refresh_from_config（不动 island 配置），不换缓存就一直挂旧头像
        if self._icon_image_mode() or self._icon_spec() != old_icon:
            self._clear_icon_cache()
        if self.dock_edge != old_edge:
            self._apply_position()
        # 「靠边半隐藏」被关闭时已停靠的岛要复位回正常形态——否则一直是
        # 16px 细条贴边（碰撞结算也随停靠跳过而长期失效）
        if not self._edge_dock_enabled() and self._mode == "docked":
            self._mode = "normal"
            self._hover_peek = False
            self._apply_fixed_size()
            self._apply_position()
        self._refresh()

    # ------------------------------------------------------------ 余额峰谷
    def _balance_tier_display_text(self) -> str:
        """按系统时间直接生成余额峰谷文案：当前档位标签 + 下一档切换时间。

        不依赖余额查询；档位标签使用设置里的高峰/空闲（或梁文峰/梁文谷/自定义）。
        """
        from . import balance as balance_mod

        now = balance_mod.beijing_now()
        peak_label, idle_label = balance_mod.resolve_tier_labels(
            str(self.config.get("balance_tier_labels_mode", "default") or "default"),
            str(self.config.get("balance_tier_label_peak", "") or ""),
            str(self.config.get("balance_tier_label_idle", "") or ""),
        )
        # 保持无参调用以兼容现有测试/调用面（函数内部使用同一北京时间）。
        tier = balance_mod.deepseek_pricing_tier()
        label = peak_label if tier == "peak" else idle_label
        try:
            _next_tier, next_time = balance_mod.next_pricing_switch(now)
            time_text = balance_mod.format_switch_time(now, next_time)
            return f"{label} → {time_text}"
        except Exception:
            return label

    def _on_balance_tier_tick(self) -> None:
        """到达预设档位切换点：刷新显示、播事件动效，并排下一次准点刷新。"""
        self._refresh()
        self.notify_event("tier")
        self._schedule_next_balance_tier_refresh()

    def _schedule_next_balance_tier_refresh(self) -> None:
        """在下一个峰谷切换边界安排一次单发刷新（只在余额峰谷模式启用）。"""
        if str(self._cfg.get("info_mode") or "time") != "balance_tier":
            self._tier_tick_timer.stop()
            return
        try:
            from . import balance as balance_mod

            _next_tier, next_time = balance_mod.next_pricing_switch()
            now = balance_mod.beijing_now()
            delay_ms = max(250, int((next_time - now).total_seconds() * 1000) + 250)
            self._tier_tick_timer.start(delay_ms)
        except Exception:
            self._tier_tick_timer.stop()

    def _refresh(self) -> None:
        """内容变化后立即重算尺寸、夹回屏幕并重绘。"""
        # 复用既有刷新通道重申置顶（30s 信息心跳 + 余额/配置刷新各一次）：系统
        # 事件（explorer 重启/DPI 变更/休眠唤醒，QTBUG-30359）或别的 topmost 窗
        # 抢走带顶后，最迟一个周期内自行回到最上——不为此新增定时器
        self.reassert_topmost()
        if self._mode == "docked" and not self._hover_peek:
            self.update()
            return
        self._update_size()
        self._clamp_to_screen()
        self.update()

    # ------------------------------------------------------------ 网络槽
    def _make_net_monitor(self, interval: float) -> net_monitor.NetMonitor:
        """建采样器（**测试替换点**：替身不碰 psutil、不发探测包）。"""
        return net_monitor.NetMonitor(interval=interval)

    def _sync_network_slot(self) -> None:
        """按配置启停网络槽的采样线程与读取定时器（幂等）。

        有效开关 = 岛可见 AND 显示信息槽 AND 网络槽开着（见 ``_net_active``）；
        任一不满足即停采样——关闭 → 彻底收口（线程停、socket 关、快照丢弃，信息槽
        回到 ``info_mode``），只是暂时不可见 → 保留对象不采样（同 hideEvent 的
        "隐藏即休眠"口径）。采样间隔变化（设置页改
        ``network_probe_interval_seconds``）即时生效，不重建线程。
        """
        if not self._net_active():
            self._pause_network_slot()
            if self._net_monitor is not None:
                self._net_monitor.close()
                self._net_monitor = None
            self._net_sample = None
            return
        interval = self._net_interval()
        if self._net_monitor is None:
            self._net_monitor = self._make_net_monitor(interval)
        else:
            self._net_monitor.set_interval(interval)
        self._net_timer.setInterval(max(200, int(round(interval * 1000))))
        if self.isVisible():
            self._net_monitor.start()
            self._net_timer.start()
        else:
            self._pause_network_slot()

    def _pause_network_slot(self) -> None:
        """停表停线程但保留对象（隐藏/不可见时用；socket 由线程自己收口）。"""
        self._net_timer.stop()
        if self._net_monitor is not None:
            self._net_monitor.stop()

    def _tick_network(self) -> None:
        """读一次采样快照；值没变就什么都不做（静止时零重绘）。

        **刻意不调 ``_update_size``**：网络段盒宽由声明样本定死（见
        ``_NETWORK_BOX_SAMPLE``），读数在盒内右对齐伸缩，几何重算走宽度白名单
        （``_width_key``）——采样值不归它管。也不走 ``_refresh``：那会每秒重申
        一次置顶（原生 SetWindowPos），没必要，30s 心跳已覆盖置顶保活。
        """
        monitor = self._net_monitor
        if monitor is None:
            return
        sample = monitor.snapshot()
        if sample is None or sample == self._net_sample:
            return
        self._net_sample = sample
        self.update()

    # ------------------------------------------------------------ 设备槽（CPU/内存）
    def _make_sys_monitor(self, interval: float) -> sys_monitor.SysMonitor:
        """建共享采样器（**测试替换点**：替身不碰 psutil）。"""
        return sys_monitor.SysMonitor(interval=interval)

    def _sys_metric_ids(self) -> tuple[str, ...]:
        """``island_metrics`` 里的设备槽成员（cpu/mem；保序，去重）。"""
        return tuple(metric_id for metric_id in self._metric_ids()
                     if metric_id in _SYS_METRIC_IDS)

    def _sys_active(self) -> bool:
        """设备槽的**有效**开关：段在列表里 AND 信息槽可见（可见性另算）。"""
        return bool(self._sys_metric_ids()) and bool(self._visible_parts()[2])

    def _sync_sys_slot(self) -> None:
        """按配置启停设备槽的订阅、采样线程与读取定时器（幂等）。

        订阅**按段**计：段在列表里就 subscribe、不在就 unsubscribe——0 订阅时
        底座只空转计时、不产生任何 syscall（关掉指标段就该真的零开销）。
        段全撤 / 信息槽关闭 → 彻底收口（线程停、快照丢弃）；只是暂时不可见 →
        保留对象与订阅、停线程（同 hideEvent 的"隐藏即休眠"口径）。采样间隔固定
        1Hz（不可配，见 ``sys_monitor.clamp_interval``），不重建线程。
        """
        if not self._sys_active():
            self._unsubscribe_sys()
            self._pause_sys_slot()
            if self._sys_monitor is not None:
                self._sys_monitor.close()
                self._sys_monitor = None
            self._sys_sample = None
            return
        monitor = self._sys_monitor
        if monitor is None:
            monitor = self._make_sys_monitor(sys_monitor.DEFAULT_INTERVAL_SECONDS)
            self._sys_monitor = monitor
        enabled = self._sys_metric_ids()
        for metric_id in _SYS_METRIC_IDS:
            if metric_id in enabled:
                monitor.subscribe(metric_id)
            else:
                monitor.unsubscribe(metric_id)
        self._sys_timer.setInterval(max(200, int(round(monitor.interval * 1000))))
        if self.isVisible():
            monitor.start()
            self._sys_timer.start()
        else:
            self._pause_sys_slot()

    def _unsubscribe_sys(self) -> None:
        """退掉全部设备槽订阅（收口前的最后一步：订阅计数不许留在底座上）。"""
        monitor = self._sys_monitor
        if monitor is None:
            return
        for metric_id in _SYS_METRIC_IDS:
            monitor.unsubscribe(metric_id)

    def _pause_sys_slot(self) -> None:
        """停表停线程但保留对象与订阅（隐藏/不可见时用）。"""
        self._sys_timer.stop()
        if self._sys_monitor is not None:
            self._sys_monitor.stop()

    def _tick_sys(self) -> None:
        """读一次设备槽快照；值没变就什么都不做。

        同 ``_tick_network``：**绝不调 ``_update_size``**（``CPU 9%→100%`` 只在
        盒内左扩，不推邻居）；内容层位图按 ``_content_cache`` 的 key 自行重建。
        """
        monitor = self._sys_monitor
        if monitor is None:
            return
        sample = monitor.snapshot()
        if sample is None or sample == self._sys_sample:
            return
        self._sys_sample = sample
        self.update()

    # ------------------------------------------------------------ 卡片
    def _build_card(self) -> None:
        """展开卡片：余额/峰谷两行 + 最近消息 + 三个快捷按钮。默认隐藏。"""
        self._card_box = QWidget(self)
        self._card_box.setObjectName("dynamic-island-card")
        # 卡片底板由窗口 paintEvent 统一绘制（圆角连续），控件容器自身透明
        self._card_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._card_box.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self._card_box)
        layout.setContentsMargins(16, 6, 16, 12)
        layout.setSpacing(4)
        self._card_balance_label = QLabel(self._card_box)
        self._card_tier_label = QLabel(self._card_box)
        self._card_message_label = QLabel(self._card_box)
        self._card_message_label.setWordWrap(True)
        self._card_message_label.setMaximumHeight(34)
        for label in (self._card_balance_label, self._card_tier_label,
                      self._card_message_label):
            layout.addWidget(label)
        layout.addSpacing(2)
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._card_toggle_btn = QPushButton("显隐桌宠", self._card_box)
        self._card_chat_btn = QPushButton("聊天", self._card_box)
        self._card_settings_btn = QPushButton("设置", self._card_box)
        self._card_toggle_btn.clicked.connect(self._on_card_toggle)
        self._card_chat_btn.clicked.connect(self._on_card_chat)
        self._card_settings_btn.clicked.connect(self._on_card_settings)
        for btn in (self._card_toggle_btn, self._card_chat_btn,
                    self._card_settings_btn):
            button_row.addWidget(btn)
        layout.addLayout(button_row)
        self._card_box.hide()
        self._sync_card_labels()

    def _sync_card_labels(self) -> None:
        if not hasattr(self, "_card_box"):
            return
        _bg, primary, secondary = self._style_palette()
        primary_hex = primary.name() if isinstance(primary, QColor) else "#e5eaf5"
        secondary_hex = secondary.name() if isinstance(secondary, QColor) else "#a0aabe"
        accent_hex = self._accent_color().name()
        self._card_balance_label.setStyleSheet(
            f"color: {primary_hex}; font-weight: bold; font-size: 14px;")
        self._card_tier_label.setStyleSheet(f"color: {secondary_hex}; font-size: 11px;")
        self._card_message_label.setStyleSheet(f"color: {secondary_hex}; font-size: 11px;")
        # 按钮：圆角 8px、描边跟随主题色、悬停加亮；不用系统默认灰按钮
        button_style = (
            f"QPushButton {{ color: {primary_hex}; background: transparent;"
            f" border: 1px solid {accent_hex}; border-radius: 8px;"
            f" padding: 4px 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {accent_hex}; color: #ffffff; }}"
            f"QPushButton:pressed {{ background: {secondary_hex}; }}"
        )
        for btn in (self._card_toggle_btn, self._card_chat_btn,
                    self._card_settings_btn):
            btn.setStyleSheet(button_style)
        self._card_balance_label.setText(self._balance_text)
        self._card_tier_label.setText(self._balance_tier_text)
        message = self._last_message or "（暂无最近消息）"
        # 摘要最多两行，超出省略（标签限高 34px 配合 wordWrap）
        metrics = self._card_message_label.fontMetrics()
        elided = metrics.elidedText(
            message, Qt.TextElideMode.ElideRight, max(40, (_CARD_WIDTH - 32) * 2))
        self._card_message_label.setText(elided)
        self._card_toggle_btn.setText("隐藏桌宠" if self._pet_visible else "显示桌宠")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_card_box"):
            self._card_box.setGeometry(
                0, _CAPSULE_HEIGHT, self.width(),
                max(0, self.height() - _CAPSULE_HEIGHT))

    def _on_card_toggle(self) -> None:
        self.toggle_pet_requested.emit()
        self.collapse_card()

    def _on_card_chat(self) -> None:
        self.open_chat_requested.emit()
        self.collapse_card()

    def _on_card_settings(self) -> None:
        self.open_settings_requested.emit()
        self.collapse_card()

    def expand_card(self) -> None:
        """展开卡片（单击胶囊的默认行为）。停靠状态先滑出再展开。"""
        if self._mode == "expanded":
            self.collapse_card()
            return
        self._dock_back_timer.stop()
        self._mode = "expanded"
        self._hover_peek = False
        # 单击展开时鼠标多半已在岛内（enterEvent 已把悬停放大目标置 1.02），
        # 展开态禁用整窗缩放，目标拉回 1.0（见 paintEvent 截边说明）
        self._hover_scale_target = 1.0
        self._card_box.show()
        self._sync_card_labels()
        self._animate_to(self._target_rect())
        self._card_collapse_timer.start()
        self.card_expanded.emit()

    def collapse_card(self, *, animate: bool = True) -> None:
        """收起卡片；配置为停靠边时收回细条。拖拽起手时 animate=False
        （动画会与拖拽抢几何，直接把窗拽回停靠位）。"""
        if self._mode != "expanded":
            return
        self._card_collapse_timer.stop()
        self._card_box.hide()
        self._mode = "docked" if self.dock_edge != "none" else "normal"
        self._hover_peek = False
        if animate:
            self._animate_to(self._target_rect())
        else:
            self._geo_from = None
            self._geo_to = None
            self._set_free_geometry(self._target_rect())
            self._apply_fixed_size()

    # ------------------------------------------------------------ 动效核心
    def _bounce(self, impulse: float = 4.0) -> None:
        """事件弹跳：下压几像素再弹簧回位（整数位移，文字不糊）+ 表面轻压。"""
        self._kick_y = 1.5 + min(float(impulse), 5.0)
        self._kick_vy = 0.0
        self._squish_v -= impulse * 0.14
        self._scale_v += impulse * 0.06
        self._ensure_anim_timer()

    def _ensure_anim_timer(self) -> None:
        # 隐藏即休眠：隐藏态不被后台事件（AI 回复/余额刷新）拉起 60fps
        # 动画定时器空转；showEvent 恢复时会重刷新并重启动效
        if not self.isVisible():
            return
        if not self._anim_timer.isActive():
            self._anim_last = time.monotonic()
            self._anim_timer.start()

    def _animating(self) -> bool:
        if self._geo_to is not None:
            return True
        if self._mode == "expanded":
            # 展开卡片态：paintEvent 把 kick/呼吸平移、tilt/scale 整窗变换全丢
            # （贴边底板被位移或 >1 缩放硬切的实机修复，见 paintEvent），
            # ``_squished_capsule_rect`` 又冻结 squish——上面这些通道收敛到任何
            # 值都不改变一个像素，不能当"动画活跃"判据。否则每次 bump（岛被宠
            # 撞）/余额弹跳都在半透明顶层窗上白跑 ~1s 的 60fps 重绘（实机每帧
            # 一次窗口合成）。几何动画（_geo_to，展开/收起滑移）照常驱动重绘。
            return False
        # 阈值 = 感知量级（44px 高胶囊）：|squish-1| 0.01 → 0.44px 形变、
        # |squish_v| 0.06 → 0.2px 振速、|tilt_v| 3.0 → 0.27°（约 0.6px 边缘位移）。
        # 低于它仍是"动画"的话，每次撞击都要把半透明顶层窗多画几十帧不可见的
        # 尾巴（实测单次撞击的静音耗时 0.88s → 0.61s，见同目录探针记录）。
        return (
            abs(self._kick_x) > 0.3 or abs(self._kick_y) > 0.3
            or abs(self._kick_vx) > 5.0 or abs(self._kick_vy) > 5.0
            or abs(self._squish - 1.0) > 0.01 or abs(self._squish_v) > 0.06
            or abs(self._scale - self._hover_scale_target) > 0.001
            or abs(self._scale_v) > 0.005
            or abs(self._tilt) > 0.05
            or abs(self._tilt_v) > 3.0
            or time.monotonic() < self._breathe_until
        )

    def _settle_bump_animation(self) -> None:
        """把 bump 动效通道（踢动/形变/倾斜）连同速度一起归零。

        只碰 bump 自己驱动的通道：``_scale``/``_scale_v`` 归事件弹跳
        （``_bounce``）与悬停放大，不在撞击动效的收尾范围内（否则会硬切悬停
        放大 / 事件弹跳的中间帧）。
        """
        self._kick_x = self._kick_y = 0.0
        self._kick_vx = self._kick_vy = 0.0
        self._squish, self._squish_v = 1.0, 0.0
        self._tilt, self._tilt_v = 0.0, 0.0

    def _on_anim_tick(self) -> None:
        now = time.monotonic()
        dt = now - (self._anim_last or now)
        self._anim_last = now

        # bump 动效的动画时间上限（按动画时间累计，停表期间的墙钟不计入）：
        # 连撞把弹簧顶在钳位上时阈值判据可能长期为真，到点强制收尾归零。
        if self._bump_anim_left > 0.0:
            self._bump_anim_left = max(0.0, self._bump_anim_left - dt)
            if self._bump_anim_left == 0.0:
                self._settle_bump_animation()

        # 几何滑移（停靠/展开）：定时插值，ease-out
        if self._geo_to is not None and self._geo_from is not None:
            self._geo_t = min(1.0, self._geo_t + dt / 0.18)
            k = ease_out_cubic(self._geo_t)
            rect = QRect(
                round(self._geo_from.x() + (self._geo_to.x() - self._geo_from.x()) * k),
                round(self._geo_from.y() + (self._geo_to.y() - self._geo_from.y()) * k),
                round(self._geo_from.width() + (self._geo_to.width() - self._geo_from.width()) * k),
                round(self._geo_from.height() + (self._geo_to.height() - self._geo_from.height()) * k),
            )
            self._set_free_geometry(rect)
            if self._geo_t >= 1.0:
                self._geo_from = None
                self._geo_to = None
                self._set_free_geometry(self._target_rect())

        # 位移踢动回位 / 微缩放 / 受击倾斜 / 果冻形变回弹
        self._kick_x, self._kick_vx = spring_step(
            self._kick_x, self._kick_vx, 0.0, dt)
        self._kick_y, self._kick_vy = spring_step(
            self._kick_y, self._kick_vy, 0.0, dt)
        self._scale, self._scale_v = spring_step(
            self._scale, self._scale_v, self._hover_scale_target, dt,
            stiffness=_SCALE_STIFFNESS, damping=_SCALE_DAMPING)
        self._scale = max(_SCALE_MIN, min(_SCALE_MAX, self._scale))
        self._tilt, self._tilt_v = spring_step(
            self._tilt, self._tilt_v, 0.0, dt,
            stiffness=_TILT_STIFFNESS, damping=_TILT_DAMPING)
        # 倾斜状态钳位：paintEvent 早就把绘制钳到 ±_TILT_MAX_DEG，不钳状态时
        # 连撞共振能把振幅泵到十几度——弹簧在"画不出来"的幅度里来回，速度随之
        # 无界（实测同向连打 _tilt_v 109），_animating() 的阈值判据随之失效。
        # 与 ``_squish`` 的状态钳位同口径（区别只是那里钳在 _on_anim_tick 前段）。
        self._tilt = max(-_TILT_MAX_DEG, min(_TILT_MAX_DEG, self._tilt))
        self._squish, self._squish_v = spring_step(
            self._squish, self._squish_v, 1.0, dt,
            stiffness=_SQUISH_STIFFNESS, damping=_SQUISH_DAMPING)
        self._squish = max(_SQUISH_MIN, min(_SQUISH_MAX, self._squish))
        # 踢动位移钳制在窗口内（±5px）：弹簧过冲也不画出界被裁
        self._kick_x = max(-5.0, min(5.0, self._kick_x))
        self._kick_y = max(-5.0, min(5.0, self._kick_y))
        if not self._animating():
            # 停表即收尾：连速度一起归零（残留速度会让下一次动画起步时凭空
            # 抖一下，也是 _animating() 判据失效的温床）
            self._settle_bump_animation()
            self._scale = 1.0 if self._hover_scale_target == 1.0 else self._hover_scale_target
            self._bump_anim_left = 0.0
            self._anim_timer.stop()
        self.update()

    def _finish_animations(self) -> None:
        """立即跳到所有动画终点（测试与即需布局用）。"""
        self._anim_timer.stop()
        self._geo_from = None
        self._geo_to = None
        self._kick_x = self._kick_y = 0.0
        self._kick_vx = self._kick_vy = 0.0
        self._squish = 1.0
        self._squish_v = 0.0
        self._scale = 1.0
        self._scale_v = 0.0
        self._tilt = 0.0
        self._tilt_v = 0.0
        self._breathe_until = 0.0
        self._bump_anim_left = 0.0
        self._hover_scale_target = 1.0
        self._set_free_geometry(self._target_rect())
        self.update()

    def _animate_to(self, target: QRect) -> None:
        if target == self.geometry() and not self._anim_timer.isActive():
            self._set_free_geometry(target)
            return
        self._geo_from = self.geometry()
        self._geo_to = target
        self._geo_t = 0.0
        self._ensure_anim_timer()

    def _emit_geometry_changed(self) -> None:
        callback = self.on_geometry_changed
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    def _set_free_geometry(self, rect: QRect) -> None:
        """动画期间解除固定尺寸直接摆几何；到位后由 _apply_fixed_size 锁定。"""
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setGeometry(rect)
        self._emit_geometry_changed()

    # ------------------------------------------------------------ 内部
    def _visible_parts(self) -> tuple[bool, bool, bool, bool]:
        c = self._cfg
        icon = bool(c.get("show_icon", True))
        name = bool(c.get("show_name", True))
        info = bool(c.get("show_info", True))
        status = bool(c.get("show_status", True))
        if not (icon or name or info or status):
            info = True
        return icon, name, info, status

    def _info_text(self) -> str:
        """主信息段的文案（单串视图；绘制走 :meth:`_compose_info_segments`）。

        网络接管分支已在 P1 D1 删除：网络是普通指标段，信息槽永远由
        ``info_mode`` 决定（见 ``_primary_segment``）。
        """
        return self._primary_segment().text

    def _info_color(self, fallback: QColor) -> QColor:
        """余额峰谷主信息跟随设置的峰谷提示颜色开关。

        开启后高峰显示红色、低谷显示绿色；关闭或非余额峰谷模式使用传入的兜底色
        （主信息段用主文字色，见 ``_content_cache``）。
        """
        if str(self._cfg.get("info_mode") or "time") != "balance_tier":
            return fallback
        if not bool(self.config.get("balance_tier_color_enabled", True)):
            return fallback
        try:
            from . import balance as balance_mod

            tier = balance_mod.deepseek_pricing_tier()
        except Exception:
            return fallback
        if tier == "peak":
            return QColor("#e5484d")
        if tier == "idle":
            return QColor("#30a46c")
        return fallback

    # ------------------------------------------------------------ 段管线
    def _font_for(self, layer: str) -> QFont:
        """按字号层取内容字体（懒建 + 缓存；应用字体变化由 changeEvent 清缓存）。"""
        font = self._fonts.get(layer)
        if font is None:
            px, weight = _FONT_LAYERS[layer]
            font = QFont(self.font())
            font.setPixelSize(px)
            font.setWeight(weight)
            self._fonts[layer] = font
        return font

    def _metrics_for(self, layer: str) -> QFontMetrics:
        """按字号层取字体度量（缓存对象：QFontMetrics 构造有成本）。"""
        metrics = self._font_metrics.get(layer)
        if metrics is None:
            metrics = QFontMetrics(self._font_for(layer))
            self._font_metrics[layer] = metrics
        return metrics

    def _fonts_key(self) -> tuple:
        """字号各层的度量指纹（内容层缓存 key 的"字体"分量）。

        指纹探针（行度量 + 数字串宽度）由 ``island_segments`` 提供——系统字体/
        字号/DPI 一变就换键，盒宽与内容层位图都跟着重测。
        """
        return tuple(island_segments.font_metrics_key(self._metrics_for(layer))
                     for layer in _FONT_LAYERS)

    def _metric_ids(self) -> tuple[str, ...]:
        """``island_metrics`` 的段 id 序（**列表序 = 用户优先级 = 尾部先折叠**）。

        这里只做"非空字符串 + 去重"：合法 id 的归一化在 config 层（Slice C），
        未知 id 刻意透传——配置被手改或调用方给的是桩对象时，未知段要降级成
        ``--`` 段（见 ``_unknown_segment``），而不是让整条岛炸掉。
        """
        metrics = self.config.get("island_metrics", [])
        if not isinstance(metrics, (list, tuple)):
            return ()
        ids: list[str] = []
        for item in metrics:
            if not isinstance(item, str) or not item or item in ids:
                continue
            ids.append(item)
        return tuple(ids)

    @staticmethod
    def _state_text(state: str, value: str) -> str:
        """四态兜底：只有 ``ok`` 显示读数；其余一律同宽 ``--``（不伪造 0）。"""
        return value if state == island_segments.STATE_OK else island_segments.UNKNOWN_TEXT

    def _primary_segment(self) -> _InfoSeg:
        """首段（恒为段列表第一项）：time / custom / balance / balance_tier 主信息。

        按模式取测宽样本：时间为 ``88:88`` 定宽（数字不推邻居），余额/峰谷取真实
        最长单行形态，custom 用配置文本自身。现文案超过样本时按现文案加宽（见
        :func:`place_info_segments`），定宽靠样本而不是靠截断。
        """
        mode = str(self._cfg.get("info_mode") or "time")
        if mode == "custom":
            text = str(self._cfg.get("custom_text") or "").strip() or "自定义"
            sample = text
        elif mode == "balance_tier":
            text = self._balance_tier_display_text()
            sample = _PRIMARY_SAMPLES["balance_tier"]
        elif mode == "balance":
            text = self._balance_text
            sample = _PRIMARY_SAMPLES["balance"]
        else:
            from PySide6.QtCore import QTime

            text = QTime.currentTime().toString("HH:mm")
            sample = _PRIMARY_SAMPLES["time"]
        return _InfoSeg(kind="primary", seg_id="primary", label="", text=text,
                        box_text=sample, state=island_segments.STATE_OK)

    def _network_segment(self) -> _InfoSeg:
        """网络段：定宽槽串（``format_network_slot`` 的 5 列契约）直接进字段盒。

        没有 label（↓↑ 是槽串自带的 glyph），采样还没出第一轮时按四态显示 ``--``。
        """
        sample = self._net_sample
        if sample is None:
            text = island_segments.UNKNOWN_TEXT
            state = island_segments.STATE_SAMPLING
        else:
            text = net_monitor.format_network_slot(
                sample.down_bps, sample.up_bps, sample.latency_ms,
                lost=sample.latency_lost)
            state = island_segments.STATE_OK
        return _InfoSeg(kind="metric", seg_id=island_segments.NETWORK, label="",
                        text=text, box_text=_NETWORK_BOX_SAMPLE, state=state)

    def _device_segment(self, metric_id: str) -> _InfoSeg:
        """CPU / 内存段：读数来自共享的 ``SysMonitor`` 快照（无快照 = sampling）。

        有快照但该字段是 None（CPU 差分首样本）也算 sampling——"还没读数"与
        "读数是 0"必须分得开（``--`` 不伪造 0）。
        """
        sample = self._sys_sample
        if sample is None:
            state, value = island_segments.STATE_SAMPLING, None
        elif sample.state != island_segments.STATE_OK:
            state, value = island_segments.STATE_ERROR, None
        else:
            value = (sample.cpu_percent if metric_id == island_segments.CPU
                     else sample.mem_percent)
            state = (island_segments.STATE_OK if value is not None
                     else island_segments.STATE_SAMPLING)
        formatter = (sys_monitor.format_cpu if metric_id == island_segments.CPU
                     else sys_monitor.format_mem)
        return _InfoSeg(kind="metric", seg_id=metric_id, label=_DEVICE_LABELS[metric_id],
                        text=self._state_text(state, formatter(value)),
                        box_text=sys_monitor.MAX_TEXT, state=state)

    @staticmethod
    def _unknown_segment(metric_id: str) -> _InfoSeg:
        """未实现的段 id（配置残留）：降级成 unknown 态 ``--`` 段，不崩不留洞。"""
        return _InfoSeg(kind="metric", seg_id=metric_id,
                        label=metric_id[:island_segments.LABEL_MAX_CHARS],
                        text=island_segments.UNKNOWN_TEXT,
                        box_text=island_segments.UNKNOWN_TEXT,
                        state=island_segments.STATE_UNKNOWN)

    def _compose_info_segments(self) -> list[_InfoSeg]:
        """把"这一帧要画的信息"组合成段列表（数据，不是绘制串）。

        首段恒为主信息段（信息槽内容由 ``info_mode`` 决定），其后按
        ``island_metrics`` 的列表序追加指标段。信息槽整体关掉时返回空列表——
        "没有段"与"首段不是 primary"是两件事。D2 的收缩流水线只需过滤这个列表
        （折尾段、省名字）而不必改绘制。
        """
        if not self._visible_parts()[2]:
            return []
        segments = [self._primary_segment()]
        for metric_id in self._metric_ids():
            if metric_id == island_segments.NETWORK:
                segments.append(self._network_segment())
            elif metric_id in _DEVICE_LABELS:
                segments.append(self._device_segment(metric_id))
            else:
                segments.append(self._unknown_segment(metric_id))
        return segments

    def _character_name(self) -> str:
        character_id = str(self.config.get("character", catalog.DEFAULT_CHARACTER))
        return self.config.character_alias(character_id) or character_id

    def _icon_spec(self) -> str:
        """图标配置原值（auto / img:<路径> / 文字或 emoji）。"""
        return str(self._cfg.get("icon") or _ICON_AUTO).strip()

    def _icon_image_mode(self) -> bool:
        """当前图标是否走图片路径（auto / img:）——只有文字模式才允许画字符。"""
        spec = self._icon_spec()
        return spec == _ICON_AUTO or spec.startswith(_ICON_IMG_PREFIX)

    def _clear_icon_cache(self) -> None:
        """丢弃头像位图与内容层位图；换代计数自增让缓存 key 必然失配。"""
        self._icon_pixmap_cache = None
        self._icon_img_failed = False
        self._icon_pixmap_token += 1
        self._content_pixmap = None
        self._content_cache_key = None

    def _icon_text(self) -> str:
        """文字/emoji 模式画在底圈里的字符（用户主动选择才走这条路）。

        默认 icon="auto" 不经过这里：进程内第一次用 QPainter/QLabel 画 emoji
        字符会触发 DirectWrite 彩色 emoji 字体栈加载，实测定案一次性 +33.6MB
        私有内存（纯文字窗口 61.5MB → 画一个 🐳 后 95.1MB，且与 emoji 个数
        无关）。空值兜底也不再回 "🐳"，避免隐形地重新付这笔税。
        """
        return str(self._cfg.get("icon") or "").strip()[:8]

    def _icon_pixmap(self) -> QPixmap | None:
        """图片模式的图标位图；文字/emoji 模式返回 None。

        auto：provider 命中缓存直接返回；未命中才回调取图，成功即缓存，失败
        （帧未就绪）不缓存——下次重建内容层时重试。
        img:：读文件并缓存，**失败结果也缓存**（否则每帧都去碰磁盘）。
        """
        spec = self._icon_spec()
        if spec.startswith(_ICON_IMG_PREFIX):
            if self._icon_pixmap_cache is not None:
                return self._icon_pixmap_cache
            if self._icon_img_failed:
                return None
            path = spec[len(_ICON_IMG_PREFIX):].strip()
            pm = QPixmap(path) if path else QPixmap()
            if pm.isNull():
                self._icon_img_failed = True
                logger.warning("灵动岛自定义图标加载失败：%s", path)
                return None
            self._icon_pixmap_cache = pm
            self._icon_pixmap_token += 1
            return pm
        if spec != _ICON_AUTO or not callable(self._icon_provider):
            return None
        if self._icon_pixmap_cache is not None:
            return self._icon_pixmap_cache
        try:
            pm = self._icon_provider()
        except Exception:
            logger.exception("灵动岛头像回调失败")
            return None
        if not isinstance(pm, QPixmap) or pm.isNull():
            return None
        self._icon_pixmap_cache = pm
        self._icon_pixmap_token += 1
        return pm

    def _icon_pixmap_scaled(self, logical_px: float) -> QPixmap | None:
        """头像按逻辑尺寸出图（乘 DPR + SmoothTransformation，防 hi-dpi 糊）。"""
        pm = self._icon_pixmap()
        if pm is None:
            return None
        dpr = self.devicePixelRatioF()
        edge = max(1, round(logical_px * dpr))
        scaled = pm.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        return scaled

    def _capsule_width(self) -> int:
        """自然宽 = 内容行各件宽之和（左右各 19px 内边距，见设计稿 §1.1）。

        宽度白名单的落地：**只在 :meth:`_width_key` 变化时重算一次**（缓存），
        而采样值进不了那个键——所以"数字跳动不推邻居"是结构保证。指标段盒宽 =
        声明样本的实测盒宽，读数在盒内右对齐伸缩；主信息段盒宽 = 样本与现文案的
        较宽者（长余额串按现文案加宽，不静默吃字）。
        """
        key = self._width_key()
        if self._width_cache_key == key:
            return self._width_cache
        icon, name, info, status = self._visible_parts()
        width = _CONTENT_PAD_PX * 2
        if icon:
            width += _ICON_PX + _ICON_GAP_PX
        if name:
            width += self._name_layout()[1] + _NAME_GAP_PX
        if info:
            placements = place_info_segments(
                self._compose_info_segments(), start_x=width,
                primary_fm=self._metrics_for("primary"),
                value_fm=self._metrics_for("value"),
                label_fm=self._metrics_for("label"))
            if placements:
                width = placements[-1].right
        if status:
            width += _STATUS_GAP_PX + _STATUS_DOT_PX
        natural = max(_MIN_CAPSULE_W, int(round(width)))
        self._width_cache_key = key
        self._width_cache = natural
        return natural

    def _name_layout(self) -> tuple[str, int]:
        """角色名的显示文本与占位宽（≤96px 右省略）。D2 的 S1 直接整段去掉它。"""
        name = self._character_name()
        metrics = self._metrics_for("name")
        width = int(metrics.horizontalAdvance(name))
        if width <= _NAME_MAX_PX:
            return name, width
        elided = metrics.elidedText(name, Qt.TextElideMode.ElideRight, _NAME_MAX_PX)
        return elided, int(metrics.horizontalAdvance(elided))

    def _width_key(self) -> tuple:
        """自然宽白名单键：**只有这些输入变化**才允许重算自然宽。

        - 可见项 / 角色名（含省略后的文本与占位宽）/ 各段的 ``(id, label, box_text)``
          —— 段增删与段模板变化都在这一项里；
        - 主信息段的 ``text``：它超出样本时按现文案加宽（见 ``place_info_segments``）；
        - 字号各层的度量指纹 + DPR：系统字体/DPI 一变必须重测（字变了盒子也要变）。

        **采样值不在键里**（指标段的 ``text`` 被刻意排除）：它是内容层的事——
        指标段盒宽由声明样本定死，读数在盒内右对齐伸缩。D2 的折叠态同样只体现为
        "段列表变了"，不需要额外的键分量。
        """
        segments = self._compose_info_segments()
        return (
            self._visible_parts(),
            self._name_layout(),
            tuple(
                (seg.seg_id, seg.label, seg.box_text,
                 seg.text if seg.kind == "primary" else "")
                for seg in segments
            ),
            self._fonts_key(),
            round(self.devicePixelRatioF(), 3),
        )

    def _update_size(self) -> None:
        self._set_free_geometry(QRect(self.pos(), self._rest_size()))
        self._apply_fixed_size()

    def _rest_size(self) -> QSize:
        width = self._capsule_width()
        if self._mode == "expanded":
            return QSize(max(width, _CARD_WIDTH), _CAPSULE_HEIGHT + _CARD_HEIGHT)
        return QSize(width, _CAPSULE_HEIGHT)

    def _apply_fixed_size(self) -> None:
        size = self._rest_size()
        if self._mode == "docked" and not self._hover_peek:
            edge = self.dock_edge
            if edge in ("top", "bottom"):
                size = QSize(size.width(), _STRIP_THICKNESS)
            elif edge in ("left", "right"):
                size = QSize(_STRIP_THICKNESS, _STRIP_SIDE)
        self.setFixedSize(size)

    def _clamp_rect(self, rect: QRect) -> QRect:
        screen = self._current_screen()
        if screen is None:
            return rect
        available = screen.availableGeometry()
        x = max(available.left(), min(rect.x(), available.right() - rect.width() + 1))
        y = max(available.top(), min(rect.y(), available.bottom() - rect.height() + 1))
        return QRect(QPoint(x, y), rect.size())

    def _target_rect(self) -> QRect:
        """当前模式下的目标矩形（停靠细条 / 滑出预览 / 正常胶囊 / 展开卡片）。"""
        size = self._rest_size()
        edge = self.dock_edge
        screen = self._current_screen()
        if self._mode == "docked" and not self._hover_peek and screen is not None:
            # 参考矩形锚定当前窗口的真实几何中心，而不是"细条左上角 +
            # 胶囊尺寸"：动画收尾（_on_anim_tick 到位后的重算、
            # _finish_animations、showEvent）调用本函数时窗口已是 64 高
            # 细条，旧拼法的中心凭空高出 (64-44)/2 = 10px，每次收回/停靠
            # 动画结束细条就上跳一截，反复悬停累计上窜
            rect = QRect(self.pos(), size)
            rect.moveTop(self.y() + self.height() // 2 - size.height() // 2)
            return strip_rect_for(rect, edge, screen.availableGeometry())
        if edge != "none" and self._mode in ("docked", "expanded") \
                and screen is not None:
            # 从停靠边向内展开：顶/底锚定该边，左右以细条纵向中心展开
            available = screen.availableGeometry()
            rect = QRect(self.pos(), size)
            if edge == "top":
                rect.moveTop(available.top())
            elif edge == "bottom":
                rect.moveBottom(available.bottom())
            elif edge == "left":
                rect.moveLeft(available.left())
                rect.moveTop(self.y() + self.height() // 2 - size.height() // 2)
            elif edge == "right":
                rect.moveRight(available.right())
                rect.moveTop(self.y() + self.height() // 2 - size.height() // 2)
            return self._clamp_rect(rect)
        return self._clamp_rect(QRect(self.pos(), size))

    def _screen_at(self, point: QPoint):
        """按给定全局坐标选屏；落在多屏空洞（错位拼接）时回退主屏。"""
        return QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()

    def _current_screen(self):
        screen = self._screen_at(self.pos())
        return screen

    def _apply_position(self) -> None:
        self._update_size()
        screen = self._current_screen()
        available = screen.availableGeometry() if screen is not None else None
        x = self._cfg.get("x")
        y = self._cfg.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            pos = QPoint(int(x), int(y))
        else:
            pos = (
                QPoint(available.right() - self.width() - _EDGE_MARGIN,
                       available.top() + _EDGE_MARGIN)
                if available else QPoint(100, 100)
            )
        self.move(pos)
        self._clamp_to_screen()
        # 展开卡片态不被停靠劫持：卡片是用户当前的交互焦点，设置保存触发的
        # 位置应用不能把 _mode 改成 docked（卡片会留在 16px 细条上收不起来）；
        # 收起时 collapse_card 会按 dock_edge 自行决定是否停靠
        if self.dock_edge != "none" and self._mode != "expanded":
            self._mode = "docked"
            self._hover_peek = False
            target = self._target_rect()
            self._set_free_geometry(target)
            self._apply_fixed_size()

    def _clamp_to_screen(self) -> None:
        if self._mode == "docked" and not self._hover_peek:
            return
        screen = self._current_screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = max(available.left(), min(self.x(), available.right() - self.width() + 1))
        y = max(available.top(), min(self.y(), available.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
            # 位置校正也要通知碰撞体重提交，否则碰撞体留在旧位置
            self._emit_geometry_changed()

    def _save_position(self) -> None:
        island = dict(self._cfg)
        island["x"] = self.x()
        island["y"] = self.y()
        self._cfg = island
        self.config.set("dynamic_island", island)
        self.config.save()

    def _save_dock_edge(self, edge: str) -> None:
        island = dict(self._cfg)
        island["dock_edge"] = edge if edge in _DOCK_EDGES else "none"
        self._cfg = island
        self.config.set("dynamic_island", island)
        self.config.save()

    # ------------------------------------------------------------ 绘制
    def _style_palette(self):
        """返回 (背景, 主文字色, 次文字色)。背景可为 QColor 或 QLinearGradient。

        所有风格的 alpha 都乘上不透明度设置。
        """
        opacity = self._opacity()
        style = str(self._cfg.get("style") or "dark")
        if style == "light":
            return (QColor(255, 255, 255, round(242 * opacity)),
                    QColor(31, 35, 40), QColor(107, 114, 128))
        if style == "glass":
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor(255, 255, 255, round(196 * opacity)))
            gradient.setColorAt(0.5, QColor(230, 242, 255, round(150 * opacity)))
            gradient.setColorAt(1.0, QColor(255, 255, 255, round(210 * opacity)))
            return gradient, QColor(35, 45, 60), QColor(90, 105, 125)
        return (QColor(28, 30, 38, round(235 * opacity)),
                QColor(235, 238, 245), QColor(160, 170, 190))

    def _keyline_color(self) -> QColor:
        """深色底上的 1px 分界描边（暗壁纸下把胶囊轮廓勾出来）。"""
        style = str(self._cfg.get("style") or "dark")
        if style in ("light", "glass"):
            return QColor(0, 0, 0, 28)
        return QColor(255, 255, 255, 52)

    def _divider_color(self) -> QColor:
        """段间分隔竖线的颜色：比 keyline 再弱一档。

        轮廓线管"窗在哪"，分隔线只管"段在哪"——两者同色会让胶囊边缘与段边界
        抢注意力（暗 `#FFF`α36 / 亮 `#1F2328`α31 / glass `#232D3C`α36）。
        """
        style = str(self._cfg.get("style") or "dark")
        if style == "light":
            return QColor(31, 35, 40, 31)
        if style == "glass":
            return QColor(35, 45, 60, 36)
        return QColor(255, 255, 255, 36)

    @staticmethod
    def _readable_card_background(background):
        """展开卡片底板：alpha 钳到下限 215。

        胶囊透明度设置只该影响胶囊本体（不挡视线）；卡片是阅读界面，
        跟着透明化会让余额/消息直接糊在壁纸上（实机反馈）。QColor 与
        glass 的 QLinearGradient 两种背景分别钳制。
        """
        if isinstance(background, QLinearGradient):
            clamped = QLinearGradient(background)
            for pos, color in background.stops():
                c = QColor(color)
                c.setAlpha(max(c.alpha(), 215))
                clamped.setColorAt(pos, c)
            return clamped
        c = QColor(background)
        c.setAlpha(max(c.alpha(), 215))
        return c

    def _status_dot_color(self) -> QColor:
        if self._agent_active:
            return QColor(64, 150, 255)
        if self._pet_visible:
            return QColor(80, 220, 120)
        return QColor(130, 140, 155)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 展开卡片时跳过一切整窗变换（kick 平移/呼吸/倾斜/缩放）：卡片底板
        # 贴窗口边缘绘制，任何位移或 >1 缩放都会把它顶出窗口被硬切（截边
        # 实机反馈；kick 来自展开后的余额刷新弹跳，是必然路径）
        if self._mode == "expanded":
            tilt, scale = 0.0, 1.0
        else:
            # 动效变换：整数位移（文字锐利）+ 呼吸微浮动
            kick_x = round(self._kick_x)
            kick_y = round(self._kick_y)
            if time.monotonic() < self._breathe_until:
                kick_y += round(1.5 * math.sin(time.monotonic() * 2.6))
            if kick_x or kick_y:
                painter.translate(kick_x, kick_y)
            tilt = max(-_TILT_MAX_DEG, min(_TILT_MAX_DEG, self._tilt))
            scale = max(_SCALE_MIN, min(_SCALE_MAX, self._scale))
        if tilt or scale != 1.0:
            cx = self.width() / 2.0
            cy = min(self.height(), _CAPSULE_HEIGHT) / 2.0
            painter.translate(cx, cy)
            painter.rotate(tilt)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        if self._mode == "docked" and not self._hover_peek:
            self._paint_strip(painter)
        else:
            self._paint_capsule(painter)
        painter.end()

    def _squished_capsule_rect(self) -> tuple[QRectF, float]:
        """果冻形变后的胶囊绘制矩形（内缩 _CAPSULE_INSET 留形变余量）。

        只返回外形的几何——文字/图标不在这里面变换，保持锐利。
        squish<1 时竖向压扁、横向鼓出（面积大致守恒），绕胶囊中心形变。
        """
        base = QRectF(_CAPSULE_INSET, _CAPSULE_INSET,
                      self.width() - _CAPSULE_INSET * 2,
                      _CAPSULE_HEIGHT - _CAPSULE_INSET * 2)
        # 展开卡片态冻结形变（与整窗变换禁用同口径）：squish 鼓出会把
        # 贴边底板两侧的胶囊圆角削掉（实测 342.8px > 340px 窗口宽）
        squish = 1.0 if self._mode == "expanded" else \
            max(_SQUISH_MIN, min(_SQUISH_MAX, self._squish))
        if abs(squish - 1.0) < 0.002:
            return base, base.height() / 2.0
        sy = squish
        sx = 1.0 + (1.0 - sy) * 0.3  # 竖压横鼓（权重打折，鼓出不超出内缩余量）
        w, h = base.width() * sx, base.height() * sy
        cx, cy = base.center().x(), base.center().y()
        return QRectF(cx - w / 2.0, cy - h / 2.0, w, h), h / 2.0

    def _paint_strip(self, painter: QPainter) -> None:
        """停靠细条：圆角条 + 靠屏侧主题色亮线 + 状态点（竖条加图标）。"""
        rect = QRectF(0, 0, self.width(), self.height())
        radius = min(rect.width(), rect.height()) / 2.0
        background, primary, _secondary = self._style_palette()
        opacity = self._opacity()
        if isinstance(background, QColor):
            base = QColor(background)
            base.setAlpha(min(255, round(210 * opacity)))
        else:
            base = QColor(255, 255, 255, round(210 * opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(rect, radius, radius)

        # 靠屏一侧的 2px 亮线（深壁纸上也能一眼找到细条）
        accent = QColor(self._accent_color())
        accent.setAlpha(220)
        painter.setBrush(accent)
        edge = self.dock_edge
        if edge == "top":
            painter.drawRoundedRect(QRectF(6, 0, rect.width() - 12, 2), 1, 1)
        elif edge == "bottom":
            painter.drawRoundedRect(QRectF(6, rect.height() - 2, rect.width() - 12, 2), 1, 1)
        elif edge == "left":
            painter.drawRoundedRect(QRectF(0, 6, 2, rect.height() - 12), 1, 1)
        elif edge == "right":
            painter.drawRoundedRect(QRectF(rect.width() - 2, 6, 2, rect.height() - 12), 1, 1)

        dot_size = 8
        painter.setBrush(self._status_dot_color())
        if edge in ("left", "right"):
            # 竖条：上方角色图标、下方状态点。头像走 drawPixmap（不碰文字栈）；
            # emoji 文字模式维持原小字号（11px）防裁切；auto 模式 provider 没
            # 就绪就只留状态点，绝不回退去画 🐳（那等于白付 33MB 税额）
            icon_pm = self._icon_pixmap_scaled(_ICON_STRIP_PX)
            if icon_pm is not None:
                painter.drawPixmap(
                    QPointF((rect.width() - _ICON_STRIP_PX) / 2.0, 8.0), icon_pm)
            elif not self._icon_image_mode():
                painter.setPen(primary if isinstance(primary, QColor) else QColor(31, 35, 40))
                icon_font = painter.font()
                icon_font.setPixelSize(11)
                painter.setFont(icon_font)
                fm = painter.fontMetrics()
                painter.drawText(
                    QRectF(0, 8, rect.width(), fm.height()),
                    Qt.AlignmentFlag.AlignCenter, self._icon_text())
                painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._status_dot_color())
            painter.drawEllipse(QRectF(
                (rect.width() - dot_size) / 2, rect.height() - dot_size - 8,
                dot_size, dot_size))
        else:
            painter.drawEllipse(QRectF(
                (rect.width() - dot_size) / 2, (rect.height() - dot_size) / 2,
                dot_size, dot_size))

    def _content_cache(self) -> QPixmap:
        """内容层（头像/角色名/信息段/状态灯）的缓存位图。

        为什么缓存（拖岛扫鱼实测定案）：paintEvent 均值 6.2ms，大头是 CJK
        文字的 shaping/回退字体解析；而内容只在刷新（时间跳变/余额刷新/
        配置变更/采样值变化）时变化，拖拽/弹簧期间逐帧重画纯属浪费。缓存后每帧
        一次 blit（亚毫秒）。blit 走同一 painter 的整窗变换（kick 为整数平移，
        文字锐利口径不变）；squish 只调制胶囊外形、本来就不碰内容层。

        key 覆盖所有影响像素的输入（可见项/各段 text+state/字号指纹/颜色/DPR/
        宽度），任一变化自动重建。**采样值变化只换这张位图**：窗口几何走
        ``_capsule_width`` 的白名单，两者互不牵连。
        """
        icon, name, info, status = self._visible_parts()
        segments = self._compose_info_segments()
        _background, primary_color, secondary_color = self._style_palette()
        # 主信息段（L1）：峰谷模式跟随设置的峰谷色，其余用主文字色
        primary_text_color = self._info_color(primary_color)
        name_text, _name_w = self._name_layout()
        dpr = self.devicePixelRatioF()
        key = (
            icon, name, info, status,
            self._icon_text() if icon else "",
            name_text if name else "",
            tuple((seg.seg_id, seg.text, seg.state) for seg in segments),
            self._accent_color().name() if icon else "",
            primary_color.name() if name else "",
            primary_text_color.name() if segments else "",
            secondary_color.name() if segments else "",
            self._divider_color().name() if len(segments) > 1 else "",
            self._status_dot_color().name() if status else "",
            self._fonts_key(), dpr, self.width(),
        )
        if self._content_pixmap is not None and self._content_cache_key == key:
            return self._content_pixmap
        # 内容层的命中路径不问 provider（否则拖拽期间每帧取图），只有重建时才问。
        # auto 模式 provider 返回 None 时也不写进 key，于是"没头像"的内容层照样
        # 命中缓存，等下次真正重建（时间/余额/配置/采样变化）时再重试取图。
        icon_pm = self._icon_pixmap_scaled(_ICON_PIXMAP_PX) if icon else None
        if icon_pm is not None:
            key = key + (self._icon_pixmap_token,)
            if self._content_pixmap is not None and self._content_cache_key == key:
                return self._content_pixmap
        pm = QPixmap(max(1, round(self.width() * dpr)),
                     max(1, round(_CAPSULE_HEIGHT * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = _CAPSULE_INSET + 13.0
        baseline = _CAPSULE_HEIGHT / 2.0 + _BASELINE_DY
        painter.setPen(Qt.PenStyle.NoPen)
        if icon:
            painter.setBrush(self._accent_color())
            painter.drawEllipse(QRectF(x, (_CAPSULE_HEIGHT - _ICON_PX) / 2, _ICON_PX, _ICON_PX))
            if icon_pm is not None:
                # 头像居中画进底圈：drawPixmap 不碰文字/emoji 字体栈
                painter.drawPixmap(
                    QPointF(x + (_ICON_PX - _ICON_PIXMAP_PX) / 2.0,
                            (_CAPSULE_HEIGHT - _ICON_PIXMAP_PX) / 2.0),
                    icon_pm)
            elif not self._icon_image_mode():
                # emoji/文字图标沿用窗口默认字体（用户主动选 emoji 才走这条路）
                painter.setFont(self.font())
                painter.setPen(QColor(255, 255, 255))
                fm = self.fontMetrics()
                painter.drawText(
                    QRectF(x, (_CAPSULE_HEIGHT - fm.height()) / 2 - 1, _ICON_PX, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    self._icon_text(),
                )
                painter.setPen(Qt.PenStyle.NoPen)
            # auto 模式 provider 没就绪：只画底圈，绝不回退画 🐳（那是白付
            # 一次 33MB 的 DirectWrite 彩色 emoji 字体栈税）
            x += _ICON_PX + _ICON_GAP_PX
        if name:
            # 角色名：L3 12px 次色，右省略到 96px（名字是身份不是数据）
            painter.setFont(self._font_for("name"))
            painter.setPen(primary_color)
            painter.drawText(QPointF(x, baseline), name_text)
            x += _name_w + _NAME_GAP_PX
        placements = place_info_segments(
            segments, start_x=x,
            primary_fm=self._metrics_for("primary"),
            value_fm=self._metrics_for("value"),
            label_fm=self._metrics_for("label"))
        for placement in placements:
            seg = placement.seg
            if placement.divider_x is not None:
                # 段间竖线：1×14px、槽位正中；首段前与状态点前都不画
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._divider_color())
                painter.drawRect(QRectF(
                    placement.divider_x,
                    (_CAPSULE_HEIGHT - _DIVIDER_H_PX) / 2.0,
                    _DIVIDER_W_PX, _DIVIDER_H_PX))
            if seg.kind == "primary":
                painter.setFont(self._font_for("primary"))
                painter.setPen(primary_text_color)
            else:
                if seg.label:
                    painter.setFont(self._font_for("label"))
                    painter.setPen(secondary_color)
                    painter.drawText(QPointF(placement.label_x, baseline), seg.label)
                painter.setFont(self._font_for("value"))
                # sampling/unknown/error 一律次色、不染告警色：胶囊上不做状态染色
                # （状态差异交给状态点与卡片），平衡"安静"与"诚实的 --"
                painter.setPen(primary_color if seg.state == island_segments.STATE_OK
                               else secondary_color)
            # 盒内右对齐 + 统一基线（所有字号层共用一条基线，见 _BASELINE_DY）
            painter.drawText(
                QPointF(placement.box_x + placement.box_w - placement.text_w, baseline),
                placement.text)
            x = placement.right
        if status:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._status_dot_color())
            painter.drawEllipse(QRectF(
                x + _STATUS_GAP_PX, (_CAPSULE_HEIGHT - _STATUS_DOT_PX) / 2,
                _STATUS_DOT_PX, _STATUS_DOT_PX))
        painter.end()
        self._content_pixmap = pm
        self._content_cache_key = key
        return pm

    def _paint_capsule(self, painter: QPainter) -> None:
        # 展开时先画卡片底板（胶囊下方一整块，圆角连续；内容区遵守同心圆角）
        if self._mode == "expanded":
            panel = QRectF(0, 0, self.width(), self.height())
            background, _p, _s = self._style_palette()
            # 卡片底板走可读性钳制（不随胶囊透明度降下去）
            background = self._readable_card_background(background)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 40))
            painter.drawRoundedRect(panel.translated(0, 2), 18, 18)
            painter.setBrush(background)
            painter.drawRoundedRect(panel, 18, 18)
            painter.setPen(QPen(self._keyline_color(), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(panel.adjusted(0.5, 0.5, -0.5, -0.5), 17.5, 17.5)

        # 胶囊外形：内缩 _CAPSULE_INSET + 果冻形变（只有外形参与 squish）
        rect, radius = self._squished_capsule_rect()

        # 柔和阴影：底层半透明圆角矩形（跟随形变）
        if self._mode != "expanded":
            shadow = rect.translated(0, 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 46))
            painter.drawRoundedRect(shadow, radius, radius)

        # 胶囊主体（白色 / 黑色 / 玻璃质感）；内容层已下沉到 _content_cache，
        # 主/次文字色在这里不再使用
        background, _primary_color, _secondary_color = self._style_palette()
        painter.setBrush(background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
        style = str(self._cfg.get("style") or "dark")
        if style == "glass":
            # 玻璃高光描边，强化“液化玻璃”边缘
            painter.setPen(QPen(QColor(255, 255, 255, 130), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)
        else:
            # 深色底 key line：在暗壁纸上把轮廓勾出来
            painter.setPen(QPen(self._keyline_color(), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        # 内容层（图标/名称/信息/状态灯）：缓存位图 blit——文字逐帧重画是
        # 实测大头（见 _content_cache）；内容绝不参与形变，口径与原"按未
        # 形变静止位绘制"一致
        painter.drawPixmap(0, 0, self._content_cache())

    # ------------------------------------------------------------ 显隐休眠
    def hideEvent(self, event) -> None:  # noqa: N802
        """隐藏即休眠：信息轮询/动效/停靠收回/卡片自动收起全部停表，
        隐藏态零定时器空转。"""
        super().hideEvent(event)
        self._info_timer.stop()
        self._tier_tick_timer.stop()
        self._anim_timer.stop()
        self._dock_back_timer.stop()
        self._card_collapse_timer.stop()
        # 网络槽/设备槽同样休眠：采样线程与读取定时器一起停（探测在途最多 1s，
        # 不 join；订阅保留，显示后 _sync_*_slot 幂等恢复）
        self._pause_network_slot()
        self._pause_sys_slot()

    def changeEvent(self, event) -> None:  # noqa: N802
        """应用字体/DPI 变化：丢掉按字号层缓存的字体与度量（下次取值重建）。

        度量缓存按对象身份缓存，字体真的换了却还拿旧度量，盒宽与内容层位图就会
        继续用旧字号画——这是"字体指纹"白名单分量必须能变的前提。
        """
        super().changeEvent(event)
        if event is not None and event.type() == QEvent.Type.FontChange:
            self._clear_font_cache()

    def _clear_font_cache(self) -> None:
        self._fonts.clear()
        self._font_metrics.clear()
        self._width_cache_key = None
        self._content_cache_key = None

    def showEvent(self, event) -> None:  # noqa: N802
        """重新显示：恢复信息轮询并立即刷新（沉睡期间的内容变化补上），
        几何直接归位（隐藏可能打断了停靠/展开动画）。"""
        super().showEvent(event)
        self._finish_animations()
        self._info_timer.start()
        self._schedule_next_balance_tier_refresh()
        self._sync_network_slot()
        self._sync_sys_slot()
        self._refresh()
        # 原生窗口此刻已就绪；再延迟一拍重申一次 topmost——show 期间 Qt 还在
        # 收尾窗口排序，它可能覆盖同步那次（口径同 legacy window.py showEvent）
        QTimer.singleShot(0, self, self.reassert_topmost)

    # ------------------------------------------------------------ 悬停
    def enterEvent(self, event) -> None:  # noqa: N802
        # 展开卡片时不悬停放大（整窗缩放会截掉贴边的卡片底板，见 paintEvent）
        self._hover_scale_target = 1.0 if self._mode == "expanded" else 1.02
        if self._mode == "docked" and not self._hover_peek:
            self._dock_back_timer.stop()
            self._hover_peek = True
            self._animate_to(self._target_rect())
        self._ensure_anim_timer()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_scale_target = 1.0
        if self._mode == "docked" and self._hover_peek:
            self._dock_back_timer.start()
        self._ensure_anim_timer()
        super().leaveEvent(event)

    def _dock_back(self) -> None:
        if self._mode == "docked" and self._hover_peek:
            self._hover_peek = False
            self._animate_to(self._target_rect())

    # ------------------------------------------------------------ 鼠标
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # 点岛 = 用户明确要它在前（legacy「点击把窗口带回置顶组最前」口径，
            # 只改 z 序不抢键盘焦点）
            self.reassert_topmost()
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is None or event.buttons() & Qt.MouseButton.LeftButton == 0:
            return
        global_pos = event.globalPosition().toPoint()
        if not self._dragging and (global_pos - self._press_global).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
            # 起拖先清几何插值状态（滑出/停靠/归位动画的目标）：否则动画
            # 每 16ms 把窗口拽回目标位，与拖拽 move() 互抢（不跟手/60Hz
            # 抖动，且期间碰撞结算被 _geo_to 守卫全程跳过）。注意不停动画
            # 表：_on_anim_tick 只在 _geo_to 非 None 时插值几何，停表会把
            # squish/kick 弹簧冻在中途
            self._geo_from = None
            self._geo_to = None
            if self._mode == "expanded":
                self.collapse_card(animate=False)  # 拖拽起手直接落位，不播收起动画
            if self._mode == "docked":
                # 拖出停靠：进入正常模式跟随光标
                self._mode = "normal"
                self._hover_peek = False
                self._apply_fixed_size()
        if self._dragging and self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)
            self._emit_geometry_changed()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # 选屏按**松手光标**的全局位置，不按窗口左上角：跨屏拖拽的触发带恰等于
        # 抓取偏移量——光标刚过屏缝松手时左上角仍在原屏，按左上角选屏会把整窗
        # 夹回原屏边缘（夹取距离 0 → 就近判定停靠）并落回原屏，用户看到的是
        # "拖过去又弹回来"（issue #154）。光标在哪块屏，岛就落在哪块屏。
        # 心跳 _clamp_to_screen 仍按窗口左上角：跨缝中途夹回所在屏是保守合理
        # 行为，不动。
        screen = self._screen_at(event.globalPosition().toPoint())
        available = screen.availableGeometry() if screen is not None else None
        if not self._dragging:
            if self._mode == "docked" and not self._hover_peek:
                # 细条单击 = 滑出预览（不停留展开卡片，保持轻量）
                self._hover_peek = True
                self._animate_to(self._target_rect())
                self._dock_back_timer.start()
            elif self._click_action() == "toggle_pet":
                self.clicked.emit()
            elif self._hidden_chat_enabled() and not self._pet_visible and self._chat_available:
                # 桌宠隐藏时岛是唯一常驻交互面：单击直接弹对话气泡
                #（恢复桌宠的入口由气泡内的「显示桌宠」按钮承接）；
                # 无聊天能力的构建（纯桌宠版）不进此分支——回退 else 展开
                # 卡片，由卡片的「显示桌宠」按钮承接恢复入口
                self.chat_requested.emit()
            else:
                self.expand_card()
        else:
            # 先夹回屏幕再判定停靠：拖出屏外的落点按夹后位置算距离
            if available is not None:
                x = max(available.left(), min(self.x(), available.right() - self.width() + 1))
                y = max(available.top(), min(self.y(), available.bottom() - self.height() + 1))
                self.move(x, y)
            edge = "none"
            if available is not None and self._edge_dock_enabled():
                edge = dock_edge_for(self.geometry(), available)
                rect = self.geometry()
                logger.info(
                    "灵动岛拖拽落点 (%d,%d)：距四边 top=%d bottom=%d left=%d right=%d"
                    "（阈值 %d）→ dock=%s",
                    rect.x(), rect.y(),
                    abs(rect.top() - available.top()),
                    abs(available.bottom() - rect.bottom()),
                    abs(rect.left() - available.left()),
                    abs(available.right() - rect.right()),
                    _DOCK_THRESHOLD, edge)
            self._save_dock_edge(edge)
            self._save_position()
            if edge != "none":
                self._mode = "docked"
                self._hover_peek = False
                self._animate_to(self._target_rect())
            elif self._mode == "docked":
                self._mode = "normal"
                self._animate_to(self._target_rect())
        self._press_global = None
        self._drag_offset = None
        self._dragging = False
        self._emit_geometry_changed()
        event.accept()

    # ------------------------------------------------------------ 测试钩子
    def _debug_state(self) -> dict:
        """测试用快照：模式/停靠边/几何动画是否活跃。"""
        return {
            "mode": self._mode,
            "dock_edge": self.dock_edge,
            "hover_peek": self._hover_peek,
            "animating": self._anim_timer.isActive(),
            "card_visible": self._card_box.isVisible(),
        }
