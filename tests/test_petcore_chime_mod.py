"""voice.chime（P4-b 重写）：排期、台词轮换、运行时与设置页。

不联网、不碰真实音频、不用固定 sleep：语音端口是假实现，时间由 ``tick(now=...)``
注入；预合成线程用 ``threading.Event`` 闸住，join 有宽预算。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.contracts.host import HostPorts
from petcore.contracts.speech import (
    SpeechError,
    SpeechProviderInfo,
    SpeechRequest,
    SpeechResult,
)
from petcore.mods import feature as feature_mod
from petcore.mods.manifest import load_manifest

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "voice.chime"
HOST_PKG = "petcore_chime_test_host"


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
schedule = importlib.import_module(f"{HOST_PKG}.schedule")
quotes = importlib.import_module(f"{HOST_PKG}.quotes")
runtime_mod = importlib.import_module(f"{HOST_PKG}.runtime")


# ---------------------------------------------------------------- 测试替身


class _Presentation:
    def __init__(self) -> None:
        self.said: list[tuple[str, int, bool]] = []
        self.animations: list[tuple[str, bool]] = []

    def say(self, text, *, duration_ms=4000, force=False):
        self.said.append((text, duration_ms, force))

    def show_image(self, *args, **kwargs):
        return False

    def play_animation(self, name, *, loop=False):
        self.animations.append((name, loop))
        return True

    def release_loop(self):
        return True

    def play_event(self, group, variant=None):
        return False

    def notify(self, *args, **kwargs):
        return None

    def texts(self) -> list[str]:
        return [item[0] for item in self.said]


class _Quiet:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def set_quiet(self, seconds):
        self.active = bool(seconds > 0)

    def quiet_active(self):
        return self.active

    def quiet_until(self):
        return None


class _Config(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class FakeSpeech:
    def __init__(self, *, error=None, gate=None) -> None:
        self.error = error
        self.gate = gate
        self.spoken: list[SpeechRequest] = []
        self.synthesized: list[SpeechRequest] = []
        self.secret_calls: list[tuple[str, str, str]] = []
        self.secret_state = {"api_key": False}
        self.provider_infos = (
            SpeechProviderInfo(id="edge", label="Edge 在线语音", online=True),
            SpeechProviderInfo(
                id="doubao", label="豆包", online=True, available=False, reason="auth"
            ),
            SpeechProviderInfo(id="mimo", label="MiMo", online=True),
        )
        self.result = SpeechResult(
            path=Path("chime.mp3"), provider="edge", voice="晓晓"
        )

    def providers(self):
        return self.provider_infos

    def preflight(self, provider=""):
        return provider or "edge"

    def synthesize(self, request):
        self.synthesized.append(request)
        if self.gate is not None:
            self.gate.wait(5)
        if self.error is not None:
            raise self.error
        return self.result

    def speak(self, request, *, on_done=None, on_error=None, **kwargs):
        self.spoken.append(request)
        if self.error is not None:
            if on_error is not None:
                on_error(self.error)
            return "speech-1"
        if on_done is not None:
            on_done(self.result)
        return "speech-1"

    def should_yield(self, moment, *, requester=""):
        return False

    def cancel_owner(self, owner):
        return None

    def stop(self, token=""):
        return None

    def playing(self):
        return False

    def cache_dir(self):
        return Path(".")

    def set_secret(self, provider, field, value):
        self.secret_calls.append((provider, field, value))
        self.secret_state[field] = bool(value)

    def secret_status(self, provider):
        return dict(self.secret_state)


def _context(config=None, *, speech=None, quiet=None):
    presentation = _Presentation()
    quiet_port = quiet or _Quiet()
    ports = HostPorts(
        presentation=presentation,
        config=_Config(config or {}),
        quiet=quiet_port,
        speech=speech,
    )
    context = SimpleNamespace(ports=ports, host=None)
    runtime = runtime_mod.ChimeRuntime(context)
    return runtime, presentation, quiet_port


ENABLED_HOURLY = {
    "voice_chime_enabled": True,
    "voice_chime_schedule": "hourly",
    "voice_chime_quotes": ["自定义台词"],
}

NINE_OCLOCK = datetime(2026, 10, 22, 9, 0, 20)


# ---------------------------------------------------------------- 排期


@pytest.mark.parametrize(
    ("mode", "minute", "due"),
    [
        ("hourly", 0, True),
        ("hourly", 1, False),
        ("every_30", 30, True),
        ("every_30", 31, False),
        ("every_15", 45, True),
        ("every_15", 46, False),
        ("every_5", 55, True),
        ("every_5", 56, False),
        ("every_minute", 37, True),
    ],
)
def test_fixed_schedules_fire_on_their_minutes(mode, minute, due):
    now = NINE_OCLOCK.replace(minute=minute)
    assert bool(schedule.slot_for(now, mode)) is due


def test_custom_times_parse_drops_invalid_entries():
    assert schedule.parse_times("08:00, 9:5, 24:00, abc, 23:59; 7:05") == (
        "07:05",
        "08:00",
        "23:59",
    )
    assert schedule.parse_times(["12:30", "12:30", "00:00"]) == ("00:00", "12:30")
    assert schedule.parse_times("") == ()
    assert schedule.parse_times(None) == ()
    assert schedule.normalize_schedule("EVERY_5") == "every_5"
    assert schedule.normalize_schedule("nope") == "hourly"


def test_custom_schedule_matches_only_listed_times():
    times = schedule.parse_times("09:00, 18:30")
    assert schedule.slot_for(NINE_OCLOCK, "custom", times)
    assert schedule.slot_for(NINE_OCLOCK.replace(minute=1), "custom", times) == ""
    assert schedule.slot_for(NINE_OCLOCK, "custom", ()) == ""


def test_each_slot_fires_once():
    slot = schedule.is_due(NINE_OCLOCK, "hourly", (), "")
    assert slot == "2026-10-22T09:00#hourly"
    assert schedule.is_due(NINE_OCLOCK, "hourly", (), slot) == ""
    later = NINE_OCLOCK.replace(hour=10)
    assert schedule.is_due(later, "hourly", (), slot) == "2026-10-22T10:00#hourly"


def test_next_due_and_seconds_are_strictly_in_the_future():
    assert schedule.next_due(NINE_OCLOCK, "hourly", ()) == datetime(2026, 10, 22, 10, 0)
    assert schedule.seconds_until_due(NINE_OCLOCK, "hourly", ()) == pytest.approx(3580.0)
    nxt = schedule.next_due(datetime(2026, 10, 22, 9, 59, 30), "every_30", ())
    assert nxt == datetime(2026, 10, 22, 10, 0)
    custom = schedule.next_due(datetime(2026, 10, 22, 23, 30), "custom", ("07:05",))
    assert custom == datetime(2026, 10, 23, 7, 5)
    assert schedule.next_due(NINE_OCLOCK, "custom", ()) is None


def test_quote_rotation_is_deterministic_and_changes_by_day():
    pool = tuple(f"台词{i}" for i in range(40))
    first = schedule.quote_day_order(pool, date(2026, 10, 22).toordinal())
    again = schedule.quote_day_order(pool, date(2026, 10, 22).toordinal())
    other = schedule.quote_day_order(pool, date(2026, 10, 23).toordinal())
    assert first == again
    assert first != other
    assert sorted(first) == sorted(pool)

    morning = schedule.pick_quote(pool, NINE_OCLOCK, "hourly", ())
    assert morning == first[9 % len(first)]


def test_quote_text_has_separate_spoken_and_bubble_forms():
    assert quotes.spoken_text(NINE_OCLOCK, "台词") == "现在是上午九点整。台词"
    assert quotes.bubble_text(NINE_OCLOCK, "台词") == "现在上午 09:00。台词"
    assert quotes.spoken_text(NINE_OCLOCK.replace(minute=5)) == "现在上午九点05分"
    assert quotes.normalize_quotes("甲\n\n乙\n甲\n") == ["甲", "乙"]
    assert quotes.pool([]) == quotes.CHINESE_QUOTES
    assert quotes.pool(["自定义"]) == ("自定义",)


# ---------------------------------------------------------------- 运行时


def test_due_tick_speaks_once_with_bubble_and_animation():
    speech = FakeSpeech()
    runtime, presentation, _quiet = _context(ENABLED_HOURLY, speech=speech)

    runtime.tick(now=NINE_OCLOCK)
    runtime.tick(now=NINE_OCLOCK)

    assert len(speech.spoken) == 1
    request = speech.spoken[0]
    assert request.text == "现在是上午九点整。自定义台词"
    assert isinstance(request, SpeechRequest)
    assert presentation.animations == [("悠闲哼歌", False)]
    assert presentation.texts() == ["现在上午 09:00。自定义台词"]
    assert presentation.said[0][2] is True


def test_quiet_mode_suppresses_speech_and_bubble():
    speech = FakeSpeech()
    runtime, presentation, quiet = _context(ENABLED_HOURLY, speech=speech, quiet=_Quiet(True))

    runtime.tick(now=NINE_OCLOCK)

    assert speech.spoken == []
    assert presentation.said == []
    assert quiet.quiet_active() is True


def test_speech_error_is_reported_as_forced_bubble():
    speech = FakeSpeech(error=SpeechError("auth", "bad key"))
    runtime, presentation, _quiet = _context(ENABLED_HOURLY, speech=speech)

    runtime.tick(now=NINE_OCLOCK)

    errors = [item for item in presentation.said if "语音合成失败" in item[0]]
    assert len(errors) == 1
    assert "密钥未配置或已失效" in errors[0][0]
    assert errors[0][2] is True


def test_disabled_or_missing_speech_does_nothing_on_tick():
    speech = FakeSpeech()
    runtime, presentation, _quiet = _context(
        {"voice_chime_enabled": False}, speech=speech
    )
    runtime.tick(now=NINE_OCLOCK)
    assert speech.spoken == [] and presentation.said == []

    runtime, presentation, _quiet = _context(ENABLED_HOURLY, speech=None)
    runtime.tick(now=NINE_OCLOCK)
    assert "语音端口不可用" in presentation.texts()[-1]


def test_precache_starts_at_most_one_thread():
    gate = threading.Event()
    speech = FakeSpeech(gate=gate)
    runtime, _presentation, _quiet = _context(
        {"voice_chime_enabled": True, "voice_chime_schedule": "hourly"}, speech=speech
    )
    # 09:59:30：本分钟不命中，距下次整点 30 秒 → 落在 60 秒预合成窗口内。
    now = datetime(2026, 10, 22, 9, 59, 30)

    runtime.tick(now=now)
    first = runtime._precache_thread
    runtime.tick(now=now)

    assert first is not None
    assert runtime._precache_thread is first
    assert speech.spoken == []
    assert len(speech.synthesized) == 1

    gate.set()
    first.join(5)
    assert first.is_alive() is False


def test_runtime_code_stays_free_of_qt():
    pattern = re.compile(r"^\s*(?:from|import)\s+PySide6", re.M)
    for name in ("runtime.py", "schedule.py", "quotes.py"):
        source = (MOD_DIR / "host" / name).read_text(encoding="utf-8")
        assert pattern.search(source) is None, name
        assert "import pet." not in source, name


# ---------------------------------------------------------------- 设置页


class _Host:
    def __init__(self, config, speech=None):
        self.config = _Config(config)
        self.ports = SimpleNamespace(speech=speech)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page_class():
    manager = feature_mod.FeatureManager(HostPorts())
    manifest, _ = load_manifest(MOD_DIR)
    manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    return manager.settings_pages()[0].factory


def test_settings_page_round_trips_schedule_times_and_quotes(app):
    speech = FakeSpeech()
    host = _Host(
        {
            "voice_chime_enabled": True,
            "voice_chime_schedule": "hourly",
            "voice_chime_times": [],
            "voice_chime_quotes": [],
        },
        speech=speech,
    )
    page = _page_class()(host)
    assert page.dirty() is False

    page.schedule.setCurrentIndex(page.schedule.findData("custom"))
    assert host.config["voice_chime_schedule"] == "custom"
    assert page.times_edit.isEnabled() is True

    page.times_edit.setText("08:00, 25:00, 9:5")
    assert host.config["voice_chime_times"] == ["08:00"]

    page.quotes_edit.setPlainText("第一句\n第二句\n\n第一句")
    assert host.config["voice_chime_quotes"] == ["第一句", "第二句"]

    page.rate.setValue(1.4)
    assert host.config["voice_chime_rate"] == pytest.approx(1.4)
    assert page.dirty() is True

    page.confirm_save()
    assert page.dirty() is False

    page.enabled.setChecked(False)
    page.quotes_edit.setPlainText("改了")
    page.discard_changes()
    assert page.enabled.isChecked() is True
    assert page.quotes_edit.toPlainText() == "第一句\n第二句"
    assert host.config["voice_chime_enabled"] is True
    assert host.config["voice_chime_quotes"] == ["第一句", "第二句"]
    assert page.dirty() is False


def test_settings_page_lists_providers_and_saves_secrets(app):
    speech = FakeSpeech()
    host = _Host({"voice_chime_enabled": False}, speech=speech)
    page = _page_class()(host)

    labels = [page.provider.itemText(index) for index in range(page.provider.count())]
    assert labels[0] == "跟随 Core 设置"
    assert "Edge 在线语音" in labels
    assert any("豆包" in label and "未配置密钥" in label for label in labels)
    assert page._secret_status["doubao"].text() == "未配置"

    page._secret_fields["doubao"].setText("key-123")
    page._save_secret("doubao")
    assert speech.secret_calls == [("doubao", "api_key", "key-123")]
    assert page._secret_fields["doubao"].text() == ""
    assert page._secret_status["doubao"].text() == "已配置"


def test_settings_page_preview_reports_failure(app):
    speech = FakeSpeech(error=SpeechError("network", "boom"))
    page = _page_class()(_Host({"voice_chime_enabled": True}, speech=speech))

    page._preview()

    assert "试听失败" in page.preview_status.text()
    assert "网络连接失败" in page.preview_status.text()
    assert page.preview_button.isEnabled() is True


# ---------------------------------------------------------------- manifest


def test_manifest_and_feature_load_with_menu_and_settings():
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest.id == "voice.chime"
    assert manifest.version == "1.1.1"
    assert manifest.execution == "host-only"
    assert manifest.entrypoint == "host/__init__.py:create_host"

    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    assert diagnostics == []

    menu = {contribution.id for _feature, contribution in manager.menu_contributions()}
    assert menu == {"now"}
    pages = manager.settings_pages()
    assert [page.id for page in pages] == ["chime"]
    assert pages[0].title == "语音报时"
    assert manager.command("voice.chime", "now") is not None
