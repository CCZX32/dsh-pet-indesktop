"""音乐识别判定层：多来源证据合并（纯函数，离线）。

判定表（写死在用例里就是契约）：SMTC 是主源，音频会话是"在不在出声"的裁判，
播放器窗口标题只在 SMTC 没有在播会话时兜底。任何"猜"都要有证据。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "media.music"
HOST_PKG = "petcore_music_sources_test_host"


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
recognizer = importlib.import_module(f"{HOST_PKG}.recognizer")
now_playing = importlib.import_module(f"{HOST_PKG}.now_playing")
players_mod = importlib.import_module(f"{HOST_PKG}.players")


# ---------------------------------------------------------------- 替身


def audio(exe: str, state: str = "active", *, muted: bool = False, peak: float = 0.4):
    return SimpleNamespace(pid=1, exe=exe, state=state, muted=muted, peak=peak)


def window(exe: str, title: str, pid: int = 1):
    return SimpleNamespace(pid=pid, exe=exe, title=title)


def sample(
    *,
    playback=None,
    audio_rows=(),
    windows=(),
    smtc_reason: str = "",
    smtc_error: bool = False,
    audio_available: bool = True,
    window_available: bool = True,
):
    return SimpleNamespace(
        sessions=(),
        playback=playback,
        smtc_reason=smtc_reason,
        smtc_error=smtc_error,
        audio=tuple(audio_rows),
        audio_available=audio_available,
        windows=tuple(windows),
        window_available=window_available,
    )


def playback(
    title: str = "晴天",
    artist: str = "周杰伦",
    *,
    app_id: str = "cloudmusic.exe",
    playing: bool = True,
    position: float | None = None,
    duration: float = 0.0,
):
    return now_playing.Playback(
        title=title,
        artist=artist,
        app_id=app_id,
        position=position,
        duration=duration,
        playing=playing,
    )


def parse_ok(title, exe, fmt=""):
    return ("晴天", "周杰伦")


# ---------------------------------------------------------------- SMTC 主源


def test_smtc_playing_with_active_audio_is_confirmed() -> None:
    decision = recognizer.decide(
        sample(playback=playback(), audio_rows=[audio("cloudmusic.exe")])
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.source == recognizer.SOURCE_SMTC
    assert decision.confidence == recognizer.CONFIDENCE_CONFIRMED
    assert decision.track is not None and decision.track.title == "晴天"
    assert any("state=active" in line for line in decision.evidence)


def test_smtc_playing_but_audio_inactive_counts_as_paused() -> None:
    """播放器还挂着"在播"、音频会话已经 Inactive：按暂停处理（不唱、歌词冻结）。"""
    decision = recognizer.decide(
        sample(playback=playback(), audio_rows=[audio("cloudmusic.exe", "inactive")])
    )
    assert decision.status == recognizer.STATUS_PAUSED
    assert decision.track is not None  # 曲目/歌词要留着
    assert any("inactive" in reason for reason in decision.reasons)


def test_smtc_playing_but_process_muted_counts_as_paused() -> None:
    decision = recognizer.decide(
        sample(playback=playback(), audio_rows=[audio("cloudmusic.exe", muted=True)])
    )
    assert decision.status == recognizer.STATUS_PAUSED
    assert any("静音" in reason for reason in decision.reasons)


def test_missing_audio_session_falls_back_to_smtc_status() -> None:
    """蓝牙 / 独占模式 / 虚拟声卡：会话表里没有它，按 SMTC 判，不许误判暂停。"""
    decision = recognizer.decide(
        sample(playback=playback(), audio_rows=[audio("steam.exe", "inactive")])
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.confidence == recognizer.CONFIDENCE_ASSUMED
    assert any("不在音频会话表" in line for line in decision.evidence)


def test_smtc_paused_stays_paused_even_if_audio_is_active() -> None:
    """SMTC 说暂停就暂停：音频活跃可能是提示音/切换动画，不能反推成在播。"""
    decision = recognizer.decide(
        sample(playback=playback(playing=False), audio_rows=[audio("cloudmusic.exe")])
    )
    assert decision.status == recognizer.STATUS_PAUSED


def test_uwp_app_id_without_exe_name_falls_back_to_smtc() -> None:
    decision = recognizer.decide(
        sample(
            playback=playback(app_id="SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
            audio_rows=[audio("spotify.exe")],
        )
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.exe == ""
    assert decision.confidence == recognizer.CONFIDENCE_ASSUMED


def test_smtc_read_failure_is_error_not_absence() -> None:
    decision = recognizer.decide(
        sample(smtc_reason="读取系统媒体信息超时。", smtc_error=True)
    )
    assert decision.status == recognizer.STATUS_ERROR
    assert decision.readable is False
    assert decision.reasons == ("读取系统媒体信息超时。",)


# ---------------------------------------------------------------- 窗口标题兜底


def test_window_source_supplies_track_when_smtc_has_nothing() -> None:
    decision = recognizer.decide(
        sample(
            smtc_reason="系统里没有正在播放的媒体会话。",
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
            audio_rows=[audio("foobar2000.exe")],
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.source == recognizer.SOURCE_WINDOW
    assert decision.track is not None and decision.track.artist == "周杰伦"


def test_window_source_without_audio_evidence_is_not_playing() -> None:
    """开着播放器没在放（标题停在上一首）：没有音频会话就不认。"""
    decision = recognizer.decide(
        sample(
            smtc_reason="系统里没有正在播放的媒体会话。",
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
            audio_rows=[],
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_ABSENT
    assert any("没有音频会话" in reason for reason in decision.reasons)


def test_window_source_with_inactive_audio_is_paused() -> None:
    decision = recognizer.decide(
        sample(
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
            audio_rows=[audio("foobar2000.exe", "inactive")],
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_PAUSED
    assert decision.source == recognizer.SOURCE_WINDOW


def test_window_source_with_unparsed_title_sings_without_track() -> None:
    """认不出歌名可以只唱歌：track 为空，但状态是在播（不取词）。"""
    decision = recognizer.decide(
        sample(
            windows=[window("aimp.exe", "某个看不懂的标题")],
            audio_rows=[audio("aimp.exe")],
        ),
        parse_window=lambda *_args: None,
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.track is None
    assert decision.source == recognizer.SOURCE_WINDOW


def test_window_source_falls_back_to_title_only_when_audio_metering_is_unavailable() -> None:
    """没有音频证据可用时（例如非 Windows 探针缺失）退回"按标题认"，置信度 assumed。"""
    decision = recognizer.decide(
        sample(
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
            audio_rows=[],
            audio_available=False,
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.confidence == recognizer.CONFIDENCE_ASSUMED


def test_unknown_process_audio_only_is_not_music() -> None:
    """游戏/语音/未知应用在出声不算音乐（对误检的收紧，写进判定表）。"""
    decision = recognizer.decide(
        sample(smtc_reason="系统里没有正在播放的媒体会话。", audio_rows=[audio("game.exe")])
    )
    assert decision.status == recognizer.STATUS_ABSENT
    assert "系统里没有正在播放的媒体会话。" in decision.reasons


def test_allowlist_applies_to_the_window_source_too() -> None:
    """识别范围对三个来源统一生效，被挡下要点名播放器。"""
    decision = recognizer.decide(
        sample(
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
            audio_rows=[audio("foobar2000.exe")],
        ),
        allowed_ids=frozenset({"cloudmusic"}),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_ABSENT
    assert any("不在识别范围" in reason for reason in decision.reasons)


# ---------------------------------------------------------------- 小工具


@pytest.mark.parametrize(
    ("app_id", "expected"),
    [
        ("cloudmusic.exe", "cloudmusic.exe"),
        ("Chrome", "chrome.exe"),
        ("MSEdge", "msedge.exe"),
        ("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", ""),
        ("", ""),
    ],
)
def test_exe_name_normalization(app_id: str, expected: str) -> None:
    assert recognizer.exe_name(app_id) == expected


def test_track_key_and_label() -> None:
    track = recognizer.Track(title=" 晴天 ", artist="周杰伦")
    assert track.key() == ("晴天", "周杰伦")
    assert track.label() == "周杰伦 - 晴天"
    assert recognizer.Track(title="").label() == "未知曲目"


def test_recognition_targets_union_known_configured_and_extras() -> None:
    targets = players_mod.recognition_targets(
        {"netease": r"D:\CloudMusic\cloudmusic.exe", "x": r"D:\Other\MyPlayer.exe"},
        "汽水音乐, foo",
    )
    assert "cloudmusic.exe" in targets
    assert "myplayer.exe" in targets
    assert "foobar2000.exe" in targets  # 已知表
    assert "foo.exe" in targets  # 额外识别名补 .exe
    assert "汽水音乐.exe" in targets


def test_window_source_does_not_repeat_the_title_as_artist() -> None:
    """顺序不可知（无格式串）时只显示一次整条标题，不把同一串贴两遍。"""
    decision = recognizer.decide(
        sample(
            windows=[window("foobar2000.exe", "开不了口 - 周杰伦")],
            audio_rows=[audio("foobar2000.exe")],
        ),
        parse_window=lambda title, _exe, _fmt: (title, title),
    )
    assert decision.track is not None
    assert decision.track.title == "开不了口 - 周杰伦"
    assert decision.track.artist == ""
    assert decision.track.label() == "开不了口 - 周杰伦"


def test_paused_smtc_session_does_not_hide_another_playing_player() -> None:
    """SMTC 里挂着暂停会话、另一台不注册 SMTC 的播放器在出声：判定要认后者。

    「挂着的客户端 + foobar 在放」是最常见的使用姿势；旧逻辑在这种情况下窗口源
    白采一遍、诊断里证据齐全却判"暂停"，也没有任何理由说明。
    """
    decision = recognizer.decide(
        sample(
            playback=playback(title="上一首", playing=False),
            audio_rows=[audio("cloudmusic.exe", "inactive"), audio("foobar2000.exe")],
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_PLAYING
    assert decision.source == recognizer.SOURCE_WINDOW
    assert decision.track is not None and decision.track.title == "晴天"
    assert any("暂停" in reason and "以窗口标题源为准" in reason for reason in decision.reasons)


def test_paused_smtc_session_still_wins_when_no_other_player_sounds() -> None:
    decision = recognizer.decide(
        sample(
            playback=playback(title="上一首", playing=False),
            audio_rows=[audio("cloudmusic.exe", "inactive")],
            windows=[window("foobar2000.exe", "晴天 - 周杰伦")],
        ),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_PAUSED
    assert decision.source == recognizer.SOURCE_SMTC


def test_path_shaped_app_id_is_reduced_to_its_executable_name() -> None:
    """有些播放器把 app_id 报成完整安装路径：必须取 basename，否则音频证据全失配、路径还会进诊断。"""
    full_path = "C:" + chr(92) + "Program Files" + chr(92) + "Netease" + chr(92) + "cloudmusic.exe"
    decision = recognizer.decide(
        sample(playback=playback(app_id=full_path), audio_rows=[audio("cloudmusic.exe", muted=True)])
    )
    assert decision.exe == "cloudmusic.exe"
    assert decision.status == recognizer.STATUS_PAUSED  # 静音否决必须生效
    assert "Program Files" not in decision.exe


def test_window_allowlist_reasons_are_deduplicated() -> None:
    decision = recognizer.decide(
        sample(
            windows=[
                window("foobar2000.exe", "A - B", pid=1),
                window("foobar2000.exe", "A - C", pid=1),
            ],
            audio_rows=[audio("foobar2000.exe")],
        ),
        allowed_ids=frozenset({"cloudmusic"}),
        parse_window=parse_ok,
    )
    assert decision.status == recognizer.STATUS_ABSENT
    hits = [reason for reason in decision.reasons if "不在识别范围" in reason]
    assert len(hits) == 1
