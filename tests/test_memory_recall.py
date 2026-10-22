# -*- coding: utf-8 -*-
"""全局记忆 v2a：分层、检索打分、已见去重、首轮闸与 topic 归档。

测试口径与 ``.scratch/memory-v2/SPEC-v2a.md`` 一致：
- 老记忆文件（无 layer/keywords）读取即 fact，且**不迁移**（盘上原样）；
- 打分对交集、idf、覆盖率、艾宾浩斯衰减、importance 各自单调；
- top-3 的前 2 条不排除已见，第 3 条起跳过已见；
- 首轮只注 user 快照，第二轮起才命中 fact/lesson/topic；
- topic 连续 14 天未命中自动归档、可恢复；
- 手动钉四前缀分别落 user/lesson/topic/fact。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from pet.chat.memory import (
    LAYERS,
    ChatMemory,
    injection_text,
    layer_of,
    memory_path,
    memory_payload,
    parse_remember_command,
)
from pet.chat.memory_recall import (
    HALF_LIFE_DAYS,
    MAX_KEYWORDS,
    RECALL_TOP_K,
    TOPIC_ARCHIVE_DAYS,
    _now,
    archive_stale_topics,
    extract_keywords,
    is_archived,
    rank_entries,
    recall,
    render_user_snapshot,
)
from pet.chat.models import ChatMessage, ChatSettings
from pet.chat.prompt import PromptBuilder

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _entry(
    text: str,
    *,
    layer: str = "fact",
    keywords: list[str] | None = None,
    source: str = "manual",
    updated_at: datetime = NOW,
    entry_id: str | None = None,
    **extra,
) -> dict:
    item = {
        "id": entry_id or f"id-{text}",
        "text": text,
        "source": source,
        "layer": layer,
        "created_at": updated_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "hits": 1,
    }
    if keywords is not None:
        item["keywords"] = list(keywords)
    item.update(extra)
    return item


def _scores(entries: list[dict], query: str, now: datetime = NOW) -> dict[str, float]:
    return {entry["text"]: score for score, entry in rank_entries(entries, query, now=now)}


# ---------------------------------------------------------------- 分层兼容
def test_old_memory_file_reads_as_fact_without_migration(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "old-1",
                        "text": "周三有课",
                        "source": "manual",
                        "created_at": NOW.isoformat(),
                        "updated_at": NOW.isoformat(),
                        "hits": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    entries = ChatMemory(path).load()
    assert entries[0]["layer"] == "fact"
    assert layer_of(entries[0]) == "fact"
    assert entries[0]["keywords"]  # 老条目现场 bigram 兜底
    assert path.read_text(encoding="utf-8") == before  # 无迁移写盘


def test_unknown_layer_falls_back_to_fact():
    assert layer_of({"text": "x", "layer": "bogus"}) == "fact"
    assert layer_of({"text": "x"}) == "fact"
    assert LAYERS == ("user", "fact", "lesson", "topic")


def test_load_grouped_is_four_groups_and_newest_first(tmp_path):
    ticks = iter(
        [
            NOW,
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=2),
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=4),
        ]
    )
    mem = ChatMemory(tmp_path / "memory.json", clock=lambda: next(ticks))
    mem.add("旧事实", layer="fact")
    mem.add("新事实", layer="fact")
    mem.add("偏好", layer="user")
    mem.add("教训", layer="lesson")
    mem.add("话题", layer="topic")
    groups = mem.load_grouped()
    assert set(groups) == set(LAYERS)
    assert [e["text"] for e in groups["fact"]] == ["新事实", "旧事实"]
    assert [e["text"] for e in groups["user"]] == ["偏好"]
    assert [e["text"] for e in groups["lesson"]] == ["教训"]
    assert [e["text"] for e in groups["topic"]] == ["话题"]


# ---------------------------------------------------------------- 关键词 / 打分
def test_extract_keywords_bigram_and_words_and_cap():
    keywords = extract_keywords("我不吃辣，喜欢 Python 和 pytest")
    assert "不吃" in keywords
    assert "python" in keywords
    assert "pytest" in keywords
    # v2b A：上限放宽到整条记忆（48），不再只留前 6 个 bigram。
    assert len(extract_keywords("很长" * 100)) <= MAX_KEYWORDS
    assert MAX_KEYWORDS == 48


def test_long_entry_keyword_cap_recalls_exam_topic():
    """盲审反例 1：条目关键词不能只留前 6 个 bigram（考试被截掉）。"""
    entries = [_entry("我在准备十月底的考试"), _entry("今天天气不错")]
    result = recall(entries, "考试还有两周，有点紧张", now=NOW)
    assert [e["text"] for e in result.entries][:1] == ["我在准备十月底的考试"]
    assert "今天天气不错" not in [e["text"] for e in result.entries]


def test_version_number_produces_bigrams_and_recalls():
    """盲审反例 2：4.4.0 这类数字 token 不再按长度丢弃，且产出 4.4/4.0 bigram。"""
    keywords = extract_keywords("版本 4.4.0 修了几个崩溃")
    assert "4.4" in keywords
    assert "4.0" in keywords
    entries = [_entry("版本 4.4.0 修了几个崩溃"), _entry("今天天气不错")]
    result = recall(entries, "4.4.0 还有问题吗", now=NOW)
    assert [e["text"] for e in result.entries][:1] == ["版本 4.4.0 修了几个崩溃"]
    assert "今天天气不错" not in [e["text"] for e in result.entries]


def test_score_grows_with_keyword_intersection():
    entries = [
        _entry("多词", keywords=["考试", "复习"]),
        _entry("单词", keywords=["考试"]),
    ]
    assert _scores(entries, "考试 复习")["多词"] > _scores(entries, "考试 复习")["单词"]


def test_score_grows_with_idf():
    entries = [
        _entry("rare", keywords=["alpha"]),
        _entry("common-1", keywords=["beta"]),
        _entry("common-2", keywords=["beta"]),
        _entry("common-3", keywords=["beta"]),
    ]
    scores = _scores(entries, "alpha beta")
    assert scores["rare"] > scores["common-1"]


def test_coverage_favors_entry_with_fewer_unmatched_keywords():
    entries = [
        _entry("focused", keywords=["alpha"]),
        _entry("diffuse", keywords=["alpha", "beta"]),
    ]
    # beta 在另一条里也出现，idf 相同口径下 focused 的覆盖率更高
    scores = _scores(entries, "alpha")
    assert scores["focused"] > scores["diffuse"]


def test_ebbinghaus_decay_halves_every_fourteen_days():
    old = _entry("旧", keywords=["alpha"], updated_at=NOW - timedelta(days=HALF_LIFE_DAYS))
    new = _entry("新", keywords=["alpha"], updated_at=NOW)
    scores = _scores([old, new], "alpha")
    assert scores["新"] > scores["旧"]
    assert scores["旧"] == pytest.approx(scores["新"] * 0.5, rel=1e-6)


def test_importance_manual_and_lesson_are_weighted():
    auto = _entry("自动", keywords=["alpha"], source="auto")
    manual = _entry("手动", keywords=["alpha"], source="manual")
    lesson = _entry("教训", layer="lesson", keywords=["alpha"], source="auto")
    scores = _scores([auto, manual, lesson], "alpha")
    assert scores["手动"] > scores["自动"]
    assert scores["教训"] > scores["自动"]


def test_global_idf_keeps_relative_order_when_unrelated_entries_added():
    """G：idf 用全部未归档条目统计，加无关条目后既有条目相对排序不变。"""
    focused = _entry("focused", keywords=["alpha"])
    diffuse = _entry("diffuse", keywords=["alpha", "beta"])
    baseline = recall([focused, diffuse], "alpha", now=NOW)
    assert [e["text"] for e in baseline.entries] == ["focused", "diffuse"]
    noise = [
        _entry(f"无关-{index}", keywords=[f"zz{index}"])
        for index in range(39)
    ]
    grown = recall([focused, diffuse, *noise], "alpha", now=NOW)
    assert [e["text"] for e in grown.entries] == ["focused", "diffuse"]


def test_now_dead_branch_merged():
    """H：naive 与 aware 都按本地时区归一，语义不变。"""
    naive = datetime(2026, 10, 21, 12, 0)
    aware = naive.astimezone()
    assert _now(naive) == aware
    assert _now(aware) == aware


# ---------------------------------------------------------------- 命中 / 已见
def test_first_turn_has_no_recall_and_second_turn_does():
    entries = [
        _entry("我不吃辣", layer="user"),
        _entry("周三有课", keywords=["周三", "有课"]),
    ]
    assert "我不吃辣" in render_user_snapshot(entries, now=NOW)
    assert "周三有课" not in render_user_snapshot(entries, now=NOW)
    assert recall(entries, "周三有课吗", now=NOW, turn_index=1).entries == ()
    second = recall(entries, "周三有课吗", now=NOW, turn_index=2)
    assert [e["text"] for e in second.entries] == ["周三有课"]


def test_recall_top_three_and_first_two_ignore_seen():
    entries = [
        _entry(f"e{index}", keywords=[f"kw{index}"],
               updated_at=NOW - timedelta(days=index))
        for index in range(4)
    ]
    query = "kw0 kw1 kw2 kw3"
    first = recall(entries, query, now=NOW)
    assert [e["text"] for e in first.entries] == ["e0", "e1", "e2"]
    assert len(first.entries) == RECALL_TOP_K
    second = recall(entries, query, now=NOW, seen=first.seen)
    # 前 2 条豁免已见；第 3 条（e2）跳过，顺延到 e3
    assert [e["text"] for e in second.entries] == ["e0", "e1", "e3"]
    assert "e2" not in {e["text"] for e in second.entries}


def test_recall_empty_hit_does_not_render_placeholder():
    entries = [_entry("周三有课", keywords=["周三"])]
    result = recall(entries, "完全无关的句子", now=NOW)
    assert result.entries == ()
    assert result.text == ""


def test_archived_topic_excluded_from_recall():
    stale = _entry(
        "旧话题",
        layer="topic",
        keywords=["bug"],
        updated_at=NOW - timedelta(days=TOPIC_ARCHIVE_DAYS + 1),
        last_hit_at=(NOW - timedelta(days=TOPIC_ARCHIVE_DAYS + 1)).isoformat(),
    )
    fresh = _entry("新话题", layer="topic", keywords=["bug"], updated_at=NOW)
    assert is_archived(stale, NOW) is True
    assert is_archived(fresh, NOW) is False
    result = recall([stale, fresh], "bug", now=NOW)
    assert [e["text"] for e in result.entries] == ["新话题"]
    assert [e["text"] for e in recall([stale], "bug", now=NOW).entries] == []


def test_archive_stale_topics_only_touches_topics():
    stale_topic = _entry(
        "话题",
        layer="topic",
        updated_at=NOW - timedelta(days=TOPIC_ARCHIVE_DAYS + 1),
    )
    old_fact = _entry(
        "事实",
        layer="fact",
        updated_at=NOW - timedelta(days=TOPIC_ARCHIVE_DAYS + 1),
    )
    assert archive_stale_topics([stale_topic, old_fact], NOW) is True
    assert stale_topic["archived"] is True
    assert "archived" not in old_fact


def test_topic_auto_archive_persists_via_product_path(tmp_path):
    """F：产品路径落盘（build_messages → augment_for_turn → note_recalled 巡检）。

    不是直接调 ``note_recalled([])`` 的假绿断言：这里从真实 prompt 构建进入，
    由 daemon 写盘线程把 ``archived=True`` 落到 memory.json，再读盘核对。
    """
    path = tmp_path / "memory.json"
    first = ChatMemory(path, clock=lambda: NOW)
    entry, _ = first.add("那个 Bug", layer="topic")
    later = NOW + timedelta(days=TOPIC_ARCHIVE_DAYS + 1)
    later_mem = ChatMemory(path, clock=lambda: later)
    payload = memory_payload(later_mem, True)

    builder = PromptBuilder()
    builder.build_messages(
        _settings(), "cat", _history(), "完全无关的句子",
        now=later, memory_payload=payload,
    )
    assert later_mem.flush_hits(5.0) is True

    raw = json.loads(path.read_text(encoding="utf-8"))
    persisted = next(e for e in raw["entries"] if e["id"] == entry["id"])
    assert persisted["archived"] is True
    assert is_archived(persisted, later) is True

    assert later_mem.set_archived(entry["id"], False) is True
    restored = later_mem.load()[0]
    assert restored["archived"] is False
    assert is_archived(restored, later) is False


def test_note_recalled_empty_ids_archive_via_internal_api(tmp_path):
    """F 补充：覆盖内部异步批量 API——空命中同样触发归档巡检并最终落盘。"""
    path = tmp_path / "memory.json"
    first = ChatMemory(path, clock=lambda: NOW)
    entry, _ = first.add("那个 Bug", layer="topic")
    later = NOW + timedelta(days=TOPIC_ARCHIVE_DAYS + 1)
    later_mem = ChatMemory(path, clock=lambda: later)
    later_mem.note_recalled([])
    assert later_mem.flush_hits(5.0) is True
    raw = json.loads(path.read_text(encoding="utf-8"))
    persisted = next(e for e in raw["entries"] if e["id"] == entry["id"])
    assert persisted["archived"] is True


# ---------------------------------------------------------------- 手动钉四前缀
@pytest.mark.parametrize(
    ("raw", "body", "layer"),
    [
        ("记住偏好：我不吃辣", "我不吃辣", "user"),
        ("记住：周三有课", "周三有课", "fact"),
        ("记住教训：别再把配置删了", "别再把配置删了", "lesson"),
        ("记住话题：4.4.0 发版", "4.4.0 发版", "topic"),
        ("记住偏好:我不吃辣", "我不吃辣", "user"),
    ],
)
def test_parse_remember_command_four_prefixes(raw, body, layer):
    command = parse_remember_command(raw)
    assert command == body
    assert command.layer == layer


@pytest.mark.parametrize("raw", ["请记住偏好：x", "记住我", "你好", ""])
def test_parse_remember_command_non_command_stays_none(raw):
    assert parse_remember_command(raw) is None


def test_add_uses_prefix_layer_and_extracts_keywords(tmp_path):
    mem = ChatMemory(tmp_path / "memory.json")
    command = parse_remember_command("记住教训：别再把配置删了")
    entry, created = mem.add(command)
    assert created is True
    assert entry["layer"] == "lesson"
    assert entry["keywords"]
    assert mem.load()[0]["layer"] == "lesson"


def test_add_accepts_full_remember_command_text(tmp_path):
    mem = ChatMemory(tmp_path / "memory.json")
    entry, _ = mem.add("记住偏好：别叫我全名")
    assert entry["text"] == "别叫我全名"
    assert entry["layer"] == "user"


def test_manual_pin_remember_topic_unarchives(tmp_path):
    """D：手动钉「记住话题：」是允许解除归档的入口（自动来源不允许）。"""
    path = tmp_path / "memory.json"
    mem = ChatMemory(path, clock=lambda: NOW)
    entry, _ = mem.add("记住话题：那个 Bug")
    assert mem.set_archived(entry["id"], True) is True
    assert mem.load()[0]["archived"] is True
    again, created = mem.add("记住话题：那个 Bug")
    assert created is False
    assert "archived" not in again
    assert mem.load()[0].get("archived") is not True


# ---------------------------------------------------------------- 首轮/次轮注入集成
def _settings():
    return ChatSettings()


def _history():
    return [
        ChatMessage("user", "第一轮"),
        ChatMessage("assistant", "回复"),
    ]


def test_injection_text_is_user_snapshot_only(tmp_path):
    path = memory_path(tmp_path, "", "shenshen")
    mem = ChatMemory(path)
    mem.add("我不吃辣", layer="user")
    mem.add("周三有课", layer="fact")
    section = injection_text(True, tmp_path, "", "shenshen")
    assert "我不吃辣" in section
    assert "周三有课" not in section


def test_prompt_first_turn_skips_recall_then_second_turn_hits(tmp_path):
    path = memory_path(tmp_path, "", "shenshen")
    mem = ChatMemory(path)
    mem.add("我不吃辣", layer="user")
    mem.add("周三有课", layer="fact")
    builder = PromptBuilder()
    now = datetime(2026, 10, 21, 12, 0).astimezone()
    payload = memory_payload(mem, True)

    first = builder.build_messages(
        _settings(), "cat", [], "周三有课吗", now=now, memory_payload=payload
    )
    assert "我不吃辣" in first[0]["content"]
    assert "周三有课" not in first[0]["content"]

    second = builder.build_messages(
        _settings(), "cat", _history(), "周三有课吗",
        now=now, memory_payload=payload,
    )
    assert "周三有课" in second[0]["content"]


# ---------------------------------------------------------------- v2b B：显式 payload
def _payload_for(tmp_path, character_id: str, text: str):
    path = memory_path(tmp_path, "", character_id)
    mem = ChatMemory(path)
    mem.add(text, layer="fact")
    return memory_payload(mem, True)


def test_payloads_do_not_cross_sessions(tmp_path):
    """B：A/B 两个 payload 交替构建，各自只拿到自己的条目（不再串会话）。"""
    builder = PromptBuilder()
    now = datetime(2026, 10, 21, 12, 0).astimezone()
    payload_a = _payload_for(tmp_path, "alpha", "周三有课")
    payload_b = _payload_for(tmp_path, "beta", "我不吃辣")

    first = builder.build_messages(
        _settings(), "cat", _history(), "周三有课吗", now=now, memory_payload=payload_a)
    second = builder.build_messages(
        _settings(), "cat", _history(), "我不吃辣吗", now=now, memory_payload=payload_b)
    third = builder.build_messages(
        _settings(), "cat", _history(), "周三有课吗", now=now, memory_payload=payload_a)

    assert "周三有课" in first[0]["content"]
    assert "我不吃辣" not in first[0]["content"]
    assert "我不吃辣" in second[0]["content"]
    assert "周三有课" not in second[0]["content"]
    assert "周三有课" in third[0]["content"]


def test_payload_exception_does_not_pollute_next_build(tmp_path, monkeypatch):
    """B：一次构建中途抛异常，不应留下任何可供下一次取走的暂存状态。"""
    import pet.chat.prompt as prompt_mod

    builder = PromptBuilder()
    now = datetime(2026, 10, 21, 12, 0).astimezone()
    payload_a = _payload_for(tmp_path, "alpha", "周三有课")
    payload_b = _payload_for(tmp_path, "beta", "我不吃辣")
    real_augment = prompt_mod.augment_for_turn
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("构建中途失败")
        return real_augment(*args, **kwargs)

    monkeypatch.setattr(prompt_mod, "augment_for_turn", flaky)
    with pytest.raises(RuntimeError):
        builder.build_messages(
            _settings(), "cat", _history(), "周三有课吗", now=now, memory_payload=payload_a)
    recovered = builder.build_messages(
        _settings(), "cat", _history(), "我不吃辣吗", now=now, memory_payload=payload_b)
    assert "我不吃辣" in recovered[0]["content"]
    assert "周三有课" not in recovered[0]["content"]


def test_payload_wins_over_memory_text_without_duplicate_injection(tmp_path):
    """B：memory_text 与 memory_payload 同时给时以 payload 为准，不重复注入。"""
    builder = PromptBuilder()
    now = datetime(2026, 10, 21, 12, 0).astimezone()
    payload = _payload_for(tmp_path, "alpha", "周三有课")
    messages = builder.build_messages(
        _settings(), "cat", _history(), "周三有课吗", now=now,
        memory_text="【关于用户的记忆】\n- 不该出现", memory_payload=payload)
    system = messages[0]["content"]
    assert "不该出现" not in system
    assert system.count("周三有课") == 1


def test_build_messages_without_payload_is_byte_identical():
    """B 硬约束：未传 memory_payload 时输出与改动前逐字节一致（固定输入）。"""
    now = datetime(2026, 10, 21, 12, 0).astimezone()
    history = [
        ChatMessage("user", "上一条", created_at=(now - timedelta(minutes=5)).isoformat(),
                    message_id="m1"),
        ChatMessage("assistant", "回复", created_at=(now - timedelta(minutes=4, seconds=30)).isoformat(),
                    message_id="m2"),
    ]
    messages = PromptBuilder().build_messages(
        _settings(), "cat", history, "你好", now=now)
    assert messages == [
        {
            "role": "system",
            "content": (
                "你是一只可爱的桌面宠物，请用自然、友善的中文和用户交流。\n\n"
                "【时间信息】当前时间：2026-10-21 周三 12:00。对话记录中用户消息开头的"
                "「[日期 时间]」是系统自动附加的发送时间，用来帮助你感知时间的流逝"
                "（例如隔了多久没聊、现在是白天还是深夜、日期是否变了），回复时自然地"
                "体现即可；不要在回复中复述或模仿这种时间标记。"
            ),
        },
        {"role": "user", "content": "[2026-10-21 周三 11:55] 上一条"},
        {"role": "assistant", "content": "回复"},
        {"role": "user", "content": "你好"},
    ]


# ---------------------------------------------------------------- v2b C：异步命中写盘
def test_topic_hit_build_messages_fast_and_persists_async(tmp_path):
    """C：GUI 线程构建 <5ms；命中 last_hit_at 最终由 daemon 线程落盘。"""
    path = tmp_path / "memory.json"
    mem = ChatMemory(path)
    topic, _ = mem.add("那个 Bug", layer="topic")
    payload = memory_payload(mem, True)
    builder = PromptBuilder()
    now = datetime(2026, 10, 21, 12, 0).astimezone()

    started = time.perf_counter()
    messages = builder.build_messages(
        _settings(), "cat", _history(), "那个 Bug 怎么样了",
        now=now, memory_payload=payload)
    elapsed = time.perf_counter() - started
    assert "那个 Bug" in messages[0]["content"]
    assert elapsed < 0.005, f"GUI 线程构建耗时 {elapsed * 1000:.2f}ms，超过 5ms"

    assert mem.flush_hits(5.0) is True
    raw = json.loads(path.read_text(encoding="utf-8"))
    persisted = next(e for e in raw["entries"] if e["id"] == topic["id"])
    assert datetime.fromisoformat(persisted["last_hit_at"]) >= datetime.fromisoformat(
        persisted["created_at"])


def test_note_recalled_cache_visible_before_disk_write(tmp_path):
    """C：命中先更新进程内缓存（load 立即可见），随后由 daemon 线程落盘。"""
    path = tmp_path / "memory.json"
    mem = ChatMemory(path, clock=lambda: NOW)
    topic, _ = mem.add("那个 Bug", layer="topic")
    later = NOW + timedelta(days=3)
    mem.note_recalled([topic["id"]], now=later)
    assert mem.load()[0]["last_hit_at"] == later.isoformat()
    assert mem.flush_hits(5.0) is True
    raw = json.loads(path.read_text(encoding="utf-8"))
    persisted = next(e for e in raw["entries"] if e["id"] == topic["id"])
    assert persisted["last_hit_at"] == later.isoformat()
