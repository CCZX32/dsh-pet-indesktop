from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths
from .engine.geometry import SCALE_MAX, SCALE_MIN
from .platform import hotkey_spec

SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA_VERSION,
    "character": "shenshen",
    "scale": 0.72,
    "always_on_top": True,
    "click_through": False,
    "multi_screen": False,
    "screen_name": None,
    "rx": None,
    "ry": None,
    "body_rx": None,
    "body_ry": None,
    "pos_x": None,
    "pos_y": None,
    "click_sound": True,
    "click_sound_pack": {"kind": "builtin", "id": "default", "path": ""},
    "volume": 0.8,
    "ui_font_size": 13,
    "bubble_text_scale": 100,
    "menu_animation_icons": True,
    "stream_capture_mode": False,
    "easter_egg_enabled": True,
    "easter_egg_title": "鲸鱼娘彩蛋",
    "easter_egg_image_dir": "",
    "easter_egg_image_scale": 100,
    "easter_egg_display": "bubble",
    "frameseq": "auto",
    "allow_feature_mods": False,
    "edge_probe_enabled": False,
    "hotkey_toggle_pet": "",
    "click_squash_enabled": True,
    "click_squash_ms": 220,
    "drag_physics_enabled": False,
    "drop_gravity_enabled": False,
    "throw_strength": "standard",
    "slingshot_enabled": True,
    "collision_enabled": True,
    "collision_sound": True,
    "golden_spin_on_click": False,
    "golden_spin_direct": False,
    "throw_egg_enabled": True,
    "file_feeding_enabled": True,
    "no_move": False,
    "lock_position": False,
    "shift_drag": False,
    "playback_speed": 1.0,
    "animation_gap_seconds": 0.0,
    "anim_weight_idle": 30,
    "anim_weight_turn": 10,
    "anim_weight_act": 40,
    "anim_weight_move": 20,
    "active_pets": [0],
    "spawn_inherit_size": True,
    "spawn_scale": 0.72,
    "self_talk_enabled": False,
    "self_talk_texts": ["今天也要好好休息。"],
    "self_talk_min": 20,
    "self_talk_max": 60,
    "self_talk_duration": 5,
    "self_talk_image_dir": "",
    "self_talk_image_scale": 100,
    "self_talk_image_chance": 30,
    "click_talk_enabled": False,
    "click_talk_texts": ["我在呢。"],
    "quick_launch_apps": [],
    "quiet_minutes_default": 30,
    "network_info_enabled": True,
    "memory_trim_enabled": True,
    "divination_enabled": True,
    "festival_enabled": True,
    "todo_items": [],
    "voice_chime_enabled": False,
    "music_enabled": True,
    "menu_hidden": [],
    "menu_order": [],
    "menu_layout": None,
    "positions": {},
    "last_settings_page": "general",
}

