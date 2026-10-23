"""media.music：当前播放 + 歌词 + 唱歌动画（P4 重写）。

全部离线：网络走替身 ``HttpPort``，SMTC 走替身采样函数，音频/动画走替身
``presentation``，没有固定 sleep（时钟由测试推进）。设置页用 offscreen QApplication。
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.contracts.host import HostPorts
from petcore.contracts.http import HttpError, HttpResponse
from petcore.mods import feature as feature_mod
from petcore.mods.manifest import load_manifest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "media.music"
HOST_PKG = "petcore_music_test_host"


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
now_playing = importlib.import_module(f"{HOST_PKG}.now_playing")
lyrics_mod = importlib.import_module(f"{HOST_PKG}.lyrics")
players_mod = importlib.import_module(f"{HOST_PKG}.players")
runtime_mod = importlib.import_module(f"{HOST_PKG}.runtime")


# ---------------------------------------------------------------- 替身


class FakeHttpPort:
    """记录每个请求（含 prefer_direct / URL / 上限），按 handler 回应或抛错。"""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        outcome = self.handler(request)
        if isinstance(outcome, BaseException):
            raise outcome
        status, body, headers = outcome
        return HttpResponse(status=status, url=request.url, headers=tuple(headers), body=body)


def _json(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


NETEASE_LYRIC = "[00:00.00]第一句\n[00:03.00]第二句"


def _netease_handler(request):
    if "cloudsearch" in request.url:
        return (200, _json({"result": {"songs": [{"id": 42, "ar": [{"name": "陶喆"}]}]}}), ())
    if "/api/song/lyric" in request.url:
        return (200, _json({"lrc": {"lyric": NETEASE_LYRIC}}), ())
    return HttpError("protocol", status=404)


KUGOU_SEARCH = _json({"candidates": [{"id": "abc", "accesskey": "key", "singer": "陶喆", "song": "蝴蝶"}]})
KUGOU_LYRIC = _json(
    {"content": base64.b64encode("[00:01.00]酷狗第一句\n[00:02.00]酷狗第二句".encode("utf-8")).decode("ascii")}
)


def _kugou_handler(request):
    if "krcs.kugou.com" in request.url:
        return (200, KUGOU_SEARCH, ())
    if "lyrics.kugou.com" in request.url:
        return (200, KUGOU_LYRIC, ())
    return HttpError("protocol", status=404)


class _Presentation:
    def __init__(self, start: bool = True):
        self.said: list[str] = []
        self.animations: list[tuple[str, bool]] = []
        self.released = 0
        self.start = start

    def say(self, text, *, duration_ms=4000, force=False):
        self.said.append(text)

    def play_animation(self, name, *, loop=False):
        self.animations.append((name, loop))
        return self.start

    def release_loop(self):
        self.released += 1
        return True

    def play_event(self, group, variant=None):
        return False

    def show_image(self, path, caption="", *, duration_ms=4000, scale=1.0):
        return False

    def notify(self, title, message, *, force=False):
        return None


class _Config(dict):
    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return dict.get(self, key, default)


def _playback(
    title: str = "蝴蝶",
    artist: str = "陶喆",
    *,
    position: float | None = 0.0,
    playing: bool = True,
    app_id: str = "cloudmusic.exe",
):
    return now_playing.Playback(
        title=title,
        artist=artist,
        app_id=app_id,
        position=position,
        duration=180.0,
        playing=playing,
    )


class _Harness:
    """运行时 + 可推进的时钟 + 可替换的采样/网络。"""

    def __init__(self, config=None, *, presentation=None, http=None, playback=None):
        self.presentation = presentation or _Presentation()
        self.ports = HostPorts(
            presentation=self.presentation,
            config=_Config(config or {}),
            http=http,
        )
        self.runtime = runtime_mod.MusicRuntime(SimpleNamespace(ports=self.ports))
        self.now = 100.0
        self.sample = playback
        self.reads = 0
        self.runtime.clock = lambda: self.now
        self.runtime.read_playback = self._read
        # 后台取词同步执行：结果在 poll() 里就位，测试不必等线程。
        self.runtime.background = lambda work: work()

    def _read(self, **_kwargs):
        self.reads += 1
        return self.sample

    def poll(self) -> None:
        self.runtime.poll()


# ---------------------------------------------------------------- LRC


def test_parse_lrc_handles_offsets_multi_timestamps_and_bad_lines():
    text = (
        "[ti:测试]\n"
        "[offset:500]\n"
        "[00:01.00]第一句\n"
        "[00:02.00][00:04.50]重复句\n"
        "坏行\n"
        "[abc]无效\n"
        "[00:03:20]冒号毫秒\n"
    )
    lines = lyrics_mod.parse_lrc(text)
    assert [(round(line.at, 2), line.text) for line in lines] == [
        (1.5, "第一句"),
        (2.5, "重复句"),
        (3.7, "冒号毫秒"),
        (5.0, "重复句"),
    ]
    assert lyrics_mod.parse_lrc("") == ()


def test_line_at_applies_lead_and_offset():
    lines = lyrics_mod.parse_lrc("[00:10.00]A\n[00:20.00]B")
    assert lyrics_mod.line_at(lines, 9.0) == -1
    assert lyrics_mod.line_at(lines, 9.8) == -1
    assert lyrics_mod.line_at(lines, 9.8, lead=0.3) == 0
    assert lyrics_mod.line_at(lines, 19.8) == 0
    assert lyrics_mod.line_at(lines, 19.8, lead=0.3) == 1
    assert lyrics_mod.line_at(lines, 19.8, offset=0.5) == 1
    assert lyrics_mod.line_at(lines, None) == -1
    assert lyrics_mod.line_at((), 10.0) == -1
    assert lyrics_mod.line_duration_ms(lines, 0) == 6000
    assert lyrics_mod.line_duration_ms(lines, 1) == 3000


def test_instrumental_placeholder_is_recognised():
    instrumental = lyrics_mod.parse_lrc("[00:00.00]纯音乐，请欣赏")
    assert lyrics_mod.looks_instrumental(instrumental) is True
    assert lyrics_mod.looks_instrumental(lyrics_mod.parse_lrc("[00:00.00]Instrumental")) is True
    real = lyrics_mod.parse_lrc("[00:00.00]这是一首纯音乐\n[00:02.00]但这两句是歌词\n[00:03.00]还有第三句\n[00:04.00]第四句")
    assert lyrics_mod.looks_instrumental(real) is False


# ---------------------------------------------------------------- 取词


def test_fetch_lyrics_uses_first_source_directly():
    port = FakeHttpPort(_netease_handler)
    result = lyrics_mod.fetch_lyrics(port, "蝴蝶", "陶喆")

    assert [line.text for line in result.lines] == ["第一句", "第二句"]
    assert result.source == "网易云"
    assert len(port.requests) == 2
    assert all(request.prefer_direct is True for request in port.requests)
    assert all(request.max_bytes <= lyrics_mod.MAX_BYTES for request in port.requests)
    assert port.requests[0].params[:1] == (("s", "蝴蝶 陶喆"),)


def test_fetch_lyrics_falls_back_to_second_source():
    def handler(request):
        if "music.163.com" in request.url:
            return HttpError("network")
        return _kugou_handler(request)

    port = FakeHttpPort(handler)
    result = lyrics_mod.fetch_lyrics(port, "蝴蝶", "陶喆")

    assert result.source == "酷狗"
    assert [line.text for line in result.lines] == ["酷狗第一句", "酷狗第二句"]
    assert any("krcs.kugou.com" in request.url for request in port.requests)


def test_fetch_lyrics_failure_names_both_sources():
    port = FakeHttpPort(lambda request: HttpError("timeout"))
    with pytest.raises(lyrics_mod.LyricsError) as caught:
        lyrics_mod.fetch_lyrics(port, "蝴蝶", "陶喆")

    text = str(caught.value)
    assert "网易云" in text and "酷狗" in text and "请求超时" in text
    # 一首歌只试一轮：两个源各两跳以内的请求量，失败后不再重发。
    assert len(port.requests) == 2


def test_fetch_lyrics_marks_instrumental():
    def handler(request):
        if "cloudsearch" in request.url:
            return (200, _json({"result": {"songs": [{"id": 7, "ar": [{"name": "陶喆"}]}]}}), ())
        return (200, _json({"lrc": {"lyric": "[00:00.00]纯音乐，请欣赏"}}), ())

    result = lyrics_mod.fetch_lyrics(FakeHttpPort(handler), "飞机场的10:30", "陶喆")
    assert result.instrumental is True
    assert result.lines == ()


def test_cache_hit_skips_network_and_cap_is_enforced(tmp_path):
    cache = lyrics_mod.LyricsCache(tmp_path / "lyrics", limit=2)
    port = FakeHttpPort(_netease_handler)

    first = lyrics_mod.fetch_lyrics(port, "蝴蝶", "陶喆", cache=cache)
    assert len(port.requests) == 2
    again = lyrics_mod.fetch_lyrics(port, "蝴蝶", "陶喆", cache=cache)
    assert len(port.requests) == 2
    assert again.lines == first.lines

    for title in ("甲", "乙", "丙"):
        lyrics_mod.fetch_lyrics(port, title, "陶喆", cache=cache)
    files = list((tmp_path / "lyrics").glob("*.json"))
    assert len(files) == 2
    assert cache.path_for("蝴蝶", "陶喆").name.endswith(".json")


def test_cache_key_is_sha1_of_title_and_artist():
    assert lyrics_mod.cache_key("蝴蝶", "陶喆") == lyrics_mod.cache_key(" 蝴蝶 ", "陶喆")
    assert len(lyrics_mod.cache_key("蝴蝶", "陶喆")) == 40


# ---------------------------------------------------------------- 会话选择


def _session(app_id, *, media_type=now_playing.MEDIA_TYPE_MUSIC, playing=True, index=0):
    return now_playing.Session(
        app_id=app_id,
        media_type=media_type,
        playing=playing,
        browser=now_playing.is_browser_session(app_id),
        vetoed=now_playing.is_vetoed_session(app_id),
        index=index,
    )


def test_pick_singing_session_veto_rules():
    browser = _session("chrome.exe")
    music = _session("cloudmusic.exe")
    video = _session("cloudmusic.exe", media_type=now_playing.MEDIA_TYPE_VIDEO)
    system = _session("SystemSettings.exe")

    assert now_playing.pick_singing_session([browser], browser_media_enabled=False) is None
    assert now_playing.pick_singing_session([browser], browser_media_enabled=True) is browser
    assert now_playing.pick_singing_session([video, system]) is None
    assert now_playing.pick_singing_session([video, music], browser_media_enabled=False) is music
    assert now_playing.pick_singing_session([]) is None


def test_pick_singing_session_prefers_tracked_player_in_best_tier():
    browser = _session("chrome", index=0)
    music = _session("cloudmusic.exe", index=1)
    picked = now_playing.pick_singing_session(
        [browser, music], browser_media_enabled=True, tracked_app_id="cloudmusic.exe"
    )
    assert picked is music
    paused = _session("cloudmusic.exe", playing=False, index=0)
    assert (
        now_playing.pick_singing_session([paused], browser_media_enabled=False) is paused
    )


def test_allowed_app_ids_from_paths_and_extras():
    assert now_playing.allowed_app_ids({}) == frozenset()
    ids = now_playing.allowed_app_ids(
        {"netease": r"C:\Program Files\Netease\cloudmusic.exe"},
        extras="汽水音乐，QQMusic.exe",
    )
    assert ids == frozenset({"cloudmusic", "汽水音乐", "qqmusic"})


def test_pick_singing_session_respects_allowlist():
    netease = _session("cloudmusic.exe", index=0)
    kugou = _session("kugou.exe", index=1)
    allowed = frozenset({"cloudmusic"})

    assert now_playing.pick_singing_session([kugou], allowed_ids=allowed) is None
    assert (
        now_playing.pick_singing_session(
            [kugou, netease], allowed_ids=allowed
        )
        is netease
    )
    assert now_playing.accepts_singing(kugou, allowed_ids=allowed) is False
    assert now_playing.accepts_singing(netease, allowed_ids=allowed) is True


def test_player_registry_only_launches_configured_paths(tmp_path, monkeypatch):
    assert players_mod.player_keys() == ("netease", "qqmusic", "kugou", "soda")
    ok, message = players_mod.launch({}, "netease")
    assert ok is False and "还没有配置" in message
    ok, message = players_mod.launch({"netease": str(tmp_path / "missing.exe")}, "netease")
    assert ok is False and "路径不可用" in message

    launched: list[str] = []
    monkeypatch.setattr(players_mod.os, "startfile", launched.append, raising=False)
    exe = tmp_path / "cloudmusic.exe"
    exe.write_bytes(b"MZ")
    ok, message = players_mod.launch({"netease": str(exe)}, "netease")
    assert ok is True and "网易云音乐" in message
    assert launched == [str(exe)]


# ---------------------------------------------------------------- 唱歌状态机


def test_playing_track_starts_singing_once():
    harness = _Harness({"music_lyric_enabled": False}, playback=_playback())
    harness.poll()
    harness.poll()

    assert harness.presentation.animations == [(runtime_mod.SING_ANIM, True)]
    assert harness.presentation.released == 0


def test_failed_animation_is_retried_three_times_then_quiet():
    harness = _Harness(
        {"music_lyric_enabled": False},
        presentation=_Presentation(start=False),
        playback=_playback(),
    )
    for _ in range(8):
        harness.poll()
        harness.now += 1

    assert runtime_mod.SING_MAX_ATTEMPTS == 4
    assert len(harness.presentation.animations) == runtime_mod.SING_MAX_ATTEMPTS
    assert harness.presentation.released == 0


def test_silence_beyond_grace_releases_loop():
    harness = _Harness(
        {"music_lyric_enabled": False, "music_sing_grace_seconds": 5},
        playback=_playback(),
    )
    harness.poll()
    assert harness.presentation.released == 0

    harness.sample = None
    harness.now += 1
    harness.poll()
    harness.now += 3.5
    harness.poll()
    assert harness.presentation.released == 0

    harness.now += 1.5
    harness.poll()
    assert harness.presentation.released == 1
    assert harness.presentation.animations == [(runtime_mod.SING_ANIM, True)]


def test_pause_keeps_lines_and_releases_after_grace():
    harness = _Harness(
        {"music_lyric_enabled": False, "music_sing_grace_seconds": 2},
        playback=_playback(),
    )
    harness.poll()
    harness.sample = _playback(playing=False)
    harness.now += 1
    harness.poll()
    assert harness.presentation.released == 0
    harness.now += 2
    harness.poll()
    assert harness.presentation.released == 1


def test_instrumental_track_does_not_sing():
    def handler(request):
        if "cloudsearch" in request.url:
            return (200, _json({"result": {"songs": [{"id": 7, "ar": [{"name": "陶喆"}]}]}}), ())
        return (200, _json({"lrc": {"lyric": "[00:00.00]纯音乐，请欣赏"}}), ())

    harness = _Harness(
        {"music_sing_enabled": True, "music_lyric_enabled": True},
        http=FakeHttpPort(handler),
        playback=_playback(title="飞机场的10:30"),
    )
    harness.poll()
    harness.now += 1
    harness.poll()

    assert harness.presentation.animations == []
    assert harness.runtime.instrumental is True


def test_singing_disabled_does_nothing():
    harness = _Harness(
        {"music_sing_enabled": False, "music_lyric_enabled": False},
        playback=_playback(),
    )
    harness.poll()
    harness.poll()

    assert harness.presentation.animations == []
    assert harness.presentation.released == 0


def test_music_disabled_does_not_poll():
    harness = _Harness({"music_enabled": False}, playback=_playback())
    harness.poll()
    assert harness.reads == 0
    assert harness.presentation.animations == []


def test_stop_releases_loop():
    harness = _Harness({"music_lyric_enabled": False}, playback=_playback())
    harness.poll()
    harness.runtime.stop()
    assert harness.presentation.released == 1


# ---------------------------------------------------------------- 歌词节流


def test_lyric_bubble_has_lead_and_throttle():
    harness = _Harness(
        {
            "music_lyric_enabled": True,
            "music_lyric_lead_seconds": 0.3,
            "music_sing_enabled": False,
        },
        http=FakeHttpPort(_netease_handler),
        playback=_playback(position=0.0),
    )
    harness.poll()
    assert harness.presentation.said == ["第一句"]

    harness.now += 1.0
    harness.sample = _playback(position=3.0)
    harness.poll()
    assert harness.presentation.said == ["第一句"]

    harness.now += 1.0
    harness.poll()
    assert harness.presentation.said == ["第一句", "第二句"]


def test_pause_freezes_the_local_clock():
    def handler(request):
        if "cloudsearch" in request.url:
            return (200, _json({"result": {"songs": [{"id": 1, "ar": [{"name": "陶喆"}]}]}}), ())
        return (200, _json({"lrc": {"lyric": "[00:00.00]第一句\n[00:20.00]第二句"}}), ())

    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        http=FakeHttpPort(handler),
        playback=_playback(position=None),
    )
    harness.poll()
    assert harness.presentation.said == ["第一句"]

    harness.now += 5
    harness.sample = _playback(position=None, playing=False)
    harness.poll()
    harness.now += 60
    harness.sample = _playback(position=None)
    harness.poll()

    # 暂停的 60 秒不算进本地时钟：位置仍是 5 秒，不该跳到 20 秒那句。
    assert harness.presentation.said == ["第一句"]


def test_lyric_fetch_runs_once_per_track():
    port = FakeHttpPort(_netease_handler)
    harness = _Harness(
        {"music_lyric_enabled": True, "music_sing_enabled": False},
        http=port,
        playback=_playback(position=0.0),
    )
    harness.poll()
    requests = len(port.requests)
    harness.now += 1
    harness.poll()
    assert len(port.requests) == requests

    harness.sample = _playback(title="普通朋友", position=0.0)
    harness.now += 1
    harness.poll()
    assert len(port.requests) > requests


def test_lyric_align_cycles_offset_and_bubbles():
    harness = _Harness({"music_lyric_offset_seconds": 2.5, "music_lyric_enabled": False})
    runtime = harness.runtime
    runtime.lyric_align()
    assert runtime.lyric_offset() == 3.0
    runtime.lyric_align()
    assert runtime.lyric_offset() == runtime_mod.OFFSET_MIN
    assert "+3.0" in harness.presentation.said[0]
    assert "-3.0" in harness.presentation.said[1]


# ---------------------------------------------------------------- 命令反馈


def test_transport_without_session_reports_reason():
    harness = _Harness({"music_enabled": True})
    harness.runtime.control_playback = lambda action, *, tracked_app_id="": (
        False,
        "当前没有可控制的播放器（请先在播放器里播放一首歌）。",
    )
    harness.runtime.commands["pause"]()
    assert "没有可控制的播放器" in harness.presentation.said[-1]


def test_runtime_passes_allowlist_only_when_filter_enabled():
    harness = _Harness(
        {
            "music_enabled": True,
            "music_player_paths": {"netease": r"C:\Netease\cloudmusic.exe"},
            "music_filter_enabled": False,
        }
    )
    seen: list[dict] = []

    def read(**kwargs):
        seen.append(kwargs)
        return None

    harness.runtime.read_playback = read
    harness.poll()
    assert "allowed_ids" not in seen[-1]

    harness.ports.config.set("music_filter_enabled", True)
    harness.poll()
    assert seen[-1]["allowed_ids"] == frozenset({"cloudmusic"})


def test_sung_bubble_carries_subtitle_when_port_supports_it():
    class SubtitlePresentation(_Presentation):
        def __init__(self):
            super().__init__()
            self.calls = []

        def say(self, text, *, duration_ms=4000, force=False, subtitle=""):
            self.calls.append((text, subtitle))

    presentation = SubtitlePresentation()
    harness = _Harness({}, presentation=presentation)
    harness.runtime._title = "蝴蝶"

    assert harness.runtime._say_sung("第一句", subtitle=harness.runtime._subtitle())

    assert presentation.calls == [("第一句", "我在唱《蝴蝶》")]


def test_transport_success_reports_action():
    harness = _Harness({"music_enabled": True})
    harness.runtime.control_playback = lambda action, *, tracked_app_id="": (True, "")
    harness.runtime.commands["next"]()
    assert "下一首" in harness.presentation.said[-1]


def test_open_player_without_path_bubbles_reason():
    harness = _Harness({"music_enabled": True, "music_player_paths": {}})
    harness.runtime.commands["open_netease"]()
    assert "还没有配置" in harness.presentation.said[-1]


# ---------------------------------------------------------------- 清单与设置页


class _Host:
    def __init__(self, config):
        self.config = _Config(config)
        self.ports = SimpleNamespace(http=None)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_manifest_and_contributions_load():
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest.id == "media.music"
    assert manifest.kind == "feature"
    assert manifest.execution == "host-only"
    assert manifest.version == "1.1.0"

    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    assert diagnostics == []

    menu_ids = {contribution.id for _, contribution in manager.menu_contributions()}
    assert {
        "pause",
        "next",
        "prev",
        "stop",
        "lyric_align",
        "open_netease",
        "open_qqmusic",
        "open_kugou",
        "open_soda",
    } <= menu_ids
    pages = manager.settings_pages()
    assert pages and pages[0].owner == "media.music"
    assert pages[0].id == "music"
    owners_with_menu = {feature.owner for feature, _ in manager.menu_contributions()}
    owners_with_settings = {
        feature.owner
        for feature in manager.features.values()
        for contribution in feature.definition.contributions
        if contribution.kind == "settings_page"
    }
    assert owners_with_menu <= owners_with_settings

    commands = manager.features["media.music"].commands
    for command in ("pause", "next", "prev", "stop", "lyric_align", "open_soda"):
        assert callable(commands[command])


def test_settings_page_round_trip(app):
    manager = feature_mod.FeatureManager(HostPorts())
    manifest, _ = load_manifest(MOD_DIR)
    manager.load(pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={})
    page_class = manager.settings_pages()[0].factory

    host = _Host(
        {
            "music_enabled": True,
            "music_sing_enabled": True,
            "music_sing_grace_seconds": 5,
            "music_lyric_enabled": True,
            "music_lyric_lead_seconds": 0.3,
            "music_lyric_cache_limit": 80,
            "music_browser_media_enabled": False,
            "music_player": "",
            "music_player_paths": {},
        }
    )
    page = page_class(host)
    assert page.dirty() is False

    page.sing.setChecked(False)
    assert host.config["music_sing_enabled"] is False
    page.grace.setValue(9)
    assert host.config["music_sing_grace_seconds"] == 9
    page.lead.setValue(1.2)
    assert host.config["music_lyric_lead_seconds"] == 1.2
    page.browser.setChecked(True)
    assert host.config["music_browser_media_enabled"] is True
    page.player.setCurrentIndex(page.player.findData("netease"))
    assert host.config["music_player"] == "netease"

    page.path_edits["netease"].setText("C:/CloudMusic/cloudmusic.exe")
    page._on_path_changed("netease")
    assert host.config["music_player_paths"] == {"netease": "C:/CloudMusic/cloudmusic.exe"}
    assert page.dirty() is True

    page.confirm_save()
    assert page.dirty() is False

    page.sing.setChecked(True)
    page.discard_changes()
    assert page.sing.isChecked() is False
    assert host.config["music_sing_enabled"] is False
    assert host.config["music_player_paths"] == {"netease": "C:/CloudMusic/cloudmusic.exe"}


def test_settings_page_has_h2_and_h3_groups(app):
    from PySide6.QtWidgets import QLabel

    page = sys.modules[HOST_PKG].MusicPage(_Host({"music_enabled": True}))
    headings = [
        (label.objectName(), label.text())
        for label in page.findChildren(QLabel)
        if label.objectName() in {"groupTitle", "subsectionTitle"}
    ]
    assert headings[0] == ("groupTitle", "音乐")
    assert [text for name, text in headings if name == "subsectionTitle"] == [
        "播放与唱歌",
        "歌词显示",
        "识别范围",
        "切歌与播放控制",
        "播放器",
    ]


def test_settings_page_detect_result_is_shown(app):
    page = sys.modules[HOST_PKG].MusicPage(_Host({"music_enabled": True}))
    page._on_detect_done("陶喆 - 蝴蝶（在播）")
    assert "蝴蝶" in page.detect_status.text()
    assert page.detect_button.isEnabled() is True
    assert page.player.findData("netease") >= 0
    assert set(page.path_edits) == set(players_mod.player_keys())
