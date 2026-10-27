"""音乐运行时状态机：抖动不清歌词、唱歌退避可恢复、取词冷却重试、多宠 lease、令牌。

这一组用例对应实机踩过的八个坑（见 PR 报告的 R1–R8）；它们**必须**在真实状态机
路径上跑（后台取词用同步替身只是为了不用等线程，判定与状态转换是真的）。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib
import sys

from petcore.contracts.http import HttpError  # noqa: E402
from tests.test_petcore_music_mod import (  # noqa: E402  （复用同一套 host 包与替身）
    HOST_PKG,
    FakeHttpPort,
    _Harness,
    _Presentation,
    _netease_handler,
    _playback,
)

importlib.import_module(f"{HOST_PKG}.runtime")
now_playing = importlib.import_module(f"{HOST_PKG}.now_playing")
lyrics_mod = importlib.import_module(f"{HOST_PKG}.lyrics")
runtime_mod = importlib.import_module(f"{HOST_PKG}.runtime")


# ---------------------------------------------------------------- 抖动


def test_read_failure_keeps_lyrics_and_does_not_refetch():
    """R1：一次采样失败不许清空歌词 / 重新联网取词（旧实现会当成新歌）。"""
    port = FakeHttpPort(_netease_handler)
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        http=port,
        playback=_playback(position=0.0),
    )
    harness.poll()
    assert harness.presentation.said == ["第一句"]
    requests = len(port.requests)
    track_key = harness.runtime._track_key

    harness.runtime.sample_smtc = lambda **_kwargs: now_playing.SmtcSample(
        reason="读取系统媒体信息超时。", failed=True
    )
    harness.now += 1
    harness.poll()

    assert harness.runtime._track_key == track_key
    assert harness.runtime._lines  # 歌词还在
    assert len(port.requests) == requests  # 没有重新取词


def test_absent_track_is_not_forgotten():
    """R1：播放器关掉/暂停很久也不清曲目状态；恢复后不会重新取词。"""
    port = FakeHttpPort(_netease_handler)
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False, "music_sing_grace_seconds": 1},
        http=port,
        playback=_playback(position=0.0),
    )
    harness.poll()
    requests = len(port.requests)

    harness.sample = None
    for _ in range(5):
        harness.now += 2
        harness.poll()
    assert harness.runtime._lines
    assert harness.runtime._track_key is not None

    harness.sample = _playback(position=0.0)
    harness.now += 1
    harness.poll()
    assert len(port.requests) == requests


# ---------------------------------------------------------------- 唱歌退避


def test_singing_recovers_after_animation_becomes_available():
    """R3：重试用尽不许永久放弃（旧实现只能重启）。"""
    from tests.test_petcore_music_mod import _Presentation

    presentation = _Presentation(start=False)
    harness = _Harness(
        {"music_lyric_enabled": False}, presentation=presentation, playback=_playback()
    )
    for _ in range(4):
        harness.poll()
        harness.now += 1
    assert harness.runtime.singing is False

    presentation.start = True
    for _ in range(40):
        harness.poll()
        harness.now += 1
    assert harness.runtime.singing is True


# ---------------------------------------------------------------- 歌词重试


def _failing_fetch(calls: list[str]):
    def fetch(_http, title, _artist, **_kwargs):
        calls.append(title)
        raise lyrics_mod.LyricsError("歌词获取失败：网易云：没有找到匹配的歌词")

    return fetch


def test_lyric_failure_retries_after_cooldown_with_a_cap():
    """R4：一次失败不许拉黑整首；冷却后重试，并封顶尝试次数。"""
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        http=FakeHttpPort(_netease_handler),
        playback=_playback(),
    )
    calls: list[str] = []
    harness.runtime.fetch_lyrics = _failing_fetch(calls)

    harness.poll()
    assert len(calls) == 1
    assert harness.runtime._lines == ()

    # 冷却期内不再重试
    harness.now += 5
    harness.poll()
    assert len(calls) == 1

    # 冷却到期 → 第二次、第三次
    harness.now += runtime_mod.LYRIC_RETRY_SECONDS
    harness.poll()
    assert len(calls) == 2
    harness.now += runtime_mod.LYRIC_RETRY_SECONDS
    harness.poll()
    assert len(calls) == 3

    # 上限用尽后不再发请求
    harness.now += runtime_mod.LYRIC_RETRY_SECONDS * 3
    harness.poll()
    assert len(calls) == runtime_mod.LYRIC_MAX_ATTEMPTS


def test_lyric_failure_reason_is_shown_once():
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        http=FakeHttpPort(_netease_handler),
        playback=_playback(),
    )
    harness.runtime.fetch_lyrics = _failing_fetch([])
    harness.poll()
    bubble = [text for text in harness.presentation.said if "歌词获取失败" in text]
    assert len(bubble) == 1

    harness.now += runtime_mod.LYRIC_RETRY_SECONDS
    harness.poll()
    again = [text for text in harness.presentation.said if "歌词获取失败" in text]
    assert len(again) == 1  # 只报一次，不刷屏


# ---------------------------------------------------------------- 气泡失败


def test_failed_bubble_does_not_advance_the_lyric_line():
    """R2：`say` 没显示出去时不许推进行号（旧实现那一句永久丢失）。"""

    class _Mute(_Presentation):
        def __init__(self):
            super().__init__()
            self.mute = True

        def say(self, text, *, duration_ms=4000, force=False, subtitle=""):
            if self.mute:
                return False
            self.said.append(text)
            return True

    presentation = _Mute()
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        presentation=presentation,
        http=FakeHttpPort(_netease_handler),
        playback=_playback(position=0.0),
    )
    harness.poll()
    assert presentation.said == []
    assert harness.runtime._lyric_index == -1

    presentation.mute = False
    harness.now += 2
    harness.poll()
    assert presentation.said == ["第一句"]
    assert harness.runtime._lyric_index == 0


# ---------------------------------------------------------------- 多宠 lease


class _Leaf:
    def __init__(self, slot, root):
        self.slot = slot
        self._root = root

    def play_animation(self, name, *, loop=False):
        self._root.leases[self.slot] = name
        return self._root.start

    def release_loop(self):
        self._root.leases.pop(self.slot, None)
        self._root.released.append(self.slot)
        return True

    def say(self, text, *, duration_ms=4000, force=False, subtitle=""):
        self._root.said.append(text)
        return True

    def notify(self, title, message, *, force=False, on_click=None):
        return True


class _MultiPetPresentation:
    """支持 ``for_slot`` 的呈现端口（多宠场景）。"""

    def __init__(self, start: bool = True):
        self.start = start
        self.leases: dict[int, str] = {}
        self.released: list[int] = []
        self.said: list[str] = []

    def for_slot(self, slot):
        return _Leaf(int(slot), self)

    def say(self, text, *, duration_ms=4000, force=False, subtitle=""):
        self.said.append(text)
        return True

    def play_animation(self, name, *, loop=False):
        return False

    def release_loop(self):
        return False


class _Pets:
    def __init__(self, slots):
        self.slots = list(slots)

    def pets(self):
        return [SimpleNamespace(slot=slot) for slot in self.slots]


def _multi_harness(slots):
    presentation = _MultiPetPresentation()
    harness = _Harness(
        {"music_lyric_enabled": False}, presentation=presentation, playback=_playback()
    )
    harness.ports.pets = _Pets(slots)
    return harness, presentation


def test_every_visible_pet_gets_its_own_sing_lease():
    harness, presentation = _multi_harness([0, 1])
    harness.poll()
    harness.now += 1
    harness.poll()
    assert presentation.leases == {0: runtime_mod.SING_ANIM, 1: runtime_mod.SING_ANIM}
    assert harness.runtime.singing is True


def test_closing_one_pet_releases_only_that_slot():
    """R5：切宠/关宠时释放要按 slot，不能打到另一只身上。"""
    harness, presentation = _multi_harness([0, 1])
    harness.poll()
    harness.now += 1
    harness.poll()
    assert set(presentation.leases) == {0, 1}

    harness.ports.pets.slots = [0]
    harness.now += 1
    harness.poll()
    assert presentation.released == [1]
    assert set(presentation.leases) == {0}

    harness.runtime.stop()
    assert presentation.released == [1, 0]


# ---------------------------------------------------------------- 令牌


def test_late_sample_is_dropped():
    """R8：迟到的采样不许覆盖更新的判定（每拍一个令牌）。"""
    harness = _Harness({"music_lyric_enabled": False}, playback=_playback())
    runtime = harness.runtime
    newer = runtime_mod._Request(False, "", frozenset(), "", frozenset(), seq=5)
    older = runtime_mod._Request(False, "", frozenset(), "", frozenset(), seq=4)

    runtime._consume(now_playing.SmtcSample(playback=_playback(title="新歌")), newer)
    accepted = runtime.last_decision
    runtime._consume(now_playing.SmtcSample(playback=_playback(title="旧歌")), older)

    assert runtime.last_decision is accepted
    assert runtime.last_decision.track.title == "新歌"


def test_single_absent_tick_never_flashes_the_loop_even_with_zero_grace():
    """缺席至少观察 2 拍：宽限设 0 时，一次采样抖动也不许让循环闪断重来。"""
    harness = _Harness(
        {"music_lyric_enabled": False, "music_sing_grace_seconds": 0},
        playback=_playback(),
    )
    harness.poll()
    harness.now += 1
    harness.poll()
    assert harness.runtime.singing is True

    harness.sample = None
    harness.now += 1      # 第 1 拍缺席：只记下静音起点
    harness.poll()
    assert harness.presentation.released == 0

    harness.now += 1      # 第 2 拍：还差 1 秒到确认拍数
    harness.poll()
    assert harness.presentation.released == 0

    harness.now += 1      # 第 3 拍：满 ABSENT_CONFIRM_TICKS 拍才解除
    harness.poll()
    assert harness.presentation.released == 1


def test_sync_path_advances_the_sample_token():
    """同步兜底路径也必须每拍换令牌（否则"迟到采样"的判断在测试路径上永远不生效）。"""
    harness = _Harness({"music_lyric_enabled": False}, playback=_playback())
    runtime = harness.runtime
    seen: list[int] = []
    original = runtime._consume

    def consume(sample, request):
        seen.append(request.seq)
        original(sample, request)

    runtime._consume = consume
    for _ in range(3):
        harness.now += 1
        harness.poll()
    assert seen == [1, 2, 3]


def test_transport_commands_use_the_default_seam(monkeypatch):
    """播放控制命令走**默认接缝**也必须能通（`control_playback` 曾是类属性 → 绑定方法，
    把 self 塞进 action 位，四个命令 100% 报"系统媒体控制调用失败"）。"""
    calls: list[tuple[str, dict]] = []

    def fake_transport(action, **kwargs):
        calls.append((action, dict(kwargs)))
        return True, ""

    monkeypatch.setattr(now_playing, "transport", fake_transport)
    # 构造发生在 patch 之后：`__init__` 捕获的就是这个替身（路径与生产一致）
    harness = _Harness({"music_enabled": True})

    harness.runtime.commands["pause"]()
    harness.runtime.commands["next"]()

    assert [action for action, _kwargs in calls] == ["pause", "next"]
    assert harness.presentation.said == ["已播放/暂停", "已下一首"]


def test_control_playback_is_not_a_bound_method():
    """`control_playback` 必须是实例属性：类属性会被描述符协议绑成方法。"""
    assert "control_playback" not in vars(runtime_mod.MusicRuntime)
    harness = _Harness({"music_enabled": True})
    assert callable(harness.runtime.control_playback)
    assert getattr(harness.runtime.control_playback, "__self__", None) is None


def test_singing_waits_while_a_lyric_fetch_is_in_flight():
    """取词在飞时先别唱（纯音乐不该开口），但有上限；没在飞的曲目不受影响。"""
    importlib.import_module(f"{HOST_PKG}.recognizer")
    harness = _Harness(
        {"music_lyric_enabled": True},
        http=FakeHttpPort(lambda request: HttpError("timeout")),
        playback=_playback(),
    )
    pending: list = []
    harness.runtime.background = pending.append  # 取词永远"在飞"

    for _ in range(4):
        harness.poll()
        harness.now += 1
    assert harness.presentation.animations == []

    harness.now += 1
    harness.poll()  # 等满 LYRIC_PROBE_MAX_TICKS 后无条件放行
    assert harness.presentation.animations == [(runtime_mod.SING_ANIM, True)]


def test_unknown_track_is_announced_once_per_player():
    """认得出"在放歌"但认不出曲目时说明一次——用户要能分清"没歌"与"认不出"。"""
    recognizer = importlib.import_module(f"{HOST_PKG}.recognizer")
    harness = _Harness({"music_lyric_enabled": False}, playback=_playback())
    blind = recognizer.Decision(
        status=recognizer.STATUS_PLAYING,
        source=recognizer.SOURCE_WINDOW,
        track=None,
        exe="foobar2000.exe",
    )
    harness.runtime.decide = lambda *_args, **_kwargs: blind

    for _ in range(4):
        harness.poll()
        harness.now += 1
    said = [text for text in harness.presentation.said if "认不出来" in text]
    assert len(said) == 1
    assert "foobar2000.exe" in said[0]
