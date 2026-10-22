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
from datetime import datetime, timedelta, timezone

import pytest

from pet.chat.memory import (
    LAYERS,
    ChatMemory,
    injection_text,
    layer_of,
    memory_path,
    parse_remember_command,
)
from pet.chat.memory_recall import (
    HALF_LIFE_DAYS,
    RECALL_TOP_K,
    TOPIC_ARCHIVE_DAYS,
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
    assert len(extract_keywords("很长" * 100)) <= 6


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


def test_topic_auto_archive_persists_and_restore_unarchives(tmp_path):
    path = tmp_path / "memory.json"
    mem = ChatMemory(path, clock=lambda: NOW)
    entry, _ = mem.add("那个 Bug", layer="topic")
    later = NOW + timedelta(days=TOPIC_ARCHIVE_DAYS + 1)
    later_mem = ChatMemory(path, clock=lambda: later)
    assert later_mem.note_recalled([]) is True
    archived = later_mem.load()[0]
    assert archived["archived"] is True
    assert is_archived(archived, later) is True
    assert later_mem.set_archived(entry["id"], False) is True
    restored = later_mem.load()[0]
    assert restored["archived"] is False
    assert is_archived(restored, later) is False


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

    first_memory = injection_text(True, tmp_path, "", "shenshen")
    first = builder.build_messages(
        _settings(), "cat", [], "周三有课吗", now=now, memory_text=first_memory
    )
    assert "我不吃辣" in first[0]["content"]
    assert "周三有课" not in first[0]["content"]

    second_memory = injection_text(True, tmp_path, "", "shenshen")
    second = builder.build_messages(
        _settings(), "cat", _history(), "周三有课吗", now=now, memory_text=second_memory
    )
    assert "周三有课" in second[0]["content"]
