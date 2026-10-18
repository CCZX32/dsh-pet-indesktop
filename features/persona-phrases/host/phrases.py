# -*- coding: utf-8 -*-
"""台词库与按日期选择（纯标准库）。"""

from __future__ import annotations

from datetime import datetime

DEFAULT_PHRASES = (
    "今天也要好好吃饭。",
    "慢慢来，比较快。",
    "记得看看窗外。",
    "累了就休息一下。",
    "你已经做得不错了。",
    "别忘了喝水。",
    "想做什么就去做吧。",
    "今天也会是好天气。",
)


def lines(value) -> tuple[str, ...]:
    if isinstance(value, str):
        items = tuple(line.strip() for line in value.splitlines() if line.strip())
    elif isinstance(value, (list, tuple)):
        items = tuple(str(line).strip() for line in value if str(line).strip())
    else:
        items = ()
    return items or DEFAULT_PHRASES


def pick_phrase(now: datetime, custom) -> str:
    pool = lines(custom)
    return pool[now.toordinal() % len(pool)]
