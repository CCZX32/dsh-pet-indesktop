"""灵动岛胶囊窗口（唯一 Qt 面）。

职责只有四件事：**取数**（采样线程的快照）、**组段**（把读数变成
``layout._InfoSeg``）、**排版**（调 ``layout.plan_info_row`` 拿行计划）、**绘制**。
判定逻辑一律在 ``petcore/island/`` 的零 Qt 层里，这里不许再写一套。

三条不变量（改这个文件前先读）：

1. **宽度只由模板驱动**：段的盒宽来自声明样本（``max_text``），读数只在盒内伸缩。
   任何"按当前读数算宽"的写法都会让岛随数字抖。
2. **看不清就不采**：岛隐藏 / 卡片折叠 / 段被折进 ``+N`` 时停掉对应采样线程。
3. **点胶囊 = 展开/收起卡片**；``island_click_action=toggle_pet`` 时改为透传点击。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..island import layout, segments as isl
from ..platform import netmon, sysmon

#: 胶囊窗口高（固定，永不随内容变）。
CAPSULE_HEIGHT = 44
#: 绘制内缩（左右上下留 6px 给阴影/悬停）。
CAPSULE_INSET = 6
#: 贴边边距。
EDGE_MARGIN = 16
#: 胶囊自然宽下限（极小内容下仍是可点可拖的胶囊）。
MIN_CAPSULE_WIDTH = layout._MIN_CAPSULE_W
#: 卡片宽度区间与自动收起时间。
CARD_MIN_WIDTH = 340
CARD_MAX_WIDTH = 420
CARD_AUTO_COLLAPSE_MS = 15000
#: 内容行左内边距 / 图标 / 图标与名字间距 / 名字上限与间距。
CONTENT_PAD = layout._CONTENT_PAD_PX
ICON_PX = layout._ICON_PX
ICON_GAP = layout._ICON_GAP_PX
NAME_MAX = layout._NAME_MAX_PX
NAME_GAP = layout._NAME_GAP_PX
#: 告警点尺寸（行尾状态点）。
STATUS_DOT = layout._STATUS_DOT_PX
STATUS_GAP = layout._STATUS_GAP_PX
#: 统一基线偏移（胶囊垂直中心下方 5px）。
BASELINE_DY = 5.0
#: 字号层（逻辑 px）。
FONT_LAYERS = {
    "primary": (14, QFont.Weight.DemiBold),
    "value": (13, QFont.Weight.DemiBold),
    "name": (12, QFont.Weight.Normal),
    "label": (10, QFont.Weight.Normal),
    "aux": (11, QFont.Weight.Normal),
}
#: 三套配色（主分支同口径：深浅色不跟系统主题，由配置显式选）。
STYLE_PALETTES = {
    "dark": {
        "bg": (28, 30, 38, 235),
        "text": (235, 238, 245),
        "muted": (160, 170, 190),
        "keyline": (255, 255, 255, 52),
        "divider": (255, 255, 255, 36),
    },
    "light": {
        "bg": (255, 255, 255, 242),
        "text": (31, 35, 40),
        "muted": (107, 114, 128),
        "keyline": (0, 0, 0, 28),
        "divider": (31, 35, 40, 31),
    },
    "glass": {
        "bg": (236, 244, 255, 214),
        "text": (35, 45, 60),
        "muted": (90, 105, 125),
        "keyline": (0, 0, 0, 28),
        "divider": (35, 45, 60, 36),
    },
}
#: 强调色（图标底圈）。
ACCENTS = {
    "blue": "#40b8ff",
    "green": "#34c77b",
    "purple": "#9b7bff",
    "pink": "#ff7ab8",
    "orange": "#ffa94d",
}
ALERT_COLORS = {"warn": "#f0b44c", "crit": "#f2777a"}
#: 卡片行里的段名（胶囊上是纯 glyph 的段也要有可读名字）。
CARD_NAMES = {"network": "网络", "cpu": "CPU", "mem": "内存", "gpu": "GPU", "fps": "帧率"}
#: 主信息段（时间）的测宽样本：定宽形态，时间跳变不推邻居。
TIME_BOX_SAMPLE = "88:88"


@dataclass(frozen=True)
class IslandConfig:
    """一次刷新读到的一组设置（`refresh_from_config()` 现取）。"""

    enabled: bool = False
    show_icon: bool = True
    show_name: bool = True
    show_status: bool = True
    info_mode: str = "time"
    custom_text: str = ""
    style: str = "dark"
    opacity: float = 1.0
    accent: str = "blue"
    click_action: str = "expand"
    metrics: tuple[str, ...] = (isl.CPU, isl.MEM)
    character_name: str = ""

    @classmethod
    def from_config(cls, config, *, character_name: str = "") -> "IslandConfig":
        def value(key, default):
            try:
                raw = config.get(key, default)
            except Exception:  # noqa: BLE001 - 配置异常回默认
                return default
            return default if raw is None else raw

        metrics = value("island_metrics", [])
        if not isinstance(metrics, (list, tuple)):
            metrics = []
        return cls(
            enabled=bool(value("island_enabled", False)),
            show_icon=bool(value("island_show_icon", True)),
            show_name=bool(value("island_show_name", True)),
            show_status=bool(value("island_show_status", True)),
            info_mode=str(value("island_info_mode", "time")),
            custom_text=str(value("island_custom_text", "") or ""),
            style=str(value("island_style", "dark")),
            opacity=float(value("island_opacity", 1.0)),
            accent=str(value("island_accent", "blue")),
            click_action=str(value("island_click_action", "expand")),
            metrics=tuple(str(item) for item in metrics),
            character_name=character_name,
        )


class DynamicIsland(QWidget):
    """顶部胶囊。点它展开卡片，再点收起；拖动可换位置。"""

    clicked = Signal()
    settings_requested = Signal()
    card_expanded = Signal(bool)

    def __init__(self, config, *, character_name: str = "", parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("dynamicIsland")
        self.config = config

        self.settings = IslandConfig.from_config(config, character_name=character_name)
        self._fonts: dict[str, QFont] = {}
        self._metrics: dict[str, QFontMetrics] = {}
        self._font_key_cache: tuple | None = None
        self._alert: dict[str, str] = {}
        self._row: tuple = ()
        self._plan: layout.ShrinkPlan | None = None
        self._width_key: tuple | None = None
        self._expanded = False
        self._dragging = False
        self._press_global: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._ticks = 0

        self.net_monitor = netmon.NetMonitor(interval=1.0)
        self.sys_monitor = sysmon.SysMonitor(interval=1.0)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)

        self._card_timer = QTimer(self)
        self._card_timer.setSingleShot(True)
        self._card_timer.setInterval(CARD_AUTO_COLLAPSE_MS)
        self._card_timer.timeout.connect(self.collapse_card)

        self.card = _IslandCard(self)
        self.card.hide()

        self._rebuild_row()
        self._apply_position(initial=True)
        self._update_size()

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        self._clock.start()
        self._card_timer.stop()
        self._sync_sampling()

    def stop(self) -> None:
        self._clock.stop()
        self._card_timer.stop()
        self.net_monitor.stop()
        self.sys_monitor.stop()

    def set_visible(self, visible: bool) -> None:
        if visible and not self.isVisible():
            self.show()
            self.start()
        elif not visible and self.isVisible():
            self.hide()
            self.stop()

    def refresh_from_config(self) -> None:
        """设置改完调用：重读配置、重排段、按需重进采样。"""
        self.settings = IslandConfig.from_config(
            self.config, character_name=self.settings.character_name
        )
        self._rebuild_row()
        self._update_size()
        self._sync_sampling()
        if self._expanded:
            self._rebuild_card()

    def _sync_sampling(self) -> None:
        """看不清就不采：岛隐藏、段没开、段被折叠时都停样本。"""
        visible = self.isVisible() and self._clock.isActive() and self.settings.enabled
        folded = set(self._plan.folded) if self._plan is not None else set()
        wants_net = (
            visible
            and isl.NETWORK in self.settings.metrics
            and isl.NETWORK not in folded
        )
        wants_sys = visible and any(
            metric in self.settings.metrics and metric not in folded
            for metric in (isl.CPU, isl.MEM)
        )
        for monitor, wanted in ((self.net_monitor, wants_net), (self.sys_monitor, wants_sys)):
            # Reconcile desired state, not thread liveness: a cancelled OS reader
            # may still be exiting. Retrying start on the next tick is safe.
            if wanted:
                monitor.start()
            else:
                monitor.stop()

    # ------------------------------------------------------------ 字体与配色

    def _font(self, layer: str) -> QFont:
        font = self._fonts.get(layer)
        if font is None:
            size, weight = FONT_LAYERS[layer]
            font = QFont(self.font())
            font.setPixelSize(int(size))
            font.setWeight(weight)
            self._fonts[layer] = font
        return font

    def _fm(self, layer: str) -> QFontMetrics:
        metrics = self._metrics.get(layer)
        if metrics is None:
            metrics = QFontMetrics(self._font(layer))
            self._metrics[layer] = metrics
        return metrics

    def _font_key(self) -> tuple:
        """字体指纹：任一层度量变化（字号/家族/DPI）就换键 → 盒宽重测。"""
        if self._font_key_cache is None:
            self._font_key_cache = tuple(
                isl.font_metrics_key(self._fm(layer))
                for layer in ("primary", "value", "label", "name")
            )
        return self._font_key_cache

    def _palette(self) -> dict[str, tuple[int, int, int, int]]:
        palette = dict(STYLE_PALETTES.get(self.settings.style, STYLE_PALETTES["dark"]))
        alpha = max(0.4, min(1.0, float(self.settings.opacity)))
        bg = palette["bg"]
        palette["bg"] = (bg[0], bg[1], bg[2], int(round(bg[3] * alpha)))
        return palette

    def accent_color(self) -> QColor:
        return QColor(ACCENTS.get(self.settings.accent, ACCENTS["blue"]))

    # ------------------------------------------------------------ 组段

    def _now_text(self) -> str:
        if self.settings.info_mode == "custom":
            return self.settings.custom_text.strip()[:80]
        return time.strftime("%H:%M")

    def _primary_segment(self) -> layout._InfoSeg:
        text = self._now_text()
        box = TIME_BOX_SAMPLE
        elide = 0
        if self.settings.info_mode == "custom":
            box = text or "88:88"
            elide = 96
        return layout._InfoSeg(
            kind=layout.KIND_PRIMARY,
            seg_id="primary",
            label="",
            text=text or "--:--",
            box_text=box,
            state=isl.STATE_OK,
            elide_px=elide,
        )

    def _percent_segment(self, metric_id: str) -> layout._InfoSeg:
        sample = self.sys_monitor.snapshot()
        label = layout._DEVICE_LABELS.get(metric_id, metric_id)
        value = sample.cpu_percent if metric_id == isl.CPU else sample.mem_percent
        if sample.error and value is None:
            return layout._InfoSeg(
                kind=layout.KIND_METRIC,
                seg_id=metric_id,
                label=label,
                text=sysmon.UNKNOWN_TEXT,
                box_text=sysmon.MAX_TEXT.rstrip("%"),
                state=isl.STATE_ERROR,
                unit=isl.PERCENT_UNIT,
                detail={"error_reason": sample.error},
            )
        state = isl.STATE_OK if value is not None else isl.STATE_SAMPLING
        rendered = sysmon.format_cpu(value) if metric_id == isl.CPU else sysmon.format_mem(value)
        number, unit = isl.split_value_unit(rendered, isl.PERCENT_UNIT)
        self._alert[metric_id] = isl.alert_severity(
            metric_id, value, self._alert.get(metric_id, "")
        )
        return layout._InfoSeg(
            kind=layout.KIND_METRIC,
            seg_id=metric_id,
            label=label,
            text=number,
            box_text=sysmon.MAX_TEXT.rstrip("%"),
            state=state,
            unit=unit if unit else isl.PERCENT_UNIT,
            severity=self._alert[metric_id],
        )

    def _network_segment(self) -> layout._InfoSeg:
        sample = self.net_monitor.snapshot()
        state = isl.STATE_OK if sample is not None else isl.STATE_SAMPLING
        text = sample.text if sample is not None else ""
        return layout._InfoSeg(
            kind=layout.KIND_METRIC,
            seg_id=isl.NETWORK,
            label="",
            text=text or "",
            box_text=netmon.NETWORK_BOX_SAMPLE,
            state=state,
        )

    def _metric_segments(self) -> tuple:
        row = []
        for metric_id in self.settings.metrics:
            if metric_id == isl.CPU or metric_id == isl.MEM:
                row.append(self._percent_segment(metric_id))
            elif metric_id == isl.NETWORK:
                row.append(self._network_segment())
            # 未知 id / 本批未实现的 gpu、fps：不占位（与 unsupported 同口径）
        return tuple(row)

    def _lead_trail(self, name_text: str) -> tuple[float, float]:
        lead = CONTENT_PAD
        if self.settings.show_icon:
            lead += ICON_PX + ICON_GAP
        trail = CONTENT_PAD
        if self.settings.show_status:
            trail = STATUS_GAP + STATUS_DOT + STATUS_GAP
        return float(lead), float(trail)

    def _name_text(self) -> str:
        if not self.settings.show_name:
            return ""
        return str(self.settings.character_name or "").strip()

    def _rebuild_row(self) -> None:
        self._row = (self._primary_segment(),) + self._metric_segments()

    def _available_width(self) -> int:
        screen = self._screen()
        if screen is None:
            return 0
        return max(0, screen.availableGeometry().width() - 2 * EDGE_MARGIN)

    def _screen(self):
        from PySide6.QtGui import QGuiApplication

        handle = self.windowHandle()
        screen = handle.screen() if handle is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen

    def _compute_plan(self, available_w: int | None = None) -> layout.ShrinkPlan:
        lead, trail = self._lead_trail(self._name_text())
        return layout.plan_info_row(
            self._row,
            lead_w=lead,
            trail_w=trail,
            name_text=self._name_text(),
            available_w=self._available_width() if available_w is None else int(available_w),
            primary_fm=self._fm("primary"),
            value_fm=self._fm("value"),
            label_fm=self._fm("label"),
            name_fm=self._fm("name"),
        )

    def _width_key_now(self) -> tuple:
        return (
            self._font_key(),
            self.settings.show_icon,
            self.settings.show_name,
            self.settings.show_status,
            self.settings.info_mode,
            self.settings.metrics,
            self._name_text(),
            self._available_width() // 4,  # 屏宽变化到 4px 粒度才重排
        )

    def _update_size(self) -> None:
        key = self._width_key_now()
        self._plan = self._compute_plan(self._card_budget() if self._expanded else None)
        self._width_key = key
        if self._expanded:
            self._apply_card_size()
        else:
            self.setFixedSize(QSize(max(MIN_CAPSULE_WIDTH, self._plan.width), CAPSULE_HEIGHT))
        self._sync_sampling()

    def _tick(self) -> None:
        self._ticks += 1
        previous_key = self._width_key
        self._rebuild_row()
        self._plan = self._compute_plan(self._card_budget() if self._expanded else None)
        if self._width_key_now() != previous_key:
            self._update_size()
        elif self._expanded:
            self._rebuild_card()
        else:
            self.update()
        self._sync_sampling()

    # ------------------------------------------------------------ 位置

    def _apply_position(self, *, initial: bool = False) -> None:
        screen = self._screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        saved_x = self._config_int("island_x")
        saved_y = self._config_int("island_y")
        if saved_x is not None and saved_y is not None:
            x, y = saved_x, saved_y
        else:
            x = area.x() + area.width() - self.width() - EDGE_MARGIN
            y = area.y() + EDGE_MARGIN
        self.move(self._clamp_point(x, y, area))
        if initial:
            self.update()

    @staticmethod
    def _clamp_point(x: int, y: int, area) -> QPoint:
        x = max(area.x(), min(area.x() + area.width() - 1, int(x)))
        y = max(area.y(), min(area.y() + area.height() - 1, int(y)))
        return QPoint(x, y)

    def _clamp_to_screen(self) -> None:
        screen = self._screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = max(area.x(), min(area.x() + area.width() - self.width(), self.x()))
        y = max(area.y(), min(area.y() + area.height() - self.height(), self.y()))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _config_int(self, key: str) -> int | None:
        try:
            value = self.config.get(key, None)
        except Exception:  # noqa: BLE001
            return None
        if value is None:
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    def _save_position(self) -> None:
        for key, value in (("island_x", self.x()), ("island_y", self.y())):
            try:
                self.config.set(key, int(value))
            except Exception:  # noqa: BLE001 - 位置保存失败不该影响岛
                pass
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 卡片

    def _card_width(self) -> int:
        capsule = self._plan.width if self._plan is not None else MIN_CAPSULE_WIDTH
        return max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, max(capsule, CARD_MIN_WIDTH)))

    def _card_budget(self) -> int:
        """展开态里内容行的可用宽：卡片宽减去左右内缩。

        卡片比胶囊窄时（胶囊本来很宽、卡片被 420 上限钳住），行必须按**卡片宽**
        重排——否则内容会画到窗外被裁掉。放开时由 `_update_size()` 恢复屏宽预算。
        """
        return max(0, self._card_width() - 2 * CAPSULE_INSET - 2 * CONTENT_PAD)

    def _apply_card_size(self) -> None:
        width = self._card_width()
        self.card.setFixedWidth(width - 2 * CAPSULE_INSET)
        self.card.adjustSize()
        height = CAPSULE_HEIGHT + self.card.sizeHint().height() + 2 * CAPSULE_INSET
        self.setFixedSize(QSize(width, height))

    def _rebuild_card(self) -> None:
        palette = self._palette()
        self.card.set_colors(
            text=palette["text"],
            muted=palette["muted"],
            accent=self.accent_color().name(),
        )
        self.card.setWidth_and_rows(self._card_width() - 2 * CAPSULE_INSET, self._card_rows())
        self._apply_card_size()

    def _card_rows(self) -> list[tuple[str, str, str, str]]:
        """卡片 B 区：每段一行 ``(段名, 值, 详情, 告警级)``。"""
        rows: list[tuple[str, str, str, str]] = []
        for seg in self._row:
            if seg.kind == layout.KIND_PRIMARY:
                continue
            name = seg.label or CARD_NAMES.get(seg.seg_id, seg.seg_id)
            if seg.state == isl.STATE_ERROR:
                reason = str(seg.detail.get("error_reason") or "读不到读数")
                rows.append((name, "--", reason, isl.ALERT_CRIT))
                continue
            value = f"{seg.text}{seg.unit}" if seg.state == isl.STATE_OK else "--"
            detail = "采样中" if seg.state == isl.STATE_SAMPLING else ""
            rows.append((name, value, detail, seg.severity))
        if not rows:
            rows.append(("提示", "没有启用的指标", "设置 → 外观与交互 → 灵动岛", ""))
        return rows

    def expand_card(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self._plan = self._compute_plan(self._card_budget())
        self._rebuild_card()
        self._sync_sampling()
        self.card.show()
        self.card.move(CAPSULE_INSET, CAPSULE_HEIGHT)
        self._card_timer.start()
        self.card_expanded.emit(True)
        self.update()

    def collapse_card(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self._card_timer.stop()
        self.card.hide()
        self._update_size()
        self.card_expanded.emit(False)
        self.update()

    def is_expanded(self) -> bool:
        return self._expanded

    def plan(self) -> layout.ShrinkPlan | None:
        return self._plan

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_global = event.globalPosition().toPoint()
        self._drag_offset = self._press_global - self.pos()
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press_global is None or self._drag_offset is None:
            return
        point = event.globalPosition().toPoint()
        if not self._dragging:
            distance = (point - self._press_global).manhattanLength()
            if distance < self.startDragDistance():
                return
            self._dragging = True
        if self._expanded:
            # 拖动即收起：展开态窗口更宽，跟着手走会把卡片拖出屏幕。
            self.collapse_card()
        self.move(point - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        dragged = self._dragging
        self._press_global = None
        self._drag_offset = None
        self._dragging = False
        if dragged:
            self._clamp_to_screen()
            self._save_position()
            event.accept()
            return
        if self.settings.click_action == "toggle_pet":
            self.clicked.emit()
            return
        if self._expanded:
            self.collapse_card()
        else:
            self.expand_card()
        event.accept()

    def enterEvent(self, event) -> None:
        if self._expanded:
            self._card_timer.stop()  # 悬停时别自动收起
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._expanded:
            self._card_timer.start()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()
        self._raise_topmost()

    def _raise_topmost(self) -> None:
        self.raise_()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fonts.clear()
            self._metrics.clear()
            self._font_key_cache = None
            isl.clear_width_cache()
            self._update_size()

    # ------------------------------------------------------------ 绘制

    def capsule_rect(self) -> QRectF:
        return QRectF(
            CAPSULE_INSET,
            CAPSULE_INSET,
            max(1.0, self.width() - 2 * CAPSULE_INSET),
            CAPSULE_HEIGHT - 2 * CAPSULE_INSET,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self._palette()
        if self._expanded:
            # 展开态是一整块圆角面板：胶囊顶条与卡片底板连成一片，不再画第二层胶囊。
            rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
            radius = 18.0
        else:
            rect = self.capsule_rect()
            radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        background = QColor(*palette["bg"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawPath(path)

        keyline = QColor(*palette["keyline"])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(keyline, 1.0))
        painter.drawPath(path)

        if self._plan is None:
            return
        self._paint_content(painter, palette)

    def _paint_content(self, painter: QPainter, palette) -> None:
        plan = self._plan
        if plan is None:
            return
        baseline = CAPSULE_HEIGHT / 2.0 + BASELINE_DY
        x = CAPSULE_INSET + CONTENT_PAD
        if self.settings.show_icon:
            ring = self.accent_color()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ring)
            painter.drawEllipse(QRectF(x, CAPSULE_HEIGHT / 2.0 - ICON_PX / 2.0, ICON_PX, ICON_PX))
            painter.setBrush(QColor(28, 30, 38, 200))
            painter.drawEllipse(
                QRectF(x + 4, CAPSULE_HEIGHT / 2.0 - ICON_PX / 2.0 + 4, ICON_PX - 8, ICON_PX - 8)
            )
            x += ICON_PX + ICON_GAP
        if plan.name:
            painter.setFont(self._font("name"))
            painter.setPen(QColor(*palette["muted"]))
            painter.drawText(QPoint(int(x), int(baseline)), plan.name)
            x += plan.name_w + NAME_GAP

        placements = layout.place_info_segments(
            layout.apply_shrink(plan, self._row, primary_fm=self._fm("primary")),
            start_x=x,
            primary_fm=self._fm("primary"),
            value_fm=self._fm("value"),
            label_fm=self._fm("label"),
        )
        text_color = QColor(*palette["text"])
        muted = QColor(*palette["muted"])
        divider = QColor(*palette["divider"])
        for placement in placements:
            seg = placement.seg
            if placement.divider_x is not None:
                painter.setPen(QPen(divider, 1.0))
                painter.drawLine(
                    int(placement.divider_x),
                    int(baseline - 7),
                    int(placement.divider_x),
                    int(baseline + 7),
                )
            if placement.label_w:
                painter.setFont(self._font("label"))
                painter.setPen(muted)
                painter.drawText(QPoint(int(placement.label_x), int(baseline)), seg.label)
            if seg.kind == layout.KIND_CHIP:
                painter.setFont(self._font("label"))
                painter.setPen(QPen(divider, 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    QRectF(placement.box_x, CAPSULE_HEIGHT / 2.0 - 9, placement.box_w, 18),
                    9,
                    9,
                )
                if placement.alert_dot_x is not None:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(ALERT_COLORS.get(seg.severity, ALERT_COLORS["crit"])))
                    painter.drawEllipse(
                        QRectF(placement.alert_dot_x, CAPSULE_HEIGHT / 2.0 - 2, 4, 4)
                    )
                painter.setPen(muted)
                painter.drawText(QPoint(int(placement.text_x), int(baseline)), placement.text)
                continue
            color = text_color
            if seg.kind == layout.KIND_METRIC and seg.state == isl.STATE_OK and seg.severity:
                color = QColor(ALERT_COLORS.get(seg.severity, ALERT_COLORS["warn"]))
            elif seg.state != isl.STATE_OK:
                color = muted
            painter.setFont(
                self._font("primary") if seg.kind == layout.KIND_PRIMARY else self._font("value")
            )
            painter.setPen(color)
            painter.drawText(QPoint(int(placement.text_x), int(baseline)), placement.text)
            if placement.unit_x is not None and placement.unit_text:
                painter.setFont(self._font("label"))
                painter.setPen(color if seg.state == isl.STATE_OK else muted)
                painter.drawText(
                    QPoint(int(placement.unit_x), int(baseline)), placement.unit_text
                )

        if self.settings.show_status:
            severity = isl.highest_severity(
                placement.seg.severity for placement in placements
            )
            dot = QColor(ALERT_COLORS.get(severity, ACCENTS.get(self.settings.accent, "#40b8ff")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            # 状态点落在行计划预留的 trail 槽里（end + STATUS_GAP），
            # 不能按「窗口右边 - 内缩」反推——那会比内容右缘多退一个间距，压到末段上。
            _, trail = self._lead_trail(plan.name)
            dot_x = self.width() - trail + STATUS_GAP
            painter.drawEllipse(
                QRectF(
                    dot_x,
                    CAPSULE_HEIGHT / 2.0 - STATUS_DOT / 2.0,
                    STATUS_DOT,
                    STATUS_DOT,
                )
            )


class _IslandCard(QWidget):
    """展开卡片：每段一行（段名 / 值 · 详情），底部一行操作提示。

    卡片自己只排字，背景与圆角由父窗口的 ``paintEvent`` 画（同一块面板），
    这样胶囊与卡片之间不会有接缝。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("islandCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 6, 14, 12)
        self._layout.setSpacing(7)
        self._rows: list[tuple[QLabel, QLabel]] = []
        self._hint = QLabel("点胶囊收起 · 拖动换位置", self)
        self._hint.setObjectName("islandCardHint")
        self._layout.addWidget(self._hint)
        self._text_color = "rgb(235, 238, 245)"
        self._muted_color = "rgb(160, 170, 190)"
        self._accent_color = "#40b8ff"

    def set_colors(self, *, text, muted, accent: str) -> None:
        self._text_color = "rgb({}, {}, {})".format(*text[:3])
        self._muted_color = "rgb({}, {}, {})".format(*muted[:3])
        self._accent_color = accent
        self._hint.setStyleSheet(
            f"color: {self._muted_color}; font-size: 11px; background: transparent;"
        )

    def setWidth_and_rows(self, width: int, rows: list[tuple[str, str, str, str]]) -> None:
        while len(self._rows) < len(rows):
            container = QWidget(self)
            container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            line = QVBoxLayout(container)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(1)
            name = QLabel("", container)
            name.setObjectName("islandCardRow")
            value = QLabel("", container)
            value.setObjectName("islandCardValue")
            value.setWordWrap(False)
            line.addWidget(name)
            line.addWidget(value)
            self._layout.insertWidget(max(0, self._layout.count() - 1), container)
            self._rows.append((name, value))
        for index, (name_label, value_label) in enumerate(self._rows):
            container = name_label.parentWidget()
            if index >= len(rows):
                container.hide()
                continue
            name, value, detail, severity = rows[index]
            name_label.setText(name)
            name_label.setStyleSheet(
                f"color: {self._muted_color}; font-size: 11px; background: transparent;"
            )
            value_label.setText(f"{value} · {detail}" if detail else value)
            alert = ALERT_COLORS.get(severity, "")
            color = alert or self._text_color
            value_label.setStyleSheet(
                f"color: {color}; font-size: 13px; background: transparent;"
            )
            container.show()
        self.setFixedWidth(max(120, int(width)))
        self.adjustSize()


__all__ = [
    "CARD_NAMES",
    "DynamicIsland",
    "IslandConfig",
    "CAPSULE_HEIGHT",
    "CARD_AUTO_COLLAPSE_MS",
    "ACCENTS",
    "STYLE_PALETTES",
]

