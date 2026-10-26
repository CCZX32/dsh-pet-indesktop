"""DeepSeek 峰谷计价提示（零 Qt 纯函数）。

移植自主分支 ``pet/balance.py``（`deepseek_pricing_tier` / `_next_pricing_switch` /
`resolve_tier_labels` / `deepseek_pricing_hint*`），口径与文案逐字一致：

- 北京时间；周六/周日与法定节假日全天空闲；
- 工作日高峰 09:00–12:00、14:00–18:00，其余空闲；
- 「下一档位」按 09/12/14/18 四个边界逐点向后扫 40 天取最早翻转点。

与主分支只有一处差异：**法定节假日由调用方注入** ``holiday_lookup(day) -> str | None``。
petcore 的 core 不带历法后端（节假日表属于 ``fun.festival`` 扩展），core 不能反向依赖
mod；未注入时按「无节假日数据」降级为纯星期规则——与主分支历法覆盖范围之外的降级
口径相同。时区用固定 +08:00（中国 1991 年后无夏令时），顺带免掉 frozen 包里的 tzdata。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Callable

#: 峰谷档位。
TIER_PEAK = "peak"
TIER_IDLE = "idle"

#: 峰谷提示颜色（主分支同值：高峰红 / 空闲绿）。
TIER_PEAK_COLOR = "#e5484d"
TIER_IDLE_COLOR = "#30a46c"

#: 一天内的计价切换时刻：09:00 / 14:00 进入高峰，12:00 / 18:00 离开高峰。
PRICING_BOUNDARIES = (time(9, 0), time(12, 0), time(14, 0), time(18, 0))

#: 切换扫描窗口（天）：法定长假最长 8 天，叠加两端周末约 10 天，40 天留足余量。
PRICING_SCAN_DAYS = 40

#: 文案模式（设置项 ``balance_tier_labels_mode``）。
LABEL_MODES = ("default", "liangwen", "custom")

_BEIJING_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

HolidayLookup = Callable[[date], "str | None"]


def beijing_now(now: datetime | None = None) -> datetime:
    """把入参统一转到北京时间；``None`` 取当前北京时间。"""
    if now is None:
        return datetime.now(_BEIJING_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=_BEIJING_TZ)
    return now.astimezone(_BEIJING_TZ)


def _is_holiday(day: date, holiday_lookup: HolidayLookup | None) -> bool:
    if holiday_lookup is None:
        return False
    try:
        return bool(holiday_lookup(day))
    except Exception:  # noqa: BLE001 - 历法后端坏了不许拖垮提​示
        return False


def pricing_tier(
    now: datetime | None = None, *, holiday_lookup: HolidayLookup | None = None
) -> str:
    """DeepSeek 峰谷计价档位（北京时间）。"""
    bj = beijing_now(now)
    if bj.weekday() >= 5:
        return TIER_IDLE
    if _is_holiday(bj.date(), holiday_lookup):
        return TIER_IDLE
    hour = bj.hour
    return TIER_PEAK if (9 <= hour < 12) or (14 <= hour < 18) else TIER_IDLE


def next_pricing_switch(
    now: datetime | None = None, *, holiday_lookup: HolidayLookup | None = None
) -> tuple[str, datetime]:
    """返回 ``(下一档位, 下一档位开始时间)``，按北京时间计算。

    逐个扫描未来 09:00/12:00/14:00/18:00 边界，取**最早**一个档位与当前不同的时刻。
    这样周末、法定节假日、调休补班后的空档都能被跨越，无需为每种日历情形写分支。
    """
    bj = beijing_now(now)
    tz = bj.tzinfo or _BEIJING_TZ
    current = pricing_tier(bj, holiday_lookup=holiday_lookup)
    day = bj.date()
    for offset in range(PRICING_SCAN_DAYS + 1):
        candidate_day = day + timedelta(days=offset)
        for boundary in PRICING_BOUNDARIES:
            candidate = datetime.combine(candidate_day, boundary, tzinfo=tz)
            if candidate <= bj:
                continue
            tier = pricing_tier(candidate, holiday_lookup=holiday_lookup)
            if tier != current:
                return tier, candidate
    # 扫描窗口内没有翻转：退回次日 09:00（与主分支同一兜底）。
    fallback = datetime.combine(day + timedelta(days=1), time(9, 0), tzinfo=tz)
    return pricing_tier(fallback, holiday_lookup=holiday_lookup), fallback


def format_switch_time(now: datetime, next_time: datetime) -> str:
    """把下一档位切换时间格式化为易读文案。

    当天只显示 ``HH:MM``；跨天显示「明天 HH:MM」；更远的日期按 **ISO 周** 决定措辞：
    同一周内用「周四 HH:MM」，跨周才用「下周四 HH:MM」。
    """
    if next_time.date() == now.date():
        return f"{next_time:%H:%M}"
    days = (next_time.date() - now.date()).days
    if days == 1:
        return f"明天 {next_time:%H:%M}"
    same_week = next_time.date().isocalendar()[:2] == now.date().isocalendar()[:2]
    prefix = "" if same_week else "下"
    return f"{prefix}{_WEEKDAY_CN[next_time.weekday()]} {next_time:%H:%M}"


def resolve_tier_labels(
    mode: str = "default", custom_peak: str = "", custom_idle: str = ""
) -> tuple[str, str]:
    """按设置返回 ``(高峰文本, 空闲文本)``。

    - ``default``：高峰 / 空闲
    - ``liangwen``：梁文峰 / 梁文谷
    - ``custom``：用户自定义，留空回退默认
    """
    mode = str(mode or "default").strip().lower()
    if mode == "liangwen":
        return "梁文峰", "梁文谷"
    if mode == "custom":
        peak = str(custom_peak or "").strip() or "高峰"
        idle = str(custom_idle or "").strip() or "空闲"
        return peak, idle
    return "高峰", "空闲"


def format_hint(
    now: datetime | None = None,
    *,
    peak_label: str | None = None,
    idle_label: str | None = None,
    holiday_lookup: HolidayLookup | None = None,
) -> str:
    """余额气泡下方的纯文本峰谷提示，如「DeepSeek 当前高峰 · 下一空闲 12:00」。"""
    bj = beijing_now(now)
    tier = pricing_tier(bj, holiday_lookup=holiday_lookup)
    next_tier, next_time = next_pricing_switch(bj, holiday_lookup=holiday_lookup)
    peak_text = str(peak_label or "高峰")
    idle_text = str(idle_label or "空闲")
    label = peak_text if tier == TIER_PEAK else idle_text
    next_label = idle_text if next_tier == TIER_IDLE else peak_text
    return f"DeepSeek 当前{label} · 下一{next_label} {format_switch_time(bj, next_time)}"


def format_hint_html(
    now: datetime | None = None,
    *,
    peak_label: str | None = None,
    idle_label: str | None = None,
    peak_color: str = TIER_PEAK_COLOR,
    idle_color: str = TIER_IDLE_COLOR,
    holiday_lookup: HolidayLookup | None = None,
) -> str:
    """带颜色的峰谷提示 HTML（QLabel 可直接渲染）。

    默认高峰红、空闲绿；自定义文案做 HTML 转义，防止破坏富文本。
    """
    bj = beijing_now(now)
    tier = pricing_tier(bj, holiday_lookup=holiday_lookup)
    next_tier, next_time = next_pricing_switch(bj, holiday_lookup=holiday_lookup)
    peak_text = escape(str(peak_label or "高峰"))
    idle_text = escape(str(idle_label or "空闲"))

    def span(text: str, color: str) -> str:
        return f'<span style="color:{color}">{text}</span>'

    label = span(peak_text, peak_color) if tier == TIER_PEAK else span(idle_text, idle_color)
    next_label = (
        span(idle_text, idle_color) if next_tier == TIER_IDLE else span(peak_text, peak_color)
    )
    time_text = format_switch_time(bj, next_time)
    return f"DeepSeek 当前{label} · 下一{next_label} {time_text}"


def subtitle_for(
    config,
    now: datetime | None = None,
    *,
    holiday_lookup: HolidayLookup | None = None,
) -> str:
    """按配置生成气泡副标题：开颜色走 HTML，关颜色走纯文本。"""
    def value(key, default):
        try:
            raw = config.get(key, default)
        except Exception:  # noqa: BLE001 - 配置异常回默认
            return default
        return default if raw is None else raw

    peak, idle = resolve_tier_labels(
        str(value("balance_tier_labels_mode", "default")),
        str(value("balance_tier_label_peak", "") or ""),
        str(value("balance_tier_label_idle", "") or ""),
    )
    if bool(value("balance_tier_color_enabled", True)):
        return format_hint_html(
            now, peak_label=peak, idle_label=idle, holiday_lookup=holiday_lookup
        )
    return format_hint(now, peak_label=peak, idle_label=idle, holiday_lookup=holiday_lookup)


__all__ = [
    "LABEL_MODES",
    "PRICING_BOUNDARIES",
    "PRICING_SCAN_DAYS",
    "TIER_IDLE",
    "TIER_IDLE_COLOR",
    "TIER_PEAK",
    "TIER_PEAK_COLOR",
    "beijing_now",
    "format_hint",
    "format_hint_html",
    "format_switch_time",
    "next_pricing_switch",
    "pricing_tier",
    "resolve_tier_labels",
    "subtitle_for",
]
