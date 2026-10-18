# -*- coding: utf-8 -*-
"""报时调度与台词选择（纯标准库，可在无 GUI 环境导入）。"""

from __future__ import annotations

from datetime import datetime, timedelta

SCHEDULE_KEYS = ("hourly", "every_30", "every_15", "every_5", "every_minute", "custom")
SCHEDULE_LABELS = {
    "hourly": "整点报时",
    "every_30": "每 30 分钟",
    "every_15": "每 15 分钟",
    "every_5": "每 5 分钟",
    "every_minute": "每分钟",
    "custom": "自定义时间点",
}
_INTERVALS = {"hourly": 60, "every_30": 30, "every_15": 15, "every_5": 5, "every_minute": 1}

DEFAULT_QUOTES_ZH = (
    "时间不早了，记得喝口水。",
    "这一小时辛苦了，伸个懒腰吧。",
    "专注很好，也别忘了休息。",
    "现在这一刻，先照顾好自己。",
    "慢慢来，事情一件一件做。",
)
DEFAULT_QUOTES_EN = ("Take a short break.", "One thing at a time.")


def clean_schedule(value) -> str:
    return value if isinstance(value, str) and value in SCHEDULE_KEYS else "hourly"


def parse_custom_times(value) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value:
        if not isinstance(item, str) or ":" not in item:
            continue
        hour, _, minute = item.partition(":")
        try:
            h, m = int(hour), int(minute)
        except ValueError:
            continue
        if 0 <= h <= 23 and 0 <= m <= 59:
            result.append((h, m))
    return tuple(sorted(set(result)))


def _next_interval(now: datetime, interval: int) -> datetime:
    base = now.replace(second=0, microsecond=0)
    for offset in range(1, 1441):
        candidate = base + timedelta(minutes=offset)
        if (candidate.hour * 60 + candidate.minute) % interval == 0:
            return candidate
    return base + timedelta(minutes=interval)


def _next_custom(now: datetime, times: tuple[tuple[int, int], ...]) -> datetime:
    for day in (0, 1):
        date = (now + timedelta(days=day)).date()
        for hour, minute in times:
            candidate = datetime(date.year, date.month, date.day, hour, minute)
            if candidate > now:
                return candidate
    return now + timedelta(days=1)


def seconds_until_next(now: datetime, schedule, custom_times) -> float:
    schedule = clean_schedule(schedule)
    if schedule == "custom":
        times = parse_custom_times(custom_times)
        if not times:
            # 自定义时间点为空时按整点兜底，而不是每分钟乱报。
            return seconds_until_next(now, "hourly", ())
        candidate = _next_custom(now, times)
    else:
        candidate = _next_interval(now, _INTERVALS[schedule])
    return max(1.0, (candidate - now).total_seconds())


def clock_sentence(now: datetime) -> str:
    return f"现在是 {now.hour} 点 {now.minute:02d} 分。"


def _lines(value, defaults) -> tuple[str, ...]:
    if isinstance(value, str):
        items = tuple(line.strip() for line in value.splitlines() if line.strip())
    elif isinstance(value, (list, tuple)):
        items = tuple(str(line).strip() for line in value if str(line).strip())
    else:
        items = ()
    return items or tuple(defaults)


def pick_quote(now: datetime, custom_zh, custom_en) -> str:
    zh = _lines(custom_zh, DEFAULT_QUOTES_ZH)
    en = _lines(custom_en, DEFAULT_QUOTES_EN)
    pool = zh + en
    index = (now.toordinal() * 24 * 60 + now.hour * 60 + now.minute) % len(pool)
    return pool[index]
