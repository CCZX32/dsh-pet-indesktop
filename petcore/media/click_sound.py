from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a"})

#: 自定义文件夹一次最多取多少个候选（防止用户误选巨大目录）。
MAX_FOLDER_CANDIDATES = 128

_DEFAULT_PACK = {"kind": "builtin", "id": "default", "path": ""}


def _pack_fields(pack) -> tuple[str, str, str]:
    if not isinstance(pack, dict):
        pack = _DEFAULT_PACK
    kind = str(pack.get("kind") or "builtin").strip().lower()
    pack_id = str(pack.get("id") or "default").strip()
    path = str(pack.get("path") or "").strip()
    return kind, pack_id, path


def _duck_candidates(duck_dir: Path) -> list[Path]:
    """小黄鸭音效：wav 优先，同名 mp3 只在缺 wav 时补位（转码后不会重复播两遍）。"""
    if not duck_dir.is_dir():
        return []
    try:
        entries = sorted(duck_dir.iterdir())
    except OSError:
        return []
    wavs = [path for path in entries if path.is_file() and path.suffix.lower() == ".wav"]
    covered = {path.stem.lower() for path in wavs}
    mp3s = [
        path
        for path in entries
        if path.is_file()
        and path.suffix.lower() == ".mp3"
        and path.stem.lower() not in covered
    ]
    return wavs + mp3s



class ClickSoundPair:
    """按下/释放音效的 token 配对器。

    目前内置音效包只有 release 音；因此 ``begin`` 在没有按下候选时只
    登记 token，释放时仍播放原有 click 音。自定义包可传入 press 候选，
    失焦、拖拽和关闭则通过 ``cancel`` 丢弃 token，重复释放不会重播。
    """

    def __init__(self, play, *, rng: random.Random | None = None):
        self._play = play
        self._rng = rng
        self._next = 0
        self._active: set[int] = set()

    @property
    def active_count(self) -> int:
        return len(self._active)

    def begin(self, press_candidates: Sequence[Path] = ()) -> int:
        self._next += 1
        token = self._next
        self._active.add(token)
        chosen = choose_click_sound(press_candidates, rng=self._rng)
        if chosen is not None:
            self._play(chosen)
        return token

    def release(self, token: int | None, release_candidates: Sequence[Path] = ()) -> bool:
        if token is None or token not in self._active:
            return False
        self._active.remove(token)
        chosen = choose_click_sound(release_candidates, rng=self._rng)
        if chosen is None:
            return False
        return bool(self._play(chosen))

    def cancel(self, token: int | None) -> bool:
        if token is None or token not in self._active:
            return False
        self._active.remove(token)
        return True

    def cancel_all(self) -> None:
        self._active.clear()

def resolve_click_sound_candidates(pack, asset_root: Path) -> list[Path]:
    """按音效包配置解析候选音频文件（不存在/不支持一律返回空表）。"""
    kind, pack_id, path_text = _pack_fields(pack)
    sounds = Path(asset_root) / "sounds"
    if kind == "builtin":
        if pack_id == "duck":
            return _duck_candidates(sounds / "duck")
        click = sounds / "click.wav"
        return [click] if click.is_file() else []
    if kind == "file":
        if not path_text:
            return []
        candidate = Path(path_text).expanduser()
        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES:
            return [candidate]
        return []
    if kind == "folder":
        if not path_text:
            return []
        folder = Path(path_text).expanduser()
        if not folder.is_dir():
            return []
        try:
            files = sorted(
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
            )
        except OSError:
            return []
        return files[:MAX_FOLDER_CANDIDATES]
    return []


def choose_click_sound(candidates: Sequence[Path], rng: random.Random | None = None) -> Path | None:
    """从候选列表里挑一个（传入 rng 可复现）；空表返回 None。"""
    items = list(candidates or ())
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    picker = rng if rng is not None else random
    return picker.choice(items)
