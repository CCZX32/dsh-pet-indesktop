"""歌词取词的匹配质量：清洗查询词、按候选打分、纯音乐标记（离线）。

「认错歌」的根因不是网络，而是**只校验歌手名就取第一个候选**：搜「晴天 周杰伦」
时排在前面的是翻唱/同名曲，歌手字段里带着"周杰伦"三个字就命中了。这里把
「歌名 / 歌手 / 专辑 / 时长」四维加权（缺失字段重新归一），低于阈值宁可不取。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.contracts.http import HttpError, HttpResponse

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "media.music"
HOST_PKG = "petcore_music_lyric_quality_host"


def _host_package():
    if HOST_PKG in sys.modules:
        return sys.modules[HOST_PKG]
    spec = importlib.util.spec_from_file_location(
        HOST_PKG,
        MOD_DIR / "host" / "__init__.py",
        submodule_search_locations=[str(MOD_DIR / "host")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[HOST_PKG] = module
    spec.loader.exec_module(module)
    return module


_host_package()
lyrics_mod = importlib.import_module(f"{HOST_PKG}.lyrics")


class _Http:
    """按 URL 片段回应的 HttpPort 替身；记录每次请求。"""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        outcome = self.handler(request)
        if isinstance(outcome, BaseException):
            raise outcome
        status, payload = outcome
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return HttpResponse(status=status, url=request.url, headers=(), body=body)


def _candidate(title="晴天", artists=("周杰伦",), album="", duration=None, ident=1):
    return {
        "id": ident,
        "title": title,
        "artists": list(artists),
        "album": album,
        "duration": duration,
    }


# ---------------------------------------------------------------- 打分


def test_exact_match_scores_one() -> None:
    score = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", candidate=_candidate()
    )
    assert score == pytest.approx(1.0)


def test_cover_with_wrong_artist_is_rejected() -> None:
    """翻唱：歌名相同、歌手不同 —— 旧实现会拿它当原唱取词。"""
    score = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", candidate=_candidate(artists=["某翻唱歌手"])
    )
    assert score < lyrics_mod.MATCH_THRESHOLD


def test_same_artist_wrong_title_is_rejected() -> None:
    score = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", candidate=_candidate(title="七里香")
    )
    assert score < lyrics_mod.MATCH_THRESHOLD


def test_missing_fields_are_renormalised_not_penalised() -> None:
    """接口不返回歌名/专辑时不能一律低分（否则老流程整片失效）。"""
    only_artist = lyrics_mod.candidate_score(
        title="晴天",
        artist="周杰伦",
        candidate={"artists": ["周杰伦"]},
    )
    assert only_artist == pytest.approx(1.0)


def test_title_containment_counts_highly() -> None:
    score = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", candidate=_candidate(title="晴天 (Live)")
    )
    assert score >= 0.9


def test_duration_mismatch_lowers_but_keeps_a_same_song() -> None:
    with_duration = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", duration=269.0,
        candidate=_candidate(duration=269.0),
    )
    wrong_duration = lyrics_mod.candidate_score(
        title="晴天", artist="周杰伦", duration=269.0,
        candidate=_candidate(duration=430.0),
    )
    assert with_duration > wrong_duration
    assert wrong_duration >= lyrics_mod.MATCH_THRESHOLD


def test_multi_artist_candidate_still_matches() -> None:
    score = lyrics_mod.candidate_score(
        title="FLOW", artist="FLOW、GRANRODEO",
        candidate=_candidate(title="FLOW", artists=["FLOW/GRANRODEO"]),
    )
    assert score >= lyrics_mod.MATCH_THRESHOLD


def test_pick_best_chooses_the_score_winner() -> None:
    candidates = [
        _candidate(artists=["某翻唱歌手"]),
        _candidate(artists=["周杰伦"]),
    ]
    best = lyrics_mod.pick_best(
        candidates, title="晴天", artist="周杰伦"
    )
    assert best is not None
    assert best[0]["artists"] == ["周杰伦"]
    assert best[1] >= lyrics_mod.MATCH_THRESHOLD


def test_pick_best_returns_none_below_the_threshold() -> None:
    assert (
        lyrics_mod.pick_best(
            [_candidate(title="七里香", artists=["某歌手"])],
            title="晴天",
            artist="周杰伦",
        )
        is None
    )


# ---------------------------------------------------------------- 查询词清洗


def test_web_title_is_cleaned_before_searching() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        if "cloudsearch" in request.url:
            return (200, {"result": {"songs": []}})
        return (200, {"lrc": {"lyric": ""}})

    http = _Http(handler)
    with pytest.raises(lyrics_mod.LyricsError):
        lyrics_mod.fetch_lyrics(
            http,
            "【4K】周杰伦《晴天》官方MV_哔哩哔哩_bilibili",
            "",
            timeout=1.0,
        )
    params = dict(seen[0].params)
    assert "晴天" in params["s"]
    assert "哔哩哔哩" not in params["s"]
    assert "4K" not in params["s"]


# ---------------------------------------------------------------- 源选择


def test_source_picks_the_right_candidate_not_the_first() -> None:
    def handler(request):
        if "cloudsearch" in request.url:
            return (
                200,
                {
                    "result": {
                        "songs": [
                            {"id": 1, "name": "晴天", "ar": [{"name": "某翻唱歌手"}]},
                            {"id": 2, "name": "晴天", "ar": [{"name": "周杰伦"}]},
                        ]
                    }
                },
            )
        params = dict(request.params)
        assert params["id"] == "2"  # 取的是打分最高的那首，不是第一条
        return (200, {"lrc": {"lyric": "[00:00.00]第一句\n[00:05.00]第二句"}})

    result = lyrics_mod.fetch_lyrics(_Http(handler), "晴天", "周杰伦", timeout=1.0)
    assert result.lines[0].text == "第一句"
    assert result.source == "网易云"
    assert result.score >= lyrics_mod.MATCH_THRESHOLD


def test_rejected_candidates_fall_through_to_the_next_source() -> None:
    def handler(request):
        if "cloudsearch" in request.url:
            # 只有翻唱：宁可不取，换下一个源
            return (
                200,
                {"result": {"songs": [{"id": 9, "name": "晴天", "ar": [{"name": "翻唱歌手"}]}]}},
            )
        if "krcs.kugou.com" in request.url:
            return (200, {"candidates": []})
        if "lrclib.net" in request.url:
            return (200, {"syncedLyrics": "[00:00.00]lrclib 第一句"})
        return HttpError("protocol", status=404)

    result = lyrics_mod.fetch_lyrics(_Http(handler), "晴天", "周杰伦", timeout=3.0)
    assert result.source == "lrclib"
    assert result.lines[0].text == "lrclib 第一句"


def test_lrclib_instrumental_flag_is_honoured() -> None:
    def handler(request):
        if "cloudsearch" in request.url:
            return (200, {"result": {"songs": []}})
        if "krcs.kugou.com" in request.url:
            return (200, {"candidates": []})
        if "lrclib.net" in request.url:
            return (200, {"instrumental": True})
        return HttpError("protocol", status=404)

    result = lyrics_mod.fetch_lyrics(_Http(handler), "钢琴曲", "", timeout=3.0)
    assert result.instrumental is True
    assert result.lines == ()


def test_all_sources_failing_names_every_source() -> None:
    def handler(request):
        if "cloudsearch" in request.url:
            return (200, {"result": {"songs": []}})
        if "krcs.kugou.com" in request.url:
            return (200, {"candidates": []})
        return HttpError("protocol", status=404)

    with pytest.raises(lyrics_mod.LyricsError) as excinfo:
        lyrics_mod.fetch_lyrics(_Http(handler), "晴天", "周杰伦", timeout=3.0)
    message = str(excinfo.value)
    assert "网易云" in message and "酷狗" in message and "lrclib" in message
