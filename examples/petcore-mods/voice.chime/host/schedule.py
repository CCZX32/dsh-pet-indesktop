"""报时调度：纯时间算术 + 按日期确定性的台词轮换。

运行时线程、网络与音频都不在这里：本模块只回答「此刻该不该报、这次报时的
槽位键是什么、下一次什么时候、今天该念哪句」。

槽位键 ``YYYY-MM-DDTHH:MM#模式`` 是幂等的唯一凭据：同一分钟里 20-30 秒一次的
tick 只会消费一次（``is_due`` 与调用方保存的 ``last_fired_key`` 比对）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

#: 调度模式（设置页下拉的 data 与此一一对应）。
SCHEDULES = (
    "hourly",
    "every_30",
    "every_15",
    "every_5",
    "every_minute",
    "custom",
)
SCHEDULE_LABELS = {
    "hourly": "整点报时",
    "every_30": "每 30 分钟",
    "every_15": "每 15 分钟",
    "every_5": "每 5 分钟",
    "every_minute": "每分钟",
    "custom": "自定义时间点",
}
#: 固定步长的分钟数（不在表里的模式走自定义时间点或每分钟）。
STEPS = {"hourly": 60, "every_30": 30, "every_15": 15, "every_5": 5}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_SEPARATORS_RE = re.compile(r"[,，;；\s]+")

#: 洗牌用的 64 位线性同余参数（Knuth/MMIX）。刻意自带而不 import random：
#: 同一日期在任何解释器版本、任何进程上都洗出同一个排列。
_SHUFFLE_MASK = (1 << 64) - 1
_SHUFFLE_MUL = 6364136223846793005
_SHUFFLE_ADD = 1442695040888963407
_SHUFFLE_SALT = 0x9E3779B97F4A7C15


def normalize_schedule(value) -> str:
    """清洗调度模式；非法值回落整点（配置被手改成脏值也不抛异常）。"""
    text = str(value or "").strip().lower()
    return text if text in SCHEDULES else "hourly"


def parse_times(value) -> tuple[str, ...]:
    """清洗自定义时间点：逗号/分号/空白分隔的 ``HH:MM``，非法项丢弃并排序去重。

    接受字符串（设置页输入框）或序列（配置里的 ``list[str]``）。
    """
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set)):
        parts = [str(item) for item in value]
    else:
        parts = _SEPARATORS_RE.split(str(value))
    times: set[str] = set()
    for part in parts:
        match = _TIME_RE.match(part.strip())
        if match:
            times.add(f"{int(match.group(1)):02d}:{match.group(2)}")
    return tuple(sorted(times))


def _matches(now: datetime, schedule: str, times: tuple[str, ...]) -> bool:
    if schedule == "custom":
        return f"{now.hour:02d}:{now.minute:02d}" in times
    if schedule == "every_minute":
        return True
    step = STEPS.get(schedule)
    return bool(step) and now.minute % step == 0


def slot_for(now: datetime, schedule: str, times=()) -> str:
    """当前分钟命中时报时槽位键，否则空串。"""
    schedule = normalize_schedule(schedule)
    if not _matches(now, schedule, parse_times(times)):
        return ""
    return f"{now.strftime('%Y-%m-%dT%H:%M')}#{schedule}"


def is_due(now: datetime, schedule: str, times=(), last_fired_key: str = "") -> str:
    """该不该报：返回待消费的槽位键，已报过或未命中返回空串。

    调用方把返回值存成 ``last_fired_key``；同一槽位因此只会消费一次，
    而 20-30 秒一次的 tick 不会把一分钟报两遍。
    """
    slot = slot_for(now, schedule, times)
    if not slot or slot == str(last_fired_key or ""):
        return ""
    return slot


def next_due(now: datetime, schedule: str, times=()) -> datetime | None:
    """下一次报时时刻（严格晚于 ``now``）；自定义时间为空时返回 ``None``。"""
    schedule = normalize_schedule(schedule)
    moment = now.replace(second=0, microsecond=0)
    if schedule == "custom":
        parsed = parse_times(times)
        if not parsed:
            return None
        for hhmm in parsed:
            hour, minute = (int(part) for part in hhmm.split(":"))
            candidate = moment.replace(hour=hour, minute=minute)
            if candidate > now:
                return candidate
        hour, minute = (int(part) for part in parsed[0].split(":"))
        return (moment + timedelta(days=1)).replace(hour=hour, minute=minute)
    step = STEPS.get(schedule, 1)
    for offset in range(1, 61):
        candidate = moment + timedelta(minutes=offset)
        if candidate.minute % step == 0:
            return candidate
    return None


def seconds_until_due(now: datetime, schedule: str, times=()) -> float | None:
    """距下一报时点的秒数；没有下一报时点时返回 ``None``。"""
    target = next_due(now, schedule, times)
    if target is None:
        return None
    return max(0.0, (target - now).total_seconds())


def slot_index_in_day(now: datetime, schedule: str, times=()) -> int:
    """当天第几次报时（0 起，含当前这一次），台词轮换的日内游标。

    直接算术求解（旧实现逐分钟回溯）；自定义时间点按「已过的时间点个数 - 1」，
    未命中时也不返回负数。
    """
    schedule = normalize_schedule(schedule)
    if schedule == "custom":
        hhmm = f"{now.hour:02d}:{now.minute:02d}"
        passed = sum(1 for item in parse_times(times) if item <= hhmm)
        return max(passed - 1, 0)
    step = STEPS.get(schedule)
    if not step:  # every_minute
        return now.hour * 60 + now.minute
    return now.hour * (60 // step) + now.minute // step


def quote_day_order(pool, day_ordinal: int) -> tuple[str, ...]:
    """把台词库按日期洗成当天的固定排列（Fisher–Yates，确定性）。

    同一天内任意时刻得到同一个排列；换一天整批顺序都不同，所以「每天同一时刻
    永远是同一句」不会发生。高标准位取模（``>> 33``）避免 LCG 低位周期短。
    """
    items = list(pool)
    state = (int(day_ordinal) * _SHUFFLE_MUL + _SHUFFLE_SALT) & _SHUFFLE_MASK
    for index in range(len(items) - 1, 0, -1):
        state = (state * _SHUFFLE_MUL + _SHUFFLE_ADD) & _SHUFFLE_MASK
        swap = (state >> 33) % (index + 1)
        items[index], items[swap] = items[swap], items[index]
    return tuple(items)


def pick_quote(pool, now: datetime, schedule: str, times=()) -> str:
    """当天第 N 次报时对应的台词（顺序取用、用尽回环）；库为空返回空串。"""
    if not pool:
        return ""
    order = quote_day_order(pool, now.date().toordinal())
    return order[slot_index_in_day(now, schedule, times) % len(order)]
