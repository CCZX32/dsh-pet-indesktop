"""拖文件解读的纯逻辑：后缀过滤、扫描预算、有界读取、提示词组装。

从主分支 `pet/file_interpret.py` 的纯函数搬来，去掉 Qt 与确认弹窗：本 mod 只负责
「读文本 + 交给 AI」，投喂动画和统计仍归 Core 的 `FeedingController`。
绝不修改、移动或删除被拖入的文件。
"""

from __future__ import annotations

import time
from pathlib import Path

TEXT_EXTENSIONS = frozenset(
    {
        ".txt", ".md", ".markdown", ".json", ".csv", ".log", ".yaml", ".yml",
        ".xml", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".sql",
        ".sh", ".bat", ".ps1", ".ini", ".toml", ".cfg", ".conf",
        ".java", ".c", ".h", ".cpp", ".go", ".rs", ".rb", ".rst",
    }
)

#: 单次解读的文本字符预算（与主分支聊天附件同源口径）。
MAX_TEXT_CHARS = 200_000
#: 扫描预算：最多看 20000 个候选、最多花 2 秒墙钟。
SCAN_FILE_LIMIT = 20_000
SCAN_TIME_BUDGET_S = 2.0

INSTRUCTION = (
    "请解读以上文件内容：先用两三句话概括它是什么、讲什么，再列出关键信息点；"
    "如果内容读不懂或像乱码，就直说。"
)

BUDGET_EXHAUSTED_HINT = "拖进来的文件太多，一次看不过来，少拖几个再试～"
NO_TEXT_HINT = "这些文件里没有能直接读的文本（只支持文本/代码/配置类），换几个试试？"
NO_SERVICE_HINT = "还没配置 AI 服务：设置 → API 与账户"


class ScanBudget:
    """扫描预算：每个真正探盘的候选记一次账（逐项查钟 + 文件数上限）。"""

    def __init__(self, *, limit: int = SCAN_FILE_LIMIT, seconds: float = SCAN_TIME_BUDGET_S, clock=time.monotonic) -> None:
        self.limit = int(limit)
        self.deadline = clock() + float(seconds)
        self._clock = clock
        self.used = 0
        self.truncated = False

    def account(self) -> bool:
        if self.truncated:
            return False
        if self.used >= self.limit or self._clock() >= self.deadline:
            self.truncated = True
            return False
        self.used += 1
        return True


def is_interpretable_file(path) -> bool:
    try:
        return Path(path).suffix.lower() in TEXT_EXTENSIONS
    except (TypeError, ValueError):
        return False


def collect_interpretable(paths, budget: ScanBudget | None = None) -> list[Path]:
    """过滤可解读的本地文件：去重、剔目录/不存在、在扫描预算内。

    后缀不符或重复的候选不记账（它们不产生 syscall），否则一堆 `.bin` 会把
    文本文件的额度吃光。
    """
    budget = budget or ScanBudget()
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths or ():
        try:
            path = Path(str(raw))
        except (TypeError, ValueError):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not is_interpretable_file(path):
            continue
        if not budget.account():
            break
        if path.is_file():
            result.append(path)
    return result


def extract_text(paths, max_chars: int = MAX_TEXT_CHARS) -> tuple[str, list[str]]:
    """顺序读取文本，共享字符预算；返回 ``(拼装内容, 被跳过的文件名)``。

    每个文件只读剩余预算的字符数，绝不整文件读入（几百 MB 的日志会把线程卡死）。
    """
    remaining = max(0, int(max_chars))
    parts: list[str] = []
    skipped: list[str] = []
    for path in paths:
        if remaining <= 0:
            skipped.append(path.name)
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(remaining)
                truncated = bool(fh.read(1))
        except OSError:
            skipped.append(path.name)
            continue
        if truncated:
            text += "\n…（已截断，超出单次解读预算）"
            remaining = 0
        else:
            remaining -= len(text)
        parts.append(f"【文件：{path.name}】\n```\n{text}\n```")
    return "\n\n".join(parts), skipped


def build_user_text(content: str, names, skipped=(), *, budget_truncated: bool = False) -> str:
    lines = [f"本次拖入的文件：{'、'.join(names) or '（无）'}"]
    if skipped:
        lines.append(f"以下文件超出预算，本次未读取：{'、'.join(skipped)}")
    if budget_truncated:
        lines.append("文件太多，只扫描了前一部分。")
    lines.append("")
    lines.append(content)
    lines.append("")
    lines.append(INSTRUCTION)
    return "\n".join(lines)


def summarize(text: str, *, limit: int = 180) -> str:
    """气泡摘要：压成单行、截断，留出气泡可读长度。"""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"
