from __future__ import annotations

import os
import random
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from petcore import paths
from petcore.config import Config
from petcore.media import sound
from petcore.media.click_sound import (
    MAX_FOLDER_CANDIDATES,
    choose_click_sound,
    resolve_click_sound_candidates,
)

ASSET_ROOT = paths.legacy_asset_root()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _touch(path: Path, payload: bytes = b"RIFF") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_builtin_default_resolves_the_bundled_click_wav() -> None:
    candidates = resolve_click_sound_candidates({"kind": "builtin", "id": "default"}, ASSET_ROOT)
    assert candidates == [ASSET_ROOT / "sounds" / "click.wav"]
    assert candidates[0].is_file()


def test_builtin_duck_prefers_the_converted_wav_files() -> None:
    candidates = resolve_click_sound_candidates({"kind": "builtin", "id": "duck"}, ASSET_ROOT)
    names = [path.name for path in candidates]
    assert names[:2] == ["Ya1.wav", "Ya2.wav"]
    assert all(path.suffix.lower() == ".wav" for path in candidates[:2])
    assert len(candidates) >= 2


def test_builtin_duck_falls_back_to_mp3_when_wav_is_missing(tmp_path: Path) -> None:
    duck = tmp_path / "sounds" / "duck"
    _touch(duck / "B.mp3")
    _touch(duck / "A.mp3")
    _touch(duck / "notes.txt")
    candidates = resolve_click_sound_candidates({"kind": "builtin", "id": "duck"}, tmp_path)
    assert [path.name for path in candidates] == ["A.mp3", "B.mp3"]


def test_file_pack_requires_existing_supported_suffix(tmp_path: Path) -> None:
    clip = _touch(tmp_path / "custom.ogg")
    assert resolve_click_sound_candidates(
        {"kind": "file", "path": str(clip)}, tmp_path
    ) == [clip]
    _touch(tmp_path / "readme.txt")
    assert resolve_click_sound_candidates(
        {"kind": "file", "path": str(tmp_path / "readme.txt")}, tmp_path
    ) == []
    assert resolve_click_sound_candidates(
        {"kind": "file", "path": str(tmp_path / "missing.mp3")}, tmp_path
    ) == []


def test_folder_pack_is_sorted_and_capped(tmp_path: Path) -> None:
    folder = tmp_path / "clips"
    for index in range(MAX_FOLDER_CANDIDATES + 5):
        _touch(folder / f"clip-{index:03d}.wav")
    _touch(folder / "ignore.txt")
    candidates = resolve_click_sound_candidates({"kind": "folder", "path": str(folder)}, tmp_path)
    assert len(candidates) == MAX_FOLDER_CANDIDATES
    assert candidates == sorted(candidates)
    assert candidates[0].name == "clip-000.wav"
    assert candidates[-1].name == f"clip-{MAX_FOLDER_CANDIDATES - 1:03d}.wav"


def test_choose_click_sound_is_reproducible_with_a_seed(tmp_path: Path) -> None:
    candidates = [_touch(tmp_path / f"{index}.wav") for index in range(6)]
    first = choose_click_sound(candidates, random.Random(1234))
    second = choose_click_sound(candidates, random.Random(1234))
    assert first == second
    assert first in candidates
    assert choose_click_sound([], random.Random(1)) is None
    assert choose_click_sound([candidates[2]], random.Random(1)) == candidates[2]


class _FakeAudio:
    def __init__(self) -> None:
        self.volume: float | None = None

    def setVolume(self, volume: float) -> None:  # noqa: N802 - Qt API
        self.volume = float(volume)


class _FakePlayer:
    def __init__(self) -> None:
        self.source = None
        self.audio = None
        self.positions: list[int] = []
        self.plays = 0
        self.stops = 0

    def setAudioOutput(self, audio) -> None:  # noqa: N802 - Qt API
        self.audio = audio

    def setSource(self, source) -> None:  # noqa: N802 - Qt API
        self.source = source

    def setPosition(self, position: int) -> None:  # noqa: N802 - Qt API
        self.positions.append(int(position))

    def play(self) -> None:
        self.plays += 1

    def stop(self) -> None:
        self.stops += 1


