"""Pure cleaners ported from the tracked legacy voice_chime implementation."""
import re

_MAX_CUSTOM_QUOTE_LEN = 120
_CUSTOM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

def clean_flag(value, default: bool = True) -> bool:
    """清洗布尔开关：JSON bool 原样返回，字符串按常见真值解析，非法回落默认。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "开", "开启"):
        return True
    if text in ("0", "false", "no", "off", "关", "关闭"):
        return False
    return default

def clean_custom_times(value) -> frozenset[str]:
    """清洗自定义时间点：逗号/空格/分号分隔的 HH:MM，非法项丢弃。"""
    text = str(value or "").strip()
    parts = re.split(r"[,，;；\s]+", text)
    times: set[str] = set()
    for part in parts:
        part = part.strip()
        match = _CUSTOM_RE.match(part)
        if match:
            times.add(f"{int(match.group(1)):02d}:{match.group(2)}")
    return frozenset(times)

def clean_custom_quotes(value) -> tuple[str, ...]:
    """清洗自定义台词/歌词：按行拆分（一行一条），去空行/去重/保序。

    兼容设置页传来的多行字符串（``\\n`` / ``\\r\\n`` / ``\\r``）与已是
    序列的配置值；去除控制字符并按 ``_MAX_CUSTOM_QUOTE_LEN`` 截断单条，
    保证进入 TTS 的文本干净。返回空元组表示“未自定义”，调用方回退内置库。
    """
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set)):
        raw_lines = [str(item) for item in value]
    else:
        raw_lines = re.split(r"\r\n|\r|\n", str(value))
    quotes: list[str] = []
    for line in raw_lines:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", line).strip()
        if not text:
            continue
        text = text[:_MAX_CUSTOM_QUOTE_LEN].strip()
        if text and text not in quotes:
            quotes.append(text)
    return tuple(quotes)
