"""多行台词/列表类设置的统一解析：一行一条，兼容旧的 `a | b` 单行写法。"""

from __future__ import annotations

LINE_SEPARATOR = "|"
FULL_WIDTH_SEPARATOR = "｜"


def parse_lines(text: str) -> list[str]:
    """按行切分，顺带拆开行内的 `|` / `｜`，丢掉空白项。"""
    items: list[str] = []
    normalized = str(text or "").replace(FULL_WIDTH_SEPARATOR, LINE_SEPARATOR)
    for raw in normalized.splitlines():
        for part in raw.split(LINE_SEPARATOR):
            value = part.strip()
            if value:
                items.append(value)
    return items


def format_lines(items) -> str:
    return "\n".join(str(item).strip() for item in (items or ()) if str(item).strip())