_LEGACY_IMPORT_KEYS = ("character", "scale", "rx", "ry", "screen_name")


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _number(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if number != number:
        return default
    return max(low, min(high, number))


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


_CLICK_SOUND_KINDS = frozenset({"builtin", "file", "folder"})
_CLICK_SOUND_BUILTINS = frozenset({"default", "duck"})
_CLICK_SOUND_PATH_MAX = 500


def _click_sound_pack(value: Any) -> dict[str, str]:
    """清洗点击音效包（总是返回新 dict，不与 DEFAULTS 共享可变对象）。"""
    if not isinstance(value, dict):
        value = {}
    kind = str(value.get("kind") or "builtin").strip().lower()
    if kind not in _CLICK_SOUND_KINDS:
        kind = "builtin"
    pack_id = str(value.get("id") or "default").strip()
    if pack_id not in _CLICK_SOUND_BUILTINS:
        pack_id = "default"
    path = str(value.get("path") or "").strip()[:_CLICK_SOUND_PATH_MAX]
    return {"kind": kind, "id": pack_id, "path": path}


def _pets(value: Any) -> list[int]:
    if not isinstance(value, list):
        return [0]
    slots: list[int] = []
    for item in value:
        try:
            slot = int(item)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= slot < 16 and slot not in slots:
            slots.append(slot)
    if 0 not in slots:
        slots.insert(0, 0)
    return sorted(slots)


def _positions(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for character_id, entry in value.items():
        if not isinstance(entry, dict):
            continue
        record = {
            "screen_name": _optional_text(entry.get("screen_name")),
            "rx": _optional_number(entry.get("rx")),
            "ry": _optional_number(entry.get("ry")),
            "body_rx": _optional_number(entry.get("body_rx")),
            "body_ry": _optional_number(entry.get("body_ry")),
            "pos_x": _optional_number(entry.get("pos_x")),
            "pos_y": _optional_number(entry.get("pos_y")),
        }
        if any(item is not None for item in record.values()):
            cleaned[str(character_id)] = record
    return cleaned


class Config:
    def __init__(self, root: Path, data: dict[str, Any] | None = None, *, filename: str | None = None):
        self.root = Path(root)
        self.path = self.root / filename if filename else paths.config_path(self.root)
        self.data = self._normalize(data if data is not None else dict(DEFAULTS))

    @classmethod
    def load(cls, root: Path, *, portable: bool = False, filename: str | None = None) -> "Config":
        root = Path(root)
        config = cls(root, filename=filename)
        if config.path.exists():
            try:
                raw = json.loads(config.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
            if isinstance(raw, dict):
                config.data = config._normalize({**DEFAULTS, **raw})
                return config
        if filename is not None:
            return config
        legacy = config._read_legacy()
        if legacy:
            config.data.update(legacy)
            config.save()
        return config

    def _read_legacy(self) -> dict[str, Any]:
        path = paths.legacy_config_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        imported: dict[str, Any] = {}
        for key in _LEGACY_IMPORT_KEYS:
            if key in raw and raw[key] is not None:
                imported[key] = raw[key]
        if "mouse_through" in raw:
            imported["click_through"] = bool(raw["mouse_through"])
        return self._normalize({**DEFAULTS, **imported})

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(DEFAULTS)
        normalized.update({key: data[key] for key in DEFAULTS if key in data})
        normalized["schema"] = SCHEMA_VERSION
        normalized["character"] = str(normalized.get("character") or DEFAULTS["character"])
        normalized["scale"] = _number(
            normalized.get("scale"), DEFAULTS["scale"], SCALE_MIN, SCALE_MAX
        )
        normalized["always_on_top"] = _bool(normalized.get("always_on_top"), True)
        normalized["click_through"] = _bool(normalized.get("click_through"), False)
        normalized["multi_screen"] = _bool(normalized.get("multi_screen"), False)
        normalized["screen_name"] = _optional_text(normalized.get("screen_name"))
        normalized["rx"] = _optional_number(normalized.get("rx"))
        normalized["ry"] = _optional_number(normalized.get("ry"))
        normalized["body_rx"] = _optional_number(normalized.get("body_rx"))
        normalized["body_ry"] = _optional_number(normalized.get("body_ry"))
        normalized["pos_x"] = _optional_number(normalized.get("pos_x"))
        normalized["pos_y"] = _optional_number(normalized.get("pos_y"))
        normalized["click_sound"] = _bool(normalized.get("click_sound"), True)
        normalized["click_sound_pack"] = _click_sound_pack(normalized.get("click_sound_pack"))
        normalized["volume"] = _number(normalized.get("volume"), 0.8, 0.0, 1.0)
        normalized["ui_font_size"] = int(
            round(_number(normalized.get("ui_font_size"), 13.0, 10.0, 18.0))
        )
        normalized["bubble_text_scale"] = int(
            round(_number(normalized.get("bubble_text_scale"), 100.0, 50.0, 300.0))
        )
        normalized["menu_animation_icons"] = _bool(
            normalized.get("menu_animation_icons"), True
        )
        normalized["stream_capture_mode"] = _bool(
            normalized.get("stream_capture_mode"), False
        )
        normalized["easter_egg_enabled"] = _bool(normalized.get("easter_egg_enabled"), True)
        title = normalized.get("easter_egg_title")
        normalized["easter_egg_title"] = (
            DEFAULTS["easter_egg_title"] if title is None else str(title)
        ).strip()[:40]
        normalized["easter_egg_image_dir"] = str(
            normalized.get("easter_egg_image_dir") or ""
        ).strip()
        normalized["easter_egg_image_scale"] = int(
            round(_number(normalized.get("easter_egg_image_scale"), 100.0, 50.0, 300.0))
        )
        display = str(normalized.get("easter_egg_display") or "bubble").strip().lower()
        normalized["easter_egg_display"] = (
            display if display in {"bubble", "window"} else "bubble"
        )
        normalized["click_squash_enabled"] = _bool(normalized.get("click_squash_enabled"), True)
        normalized["click_squash_ms"] = _number(normalized.get("click_squash_ms"), 220.0, 80.0, 1000.0)
        normalized["drag_physics_enabled"] = _bool(normalized.get("drag_physics_enabled"), False)
        normalized["drop_gravity_enabled"] = _bool(normalized.get("drop_gravity_enabled"), False)
        strength = str(normalized.get("throw_strength") or "standard")
        normalized["throw_strength"] = strength if strength in {"gentle", "standard", "strong", "crazy"} else "standard"
        normalized["slingshot_enabled"] = _bool(normalized.get("slingshot_enabled"), True)
        normalized["collision_enabled"] = _bool(normalized.get("collision_enabled"), True)
        normalized["collision_sound"] = _bool(normalized.get("collision_sound"), True)
        normalized["golden_spin_on_click"] = _bool(normalized.get("golden_spin_on_click"), False)
        normalized["golden_spin_direct"] = _bool(normalized.get("golden_spin_direct"), False)
        normalized["throw_egg_enabled"] = _bool(normalized.get("throw_egg_enabled"), True)
        normalized["file_feeding_enabled"] = _bool(normalized.get("file_feeding_enabled"), True)
        normalized["no_move"] = _bool(normalized.get("no_move"), False)
        normalized["lock_position"] = _bool(normalized.get("lock_position"), False)
        normalized["shift_drag"] = _bool(normalized.get("shift_drag"), False)
        normalized["playback_speed"] = _number(normalized.get("playback_speed"), 1.0, 0.5, 2.0)
        normalized["animation_gap_seconds"] = _number(
            normalized.get("animation_gap_seconds"), 0.0, 0.0, 3600.0
        )
        for key in (
            "anim_weight_idle",
            "anim_weight_turn",
            "anim_weight_act",
            "anim_weight_move",
        ):
            normalized[key] = int(
                round(_number(normalized.get(key), float(DEFAULTS[key]), 0.0, 100.0))
            )
        normalized["active_pets"] = _pets(normalized.get("active_pets"))
        normalized["spawn_inherit_size"] = _bool(normalized.get("spawn_inherit_size"), True)
        normalized["spawn_scale"] = _number(
            normalized.get("spawn_scale"), DEFAULTS["spawn_scale"], SCALE_MIN, SCALE_MAX
        )
        normalized["self_talk_enabled"] = _bool(normalized.get("self_talk_enabled"), False)
        normalized["self_talk_texts"] = _text_list(normalized.get("self_talk_texts"))
        normalized["self_talk_min"] = _number(normalized.get("self_talk_min"), 20.0, 1.0, 3600.0)
        normalized["self_talk_max"] = _number(normalized.get("self_talk_max"), 60.0, 1.0, 3600.0)
        normalized["self_talk_duration"] = _number(
            normalized.get("self_talk_duration"), 5.0, 1.0, 120.0
        )
        normalized["self_talk_image_dir"] = str(
            normalized.get("self_talk_image_dir") or ""
        ).strip()[:500]
        normalized["self_talk_image_scale"] = int(
            round(_number(normalized.get("self_talk_image_scale"), 100.0, 50.0, 300.0))
        )
        normalized["self_talk_image_chance"] = int(
            round(_number(normalized.get("self_talk_image_chance"), 30.0, 0.0, 100.0))
        )
        normalized["click_talk_enabled"] = _bool(normalized.get("click_talk_enabled"), False)
        normalized["click_talk_texts"] = _text_list(normalized.get("click_talk_texts"))
        apps = normalized.get("quick_launch_apps")
        normalized["quick_launch_apps"] = apps if isinstance(apps, list) else []
        normalized["quiet_minutes_default"] = _number(
            normalized.get("quiet_minutes_default"), 30.0, 1.0, 1440.0
        )
        normalized["network_info_enabled"] = _bool(normalized.get("network_info_enabled"), True)
        normalized["memory_trim_enabled"] = _bool(normalized.get("memory_trim_enabled"), True)
        normalized["divination_enabled"] = _bool(normalized.get("divination_enabled"), True)
        normalized["festival_enabled"] = _bool(normalized.get("festival_enabled"), True)
        normalized["todo_items"] = _text_list(normalized.get("todo_items"))
        normalized["voice_chime_enabled"] = _bool(normalized.get("voice_chime_enabled"), False)
        normalized["music_enabled"] = _bool(normalized.get("music_enabled"), True)
        frameseq = str(normalized.get("frameseq") or "auto")
        normalized["frameseq"] = frameseq if frameseq in {"auto", "off", "only"} else "auto"
        normalized["allow_feature_mods"] = _bool(normalized.get("allow_feature_mods"), False)
        normalized["edge_probe_enabled"] = _bool(normalized.get("edge_probe_enabled"), False)
        normalized["hotkey_toggle_pet"] = hotkey_spec.normalize(
            normalized.get("hotkey_toggle_pet")
        )
        normalized["menu_hidden"] = _text_list(normalized.get("menu_hidden"))
        normalized["menu_order"] = _text_list(normalized.get("menu_order"))
        layout = normalized.get("menu_layout")
        normalized["menu_layout"] = layout if isinstance(layout, dict) else None
        normalized["positions"] = _positions(normalized.get("positions"))
        normalized["last_settings_page"] = str(
            normalized.get("last_settings_page") or "general"
        )
        return normalized

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.data = self._normalize(self.data)

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.data = self._normalize(dict(snapshot))

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        handle, tmp_name = tempfile.mkstemp(
            prefix="config.", suffix=".tmp", dir=str(self.root)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.write("\n")
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))
