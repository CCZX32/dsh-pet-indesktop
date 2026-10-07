# -*- coding: utf-8 -*-
"""灵动岛「段」的契约层：注册表 + 宽度自测量 + 字段盒 + 四态兜底（零 Qt）。

段是胶囊上的一个信息单元（``CPU 24%``、``↓ 1.2M``），本模块只管**契约**，
不画一个像素：注册接口给第三方段用，其余是布局层的硬护栏。

三条设计取舍：

- **盒宽自测量，不写死 px**。段声明最坏宽度样本（``max_text``，如 ``"888%"``），
  ``horizontalAdvance(label) + 4(有 label 时) + horizontalAdvance(max_text)``
  就是它的声明盒宽，按 ``(id, font_key)`` 缓存。字体/DPI 一变指纹就变，
  自动重测——写死 px 在 HiDPI 与用户改字号时必然错位。
- **运行期截断护栏**：实测 ``text`` 超过声明盒宽时右省略到盒宽并记一条 warning。
  契约第一原则是「任何一段失控不得推歪整岛」——截断 + 日志让违规可见，
  比静默信任格式化器安全（第三方段是常态，不是异常）。
- **四态兜底呈现**：``ok`` 才有真读数；``sampling``/``unknown``/``error`` 一律
  同宽 ``--``（区别只在卡片与颜色，纯逻辑层同文），``unsupported`` 直接不占位。
  ``--`` 与 max_text 同盒宽语义，所以状态切换不改岛宽——不跳。

本模块零 Qt 依赖（度量对象按鸭子类型接收）：跑在后台线程/单测替身上都能用，
真实 QFontMetrics 只在测宽时由调用方传进来。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: 内置段 id（稳定标识：折叠、+N chip、卡片行都按它索引）。GPU 占位在 P3 做。
NETWORK = "network"
CPU = "cpu"
MEM = "mem"

#: 段状态词表（呈现见 :func:`render_compact`）。
STATE_OK = "ok"
STATE_SAMPLING = "sampling"
STATE_UNKNOWN = "unknown"
STATE_ERROR = "error"
STATE_UNSUPPORTED = "unsupported"
STATES = frozenset({STATE_OK, STATE_SAMPLING, STATE_UNKNOWN, STATE_ERROR, STATE_UNSUPPORTED})

#: label 长度上限（11px 标签的排版预算）。
LABEL_MAX_CHARS = 6
#: 标签与字段盒之间的固定间距（px）。绘制层按它排版，宽度公式也含它——
#: 所以 :func:`render_compact` 的 compact 串里**不插空格**（插了就比盒宽多 1 列）。
LABEL_GAP_PX = 4
#: 四种兜底态共用的占位文案（与 max_text 同盒宽语义，不占位异常宽、不伪造 0）。
UNKNOWN_TEXT = "--"
#: 右省略符。用单字符 …（``...`` 会白占两列，盒宽紧张时更早截断）。
ELLIPSIS = "…"
#: 字体指纹的探针串：度量对象不暴露字体（QFontMetrics 没有 ``font()``），
#: 用它量出的宽度 + 一组行度量足以把字号/家族/DPI 变化区分开。
_FONT_PROBE_TEXT = "0123456789"


def _single_line(value: Any, field_name: str) -> str:
    """字段归一化为单行字符串；含换行直接拒注（排版禁令的机器可检部分）。"""
    text = "" if value is None else str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"段契约：{field_name} 必须单行（禁止 \\n / \\r）：{text!r}")
    return text


@dataclass(frozen=True)
class SegmentSnapshot:
    """一段在某一时刻的完整状态（值 + 呈现态 + 卡片行素材）。

    ``id`` 稳定标识（折叠/卡片按它索引）；``label`` ≤6 字符可空（纯 glyph 段，
    如网络段的 ↓↑）；``text`` 当前紧凑文案（单行）；``max_text`` 最坏宽度样本
    （声明盒宽用）；``state`` 见 :data:`STATES`；``detail`` 是卡片 B 区的行素材
    （``unit_full``/``source``/``updated_at``/``error_reason``），本层原样透传。
    """

    id: str
    label: str = ""
    text: str = ""
    max_text: str = ""
    state: str = STATE_OK
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        segment_id = _single_line(self.id, "id")
        if not segment_id:
            raise ValueError("段契约：id 不能为空（它是折叠与卡片的稳定标识）")
        object.__setattr__(self, "id", segment_id)
        label = _single_line(self.label, "label")
        if len(label) > LABEL_MAX_CHARS:
            logger.warning(
                "段 %s 的 label %r 超过 %d 字符，已截断（超长标签会挤掉字段盒）",
                segment_id, label, LABEL_MAX_CHARS,
            )
            label = label[:LABEL_MAX_CHARS]
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "text", _single_line(self.text, "text"))
        object.__setattr__(self, "max_text", _single_line(self.max_text, "max_text"))


class SegmentRegistry:
    """有序段注册表：**列表序 = 用户优先级 = 尾部先被折叠**（收缩 S2/S3 从尾部取）。

    - 重复 id 拒注（同一 id 只有一段，否则折叠/卡片索引会指到两个对象）；
    - 未知 id 查询返回 ``None``（不抛）——配置里残留了没实现的段时，
      调用方按"未注册"处理即可，不该让整条岛炸掉。
    """

    def __init__(self, segments=None):
        self._segments: list[SegmentSnapshot] = []
        self._by_id: dict[str, SegmentSnapshot] = {}
        for segment in segments or ():
            self.register(segment)

    def register(self, segment: SegmentSnapshot) -> SegmentSnapshot:
        if not isinstance(segment, SegmentSnapshot):
            raise TypeError(f"段注册表只接受 SegmentSnapshot，收到 {type(segment).__name__}")
        if segment.id in self._by_id:
            raise ValueError(f"段 id 重复注册：{segment.id!r}（同一 id 只允许一段）")
        self._segments.append(segment)
        self._by_id[segment.id] = segment
        return segment

    def get(self, segment_id) -> SegmentSnapshot | None:
        """按 id 取段；未注册返回 None（不抛）。"""
        return self._by_id.get(segment_id)

    def snapshots(self) -> list[SegmentSnapshot]:
        """当前全部段（注册序的副本：调用方排序不会改到注册表）。"""
        return list(self._segments)

    def __len__(self) -> int:
        return len(self._segments)


# ---------------------------------------------------------------- 宽度自测量
#: 声明盒宽缓存：``(段 id, 字体指纹) -> 宽度``。段数量有界（内置 3 段 +
#: 未来第三方段），字体切换会自然产生新键，无需 LRU；:func:`clear_width_cache`
#: 给测试与"手动失效"用。
_WIDTH_CACHE: dict[tuple[str, Any], int] = {}


def font_metrics_key(font_metrics) -> tuple:
    """度量对象 → 字体指纹（缓存键的一部分）。

    QFontMetrics 不暴露 QFont 对象（无 ``font()``），所以指纹 = 一组行度量 +
    探针串宽度。任一项变化（字号、家族、DPI）都换键 → 盒宽自动重测。
    """
    values = []
    for name in ("height", "lineSpacing", "ascent", "descent", "leading", "averageCharWidth"):
        getter = getattr(font_metrics, name, None)
        try:
            values.append(int(getter()) if callable(getter) else None)
        except Exception:  # pragma: no cover - 度量对象的极端实现
            values.append(None)
    advance = getattr(font_metrics, "horizontalAdvance", None)
    try:
        probe = int(advance(_FONT_PROBE_TEXT)) if callable(advance) else None
    except Exception:  # pragma: no cover
        probe = None
    return tuple(values) + (probe,)


def measure_segment_width(seg: SegmentSnapshot, font_metrics, *, font_key=None) -> int:
    """段的**声明盒宽**（px）：``label 宽 + 4(有 label 时) + max_text 宽``。

    调用方（布局层）在段注册 / 字体变化时问一次即可，结果按 ``(id, font_key)``
    缓存；``font_key`` 显式传入可以跳过指纹计算（已知字体的调用方省一次探测）。

    注意：``max_text`` 是**注册期声明**（最坏样本），缓存按规格只认 ``(id,
    font_key)``——某段运行期改动了自己的最坏样本时，调用方要自己
    :func:`clear_width_cache`，缓存不会替你发现。
    """
    key = (seg.id, font_metrics_key(font_metrics) if font_key is None else font_key)
    cached = _WIDTH_CACHE.get(key)
    if cached is not None:
        return cached
    gap = LABEL_GAP_PX if seg.label else 0
    width = (
        int(font_metrics.horizontalAdvance(seg.label))
        + gap
        + int(font_metrics.horizontalAdvance(seg.max_text))
    )
    _WIDTH_CACHE[key] = width
    return width


def clear_width_cache() -> None:
    """清空盒宽缓存（测试用；字体热切换想强制重测时也可手动调用）。"""
    _WIDTH_CACHE.clear()


# ---------------------------------------------------------------- 字段盒
def format_field_box(text: Any, max_text: Any, font_metrics) -> tuple[str, int]:
    """把当前文案塞进**定宽字段盒**：``(显示文案, 盒宽)``。

    盒宽由 ``max_text``（最坏样本）实测而来，盒内右对齐是布局层的事。实测文案
    不超过盒宽就原样返回；超了就右省略到盒宽并记 warning——这是"任何一段失控
    不得推歪整岛"的硬护栏，宁可截断可见地坏，也不让段挤歪邻居。
    """
    raw = "" if text is None else str(text)
    box_width = int(font_metrics.horizontalAdvance("" if max_text is None else str(max_text)))
    measured = int(font_metrics.horizontalAdvance(raw))
    if measured <= box_width:
        return raw, box_width
    display = _elide_right(raw, box_width, font_metrics)
    logger.warning(
        "字段盒截断：%r 实测 %dpx 超过盒宽 %dpx（最坏样本 %r），已右省略为 %r",
        raw, measured, box_width, max_text, display,
    )
    return display, box_width


def _elide_right(text: str, box_width: int, font_metrics) -> str:
    """右省略到盒宽：二分找"能塞下省略号的最长前缀"。二分而非逐字符回退——
    恶意段可以塞进几万字符，逐字符会退化成 O(n²) 次度量。"""
    if box_width <= 0:
        return ""
    if int(font_metrics.horizontalAdvance(ELLIPSIS)) > box_width:
        return ""  # 连省略号都塞不下：宁可不显示，也不越界
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if int(font_metrics.horizontalAdvance(text[:mid] + ELLIPSIS)) <= box_width:
            low = mid
        else:
            high = mid - 1
    return text[:low] + ELLIPSIS


# ---------------------------------------------------------------- 四态兜底呈现
def render_compact(seg: SegmentSnapshot) -> str | None:
    """胶囊上的紧凑文案；``unsupported`` 段返回 ``None``（调用方跳过、不占位）。

    - ``ok`` → ``label + text``（label 空则是纯 text）。分隔符是绘制层的 4px
      间距（见 :data:`LABEL_GAP_PX`），串里不插空格。
    - ``sampling`` / ``unknown`` / ``error`` → ``label + "--"``：同宽兜底，
      差别（更淡 / 红字 / 原因）由绘制层与卡片层承担。
    - 未识别的 state 一律按 ``unknown`` 兜底：不抛，也不把原始 ``text``
      当读数显示出去。
    """
    if seg.state == STATE_UNSUPPORTED:
        return None
    body = seg.text if seg.state == STATE_OK else UNKNOWN_TEXT
    return f"{seg.label}{body}"
