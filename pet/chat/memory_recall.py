# -*- coding: utf-8 -*-
"""全局记忆 v2a 的检索层：分层常量、关键词、BM25 风格打分、已见去重、注入组装。

纯 Python、零 Qt、零第三方依赖。存储仍由 ``pet/chat/memory.py`` 负责；本模块只
接受 ``entries`` 列表（dict）并做内存计算，方便单测直接钉住打分单调性。

对齐 ``.scratch/memory-v2/SPEC-v2a.md``：
- 四层 ``user/fact/lesson/topic``；缺省/未知层按 ``fact``；
- user 层恒定注入（≤600 字符，按 importance + 新近度截）；
- fact/lesson/topic 按需命中 top-3（≤600 字符），首轮（turn_index<=1）不命中；
- 打分 = 关键词交集 idf 分 × 覆盖率 × 艾宾浩斯衰减 × importance；
- 已见去重：top-3 的前 2 条不排除已见，第 3 条起跳过已见；
- topic 连续 14 天未命中自动归档（归档条目不参与命中）；
- 空命中不注入占位。
"""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

LAYERS = ("user", "fact", "lesson", "topic")
DEFAULT_LAYER = "fact"
LAYER_LABELS = {
    "user": "用户偏好",
    "fact": "事实",
    "lesson": "教训",
    "topic": "话题",
}

HALF_LIFE_DAYS = 14.0
TOPIC_ARCHIVE_DAYS = 14.0
USER_CHAR_LIMIT = 600
RECALL_CHAR_LIMIT = 600
RECALL_TOP_K = 3
MAX_KEYWORDS = 6

_QUERY_KEYWORD_LIMIT = 16
_SECONDS_PER_DAY = 86400.0
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+", re.UNICODE)
_CJK_RE = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
#: 高频虚词不单独成为关键词；只影响单字/整词，不影响含实义字的 bigram。
_STOPWORDS = frozenset(
    "的 了 是 在 我 你 他 她 它 们 这 那 就 也 都 和 与 吗 呢 啊 呀 吧 哦 嗯 不 有".split()
)

_USER_HEADER = (
    "【关于用户的记忆】以下是用户的偏好与习惯，回答时自然参考，不要逐字复述。"
)
_RECALL_HEADER = (
    "【相关记忆】以下是与当前话题相关的记忆，只在有帮助时自然参考，不要逐字复述。"
)


def normalize_layer(value: Any) -> str:
    """任意值 → 合法层名；缺省/未知一律 ``fact``（老条目兼容）。"""
    layer = str(value or "").strip().lower()
    return layer if layer in LAYERS else DEFAULT_LAYER


def layer_of(entry: dict[str, Any]) -> str:
    """条目层名（缺省 fact）。"""
    return normalize_layer(entry.get("layer"))


def extract_keywords(text: Any, limit: int = MAX_KEYWORDS) -> list[str]:
    """从文本提取关键词：CJK bigram + 拉丁/数字词，去重、保序、截到 ``limit``。

    单字 CJK 且在虚词表里的跳过；双字 bigram 不拆（例如「不吃」「周三」）。
    同一套函数用于写入（手动钉/提炼 ops）与查询，避免两边口径漂移。
    """
    if limit <= 0:
        return []
    raw = str(text or "").lower()
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        if token and token not in seen and token not in _STOPWORDS:
            seen.add(token)
            keywords.append(token)

    for match in _TOKEN_RE.finditer(raw):
        token = match.group(0)
        if _CJK_RE.match(token):
            if len(token) == 1:
                _add(token)
                continue
            for index in range(len(token) - 1):
                _add(token[index:index + 2])
        elif len(token) >= 2:
            _add(token)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def _entry_keywords(entry: dict[str, Any]) -> list[str]:
    """条目关键词：优先持久化的 ``keywords``，缺失/空则现场 bigram 兜底。"""
    raw = entry.get("keywords")
    cleaned: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            token = str(item or "").strip().lower()
            if token and token not in cleaned:
                cleaned.append(token)
    if cleaned:
        return cleaned
    return extract_keywords(entry.get("text", ""))