def test_sound_player_routes_non_wav_through_media_player(monkeypatch, tmp_path: Path) -> None:
    created: list[tuple[_FakePlayer, _FakeAudio]] = []

    def factory():
        pair = (_FakePlayer(), _FakeAudio())
        created.append(pair)
        return pair

    monkeypatch.setattr(sound, "_new_media_player", factory)
    clip = _touch(tmp_path / "user.mp3", b"ID3")
    player = sound.SoundPlayer(0.5)

    assert player.prepare(clip) is True
    assert player.prepare(clip) is True
    assert len(created) == 1
    assert player._cache == {}
    fake_player, fake_audio = created[0]
    assert fake_player.audio is fake_audio
    assert fake_audio.volume == pytest.approx(0.5)
    assert fake_player.source is not None

    assert player.play(clip) is True
    assert fake_player.positions == [0]
    assert fake_player.plays == 1

    player.set_volume(0.25)
    assert fake_audio.volume == pytest.approx(0.25)
    player.stop_all()
    assert fake_player.stops == 1


def test_sound_player_is_silent_when_multimedia_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sound, "_new_media_player", lambda: None)
    clip = _touch(tmp_path / "user.mp3", b"ID3")
    player = sound.SoundPlayer(0.5)
    assert player.prepare(clip) is False
    assert player.play(clip) is False
    assert player._players == {}


class _StubHost:
    def __init__(self, root: Path):
        self.config = Config(root)
        self.window = None


def test_config_normalizes_the_sound_pack_without_sharing_mutable_state(tmp_path: Path) -> None:
    config = Config(tmp_path)
    config.set("click_sound_pack", {"kind": "bogus", "id": "ghost", "path": "x" * 900})
    assert config.get("click_sound_pack") == {
        "kind": "builtin",
        "id": "default",
        "path": "x" * 500,
    }

    first = Config(tmp_path / "a")
    second = Config(tmp_path / "b")
    first.data["click_sound_pack"]["kind"] = "file"
    assert second.data["click_sound_pack"]["kind"] == "builtin"

    config.set("click_sound_pack", {"kind": "folder", "path": str(tmp_path), "id": "duck"})
    assert config.get("click_sound_pack") == {
        "kind": "folder",
        "id": "duck",
        "path": str(tmp_path),
    }
    assert config.get("easter_egg_enabled") is True
    assert config.get("easter_egg_title") == "鲸鱼娘彩蛋"
    assert config.get("easter_egg_image_dir") == ""


def test_interaction_page_writes_and_discards_the_sound_pack(app, tmp_path: Path) -> None:
    from petcore.ui.settings.page_interaction import InteractionPage

    host = _StubHost(tmp_path)
    page = InteractionPage(host)
    assert page.dirty() is False
    assert page._current()["click_sound_pack"] == {
        "kind": "builtin",
        "id": "default",
        "path": "",
    }

    index = page.sound_pack_combo.findData("builtin:duck")
    page.sound_pack_combo.setCurrentIndex(index)
    assert host.config.get("click_sound_pack") == {
        "kind": "builtin",
        "id": "duck",
        "path": "",
    }
    assert page.dirty() is True

    clip = _touch(tmp_path / "custom.wav")
    page._sound_pack["kind"] = "file"
    page._sound_pack["path"] = str(clip)
    page._sync_sound_pack_widgets()
    page._on_changed()
    assert host.config.get("click_sound_pack")["path"] == str(clip)
    assert page.sound_pack_combo.currentData() == "file"

    page.discard_changes()
    assert host.config.get("click_sound_pack") == {
        "kind": "builtin",
        "id": "default",
        "path": "",
    }
    assert page.sound_pack_combo.currentData() == "builtin:default"
    assert page.dirty() is False
    page.dispose()
