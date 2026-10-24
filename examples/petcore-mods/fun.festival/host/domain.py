"""Cached calendar hits plus local birthday; no runtime/IO/Qt."""
from datetime import date
from functools import lru_cache
from . import festival as F


def clean_birthday(value):
    text = str(value or "").strip()
    try:
        day = date.fromisoformat("2000-" + text)
        return text if day.strftime("%m-%d") == text else ""
    except ValueError:
        return ""


def config(source):
    result = F.normalize_festival_config(source)
    result["birthday"] = clean_birthday(source.get("festival_birthday", ""))
    return result


@lru_cache(maxsize=64)
def _hits(day, cn, solar_terms, west):
    return F.festivals_on(day, {"cn": cn, "solar_terms": solar_terms, "west": west})


def hits(day, cfg):
    return _hits(day, cfg["cn"], cfg["solar_terms"], cfg["west"])


def birthday_on(day, cfg):
    return bool(cfg.get("birthday") and day.strftime("%m-%d") == cfg["birthday"])


def has_event(day, cfg):
    return birthday_on(day, cfg) or bool(hits(day, cfg))


def text(day, cfg, index=0):
    parts = []
    found = hits(day, cfg)
    if found:
        sentence = "今天是" + "、".join(f.name for f in found) + "。"
        if cfg["show_quote"]:
            sentence += F.pick_quote(found[0], day, index, cfg)
        parts.append(sentence)
    if birthday_on(day, cfg):
        parts.append("生日快乐！愿你今天和每一天都平安、自在。")
    return "".join(parts)