def _entry_time(entry: dict[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            return datetime.fromisoformat(str(entry.get(key, ""))).timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


def _now(now: datetime | None) -> datetime:
    value = now or datetime.now().astimezone()
    return value.astimezone() if value.tzinfo else value.astimezone()


def decay(entry: dict[str, Any], now: datetime | None = None) -> float:
    """艾宾浩斯衰减：``0.5 ** (age_days / 14)``（未来时间按 0 天）。"""
    age_days = max(0.0, (_now(now).timestamp() - _entry_time(entry, "updated_at", "created_at"))
                   / _SECONDS_PER_DAY)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def importance(entry: dict[str, Any]) -> float:
    """importance：manual=1.2 / auto=1.0；lesson 层恒 ×1.3。"""
    weight = 1.2 if str(entry.get("source", "")).strip().lower() == "manual" else 1.0
    if layer_of(entry) == "lesson":
        weight *= 1.3
    return weight


def _topic_last_activity(entry: dict[str, Any]) -> float:
    return max(
        _entry_time(entry, "last_hit_at"),
        _entry_time(entry, "updated_at"),
        _entry_time(entry, "created_at"),
    )


def _topic_is_stale(entry: dict[str, Any], now: datetime) -> bool:
    last = _topic_last_activity(entry)
    if last <= 0:
        return False
    return (_now(now).timestamp() - last) / _SECONDS_PER_DAY >= TOPIC_ARCHIVE_DAYS


def is_archived(entry: dict[str, Any], now: datetime | None = None) -> bool:
    """topic 是否归档：显式 ``archived`` 或连续 14 天未命中。非 topic 恒 False。"""
    if layer_of(entry) != "topic":
        return False
    if bool(entry.get("archived")):
        return True
    return _topic_is_stale(entry, _now(now))


def archive_stale_topics(entries: list[dict[str, Any]], now: datetime | None = None) -> bool:
    """把连续 14 天未命中的 topic 标成 ``archived``；返回是否有改动（纯内存）。"""
    moment = _now(now)
    changed = False
    for entry in entries:
        if (layer_of(entry) == "topic"
                and not bool(entry.get("archived"))
                and _topic_is_stale(entry, moment)):
            entry["archived"] = True
            changed = True
    return changed


def _idf_map(entries: list[dict[str, Any]]) -> dict[str, float]:
    """BM25 风格 idf：``log(1 + (N - df + 0.5) / (df + 0.5))``。"""
    total = max(1, len(entries))
    document_frequency: dict[str, int] = {}
    for entry in entries:
        for keyword in set(_entry_keywords(entry)):
            document_frequency[keyword] = document_frequency.get(keyword, 0) + 1
    return {
        keyword: math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))
        for keyword, frequency in document_frequency.items()
    }


def score_entry(
    entry: dict[str, Any],
    query_keywords: set[str],
    idf: dict[str, float],
    now: datetime | None = None,
) -> float:
    """单条打分：交集 idf 分 × 覆盖率 × 衰减 × importance；无交集 = 0。"""
    keywords = _entry_keywords(entry)
    if not keywords or not query_keywords:
        return 0.0
    matched = [keyword for keyword in keywords if keyword in query_keywords]
    if not matched:
        return 0.0
    coverage = len(matched) / len(keywords)
    intersection = sum(idf.get(keyword, 0.0) for keyword in matched)
    return intersection * coverage * decay(entry, now) * importance(entry)


def rank_entries(
    entries: list[dict[str, Any]],
    query: str,
    *,
    now: datetime | None = None,
) -> list[tuple[float, dict[str, Any]]]:
    """按命中分降序返回 ``(score, entry)``；user 层与归档 topic 不参与。"""
    moment = _now(now)
    query_keywords = set(extract_keywords(query, limit=_QUERY_KEYWORD_LIMIT))
    if not query_keywords:
        return []
    candidates = [
        entry for entry in entries
        if layer_of(entry) != "user" and not is_archived(entry, moment)
    ]
    idf = _idf_map(candidates)
    scored = []
    for entry in candidates:
        score = score_entry(entry, query_keywords, idf, moment)
        if score > 0:
            scored.append((score, entry))
    scored.sort(
        key=lambda item: (
            -item[0],
            -_entry_time(item[1], "updated_at", "created_at"),
            str(item[1].get("id", "")),
        )
    )
    return scored


@dataclass(frozen=True)
class RecallResult:
    """一次检索的结果：注入条目、渲染文本、更新后的已见 id 集合。"""

    entries: tuple[dict[str, Any], ...] = ()
    text: str = ""
    seen: frozenset[str] = field(default_factory=frozenset)


