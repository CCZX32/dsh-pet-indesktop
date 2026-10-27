"""识别诊断文本：三个来源逐条可见，判定与理由都在，不泄隐私（离线）。

这段文本是用户报「不唱歌 / 歌词不对」时唯一要贴的东西，所以格式与开关必须被钉住：
少一段就没法判断是哪一层出的问题，多一段（URL / 路径）就带隐私。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "media.music"
HOST_PKG = "petcore_music_diagnostics_host"


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
diagnostics = importlib.import_module(f"{HOST_PKG}.diagnostics")
recognizer = importlib.import_module(f"{HOST_PKG}.recognizer")
now_playing = importlib.import_module(f"{HOST_PKG}.now_playing")


def _sample(**overrides):
    base = dict(
        playback=None,
        sessions=(),
        smtc_reason="",
        smtc_error=False,
        audio=(),
        audio_available=True,
        windows=(),
        window_available=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _session(app_id="cloudmusic.exe", media_type=1, playing=True, browser=False, vetoed=False):
    return now_playing.Session(
        app_id=app_id, media_type=media_type, playing=playing, browser=browser, vetoed=vetoed
    )


def _audio(exe="cloudmusic.exe", state="active", muted=False, peak=0.42):
    return SimpleNamespace(pid=24076, exe=exe, state=state, muted=muted, peak=peak)


def _window(exe="foobar2000.exe", title="开不了口 - 周杰伦"):
    return SimpleNamespace(pid=99, exe=exe, title=title)


def test_render_lists_every_source_and_the_decision() -> None:
    playback = now_playing.Playback(
        title="开不了口", artist="周杰伦", app_id="cloudmusic.exe", duration=180.0, playing=True
    )
    sample = _sample(
        playback=playback,
        sessions=(_session(), _session("chrome.exe", playing=False, browser=True)),
        audio=(_audio(), _audio("chrome.exe", "inactive", peak=0.0)),
        windows=(),
    )
    decision = recognizer.decide(sample)
    text = diagnostics.render(sample, decision, lyric_state="网易云命中 score=0.92 · 第 3 行 / 共 42 行")

    assert "SMTC：2 个会话" in text
    assert "MUSIC(1)" in text
    assert "浏览器" in text  # chrome 会话被标出来源
    assert "音频会话：2 个（Active 1）" in text
    assert "peak=0.42" in text
    assert "播放器窗口标题：0 个" in text  # SMTC 在播时按需跳过
    assert "判定：在播 · 来源=系统媒体会话" in text
    assert "《开不了口》—周杰伦" in text
    assert "歌词：网易云命中 score=0.92" in text


def test_render_explains_rejections_and_pause() -> None:
    sample = _sample(
        playback=now_playing.Playback(
            title="开不了口", artist="周杰伦", app_id="cloudmusic.exe", playing=True
        ),
        sessions=(_session(),),
        audio=(_audio(state="inactive", peak=0.0),),
    )
    decision = recognizer.decide(sample)
    text = diagnostics.render(sample, decision)
    assert "判定：暂停" in text
    assert "inactive" in text
    assert "理由：" in text


def test_render_marks_platform_and_empty_states() -> None:
    sample = _sample(audio_available=False, window_available=False, smtc_reason="系统里没有正在播放的媒体会话。")
    decision = recognizer.decide(sample)
    text = diagnostics.render(sample, decision)
    assert "SMTC：没有会话" in text
    assert "本平台不可用" in text
    assert "判定：不在播" in text
    assert "系统里没有正在播放的媒体会话。" in text


def test_render_marks_read_failure_as_keep_state() -> None:
    sample = _sample(smtc_error=True, smtc_reason="读取系统媒体信息超时。")
    decision = recognizer.decide(sample)
    text = diagnostics.render(sample, decision)
    assert "读取失败（保留上一次状态）" in text
    assert "超时" in text


def test_render_never_leaks_urls_or_paths() -> None:
    sample = _sample(
        playback=now_playing.Playback(title="x", artist="y", app_id="cloudmusic.exe", playing=True),
        audio=(_audio(),),
    )
    text = diagnostics.render(sample, recognizer.decide(sample))
    assert "http" not in text.lower()
    assert "\\" not in text
    assert "/api" not in text


def test_render_masks_local_paths_in_titles() -> None:
    """窗口标题里的本地路径只留文件名：这段文本是给用户复制出去贴工单的。"""
    sample = _sample(
        windows=(
            SimpleNamespace(
                pid=7, exe="foobar2000.exe", title=r"C:\Users\someone\Music\晴天 - 周杰伦.flac"
            ),
        ),
        audio=(SimpleNamespace(pid=7, exe="foobar2000.exe", state="active", muted=False, peak=0.5),),
        audio_available=True,
    )
    decision = recognizer.decide(
        sample, parse_window=lambda title, _exe, _fmt: (title, "")
    )
    text = diagnostics.render(sample, decision)
    assert "Users" not in text
    assert "someone" not in text
    assert "晴天 - 周杰伦.flac" in text