def _render_entries(
    header: str,
    entries: list[dict[str, Any]],
    char_limit: int,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    limit = max(0, int(char_limit))
    section = header
    included: list[dict[str, Any]] = []
    for entry in entries:
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        candidate = f"{section}\n- {text}"
        if len(candidate) > limit:
            break
        section = candidate
        included.append(entry)
    if not included:
        return "", ()
    return section, tuple(included)


def render_user_snapshot(
    entries: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    char_limit: int = USER_CHAR_LIMIT,
) -> str:
    """user 层恒定注入段：按 importance × 新近度排序，硬字符上限。"""
    moment = _now(now)
    user_entries = [
        entry for entry in entries
        if layer_of(entry) == "user" and str(entry.get("text", "")).strip()
    ]
    user_entries.sort(
        key=lambda entry: (
            -(importance(entry) * decay(entry, moment)),
            -_entry_time(entry, "updated_at", "created_at"),
        )
    )
    text, _included = _render_entries(_USER_HEADER, user_entries, char_limit)
    return text


def recall(
    entries: list[dict[str, Any]],
    query: str,
    *,
    seen: frozenset[str] | set[str] | None = None,
    now: datetime | None = None,
    turn_index: int = 2,
    top_k: int = RECALL_TOP_K,
    char_limit: int = RECALL_CHAR_LIMIT,
) -> RecallResult:
    """按需命中 top-k 并渲染；首轮（``turn_index <= 1``）恒空。

    已见规则：排序后的前 2 条无论是否已见都注入；第 3 条起跳过已见，
    顺延到下一个未见条目（防止「越搜越偏」）。
    """
    seen_ids = frozenset(str(item) for item in (seen or ()))
    if int(turn_index) <= 1:
        return RecallResult(seen=seen_ids)
    ranked = rank_entries(entries, query, now=now)
    if not ranked:
        return RecallResult(seen=seen_ids)
    selected: list[dict[str, Any]] = []
    for index, (_score, entry) in enumerate(ranked):
        if len(selected) >= max(1, int(top_k)):
            break
        entry_id = str(entry.get("id", ""))
        if index < 2 or entry_id not in seen_ids:
            selected.append(entry)
    if not selected:
        return RecallResult(seen=seen_ids)
    text, included = _render_entries(_RECALL_HEADER, selected, char_limit)
    if not included:
        return RecallResult(seen=seen_ids)
    updated = seen_ids | {str(entry.get("id", "")) for entry in included}
    return RecallResult(entries=included, text=text, seen=frozenset(updated))


# ---------------------------------------------------------------- 注入暂存 / 已见
@dataclass
class _PendingInjection:
    entries: list[dict[str, Any]]
    session_key: str
    note_hits: Callable[[list[str]], Any] | None = None


_PENDING = threading.local()
_SEEN_LOCK = threading.Lock()
_SEEN: OrderedDict[tuple[str, str], frozenset[str]] = OrderedDict()
_SEEN_MAX_SESSIONS = 128


def stage_injection(
    entries: list[dict[str, Any]],
    *,
    session_key: str = "",
    note_hits: Callable[[list[str]], Any] | None = None,
) -> None:
    """由 ``memory.injection_text`` 暂存本次读到的条目；``prompt`` 消费后清空。

    这是不改变聊天窗调用签名的接缝：调用方只把 user 快照传进
    ``build_messages``，fact/lesson/topic 的命中在 ``build_messages`` 内按
    真实用户消息补上。暂存按线程隔离（两个聊天窗各自的 GUI 调用栈互不串）。
    """
    _PENDING.context = _PendingInjection(
        entries=list(entries),
        session_key=str(session_key or ""),
        note_hits=note_hits,
    )


def clear_staged_injection() -> None:
    if getattr(_PENDING, "context", None) is not None:
        del _PENDING.context


def _take_staged_injection() -> _PendingInjection | None:
    context = getattr(_PENDING, "context", None)
    if context is not None:
        del _PENDING.context
    return context


def _history_key(history: list[Any] | tuple[Any, ...] | None) -> str:
    if not history:
        return ""
    first = history[0]
    return str(
        getattr(first, "message_id", "")
        or getattr(first, "created_at", "")
        or ""
    )


def augment_for_turn(
    history: list[Any] | tuple[Any, ...] | None,
    user_text: str,
    *,
    now: datetime | None = None,
) -> str:
    """消费暂存条目并返回本轮的 recall 段；没有暂存/首轮/无命中 → 空串。"""
    context = _take_staged_injection()
    if context is None:
        return ""
    query = str(user_text or "").strip()
    if not query:
        return ""
    has_history = bool(history)
    session = (context.session_key, _history_key(history))
    if not has_history:
        with _SEEN_LOCK:
            _SEEN.pop(session, None)
        return ""
    with _SEEN_LOCK:
        seen = _SEEN.get(session, frozenset())
    result = recall(context.entries, query, seen=seen, now=now, turn_index=2)
    if result.seen:
        with _SEEN_LOCK:
            _SEEN[session] = result.seen
            _SEEN.move_to_end(session)
            while len(_SEEN) > _SEEN_MAX_SESSIONS:
                _SEEN.popitem(last=False)
    if result.entries and context.note_hits is not None:
        topics = [
            str(entry.get("id", "")) for entry in result.entries
            if layer_of(entry) == "topic"
        ]
        if topics:
            try:
                context.note_hits(topics)
            except Exception:  # noqa: BLE001 - 命中记录失败绝不打断对话
                pass
    return result.text
