from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import paths
from .engine.geometry import SCALE_MAX, SCALE_MIN
from .platform import hotkey_spec

SCHEMA_VERSION = 1

# Settings which belong to the process rather than the pet selected in the
# settings window.  Unknown keys deliberately stay per-pet so new pet-local
# feature settings do not silently become global.
GLOBAL_CONFIG_KEYS = frozenset(
    {
        "active_pets",
        "allow_feature_mods",
        "market_index_url",
        "click_through",
        "hotkey_toggle_pet",
        "hotkey_open_chat",
        "hotkey_look_screen",
        "hotkey_screen_capture",
        "ai_service",
        "ai_model",
        "ai_system_prompt",
        "ai_vision_enabled",
        "ai_temperature",
        "ai_look_screen_auto_open",
        "ai_thinking",
        "ai_reasoning_effort",
        "ai_web_search",
        "ai_web_engine",
        "ai_web_results",
        "ai_web_fetch",
        "ai_proactive_enabled",
        "ai_proactive_whitelist",
        "ai_proactive_dwell_seconds",
        "ai_proactive_change_threshold",
        "ai_proactive_daily_cap",
        "ai_proactive_cooldown_seconds",
        "ai_proactive_min_interval_seconds",
        "ai_proactive_require_idle",
        "ai_proactive_min_idle_seconds",
        "ai_proactive_dry_run",
        "ai_proactive_pre_cue",
        "ai_proactive_sync_chat",
        "ai_agent_enabled",
        "ai_agent_dsh_enabled",
        "ai_agent_events_enabled",
        "ai_agent_custom_agents",
        "ai_agent_animation_enabled",
        "ai_agent_activity_bubbles",
        "ai_agent_done_notice",
        "ai_agent_min_interval_seconds",
        "ai_agent_sound_enabled",
        "ai_agent_sound_volume",
        "ai_agent_sound_cooldown_seconds",
        "ai_agent_sound_start_path",
        "ai_agent_sound_done_path",
        "ai_agent_sound_error_path",
        "island_enabled",
        "island_show_icon",
        "island_show_name",
        "island_show_status",
        "island_info_mode",
        "island_custom_text",
        "island_style",
        "island_opacity",
        "island_accent",
        "island_click_action",
        "island_metrics",
        "island_x",
        "island_y",
        "chat_always_on_top",
        "chat_follow_pet",
        "chat_background",
        "chat_accent",
        "last_settings_page",
        "menu_hidden",
        "menu_layout",
        "menu_order",
        "quick_launch_apps",
        "spawn_inherit_size",
        "spawn_scale",
        "stream_capture_mode",
        "ui_font_size",
        "weather_enabled",
        "weather_city",
        "weather_city_list",
        "weather_city_codes",
        "file_reader_enabled",
        "file_reader_progress_seconds",
        "file_reader_record",
        "speech_backend",
        "speech_fallback",
        "speech_voice",
        "speech_rate",
        "speech_volume",
        "speech_cache_limit",
        "speech_doubao_voice",
        "speech_mimo_voice",
        "voice_chime_enabled",
        "voice_chime_schedule",
        "voice_chime_times",
        "voice_chime_show_bubble",
        "voice_chime_quotes",
        "voice_chime_anim",
        "voice_chime_provider",
        "voice_chime_voice",
        "voice_chime_rate",
        "voice_chime_volume",
        "music_enabled",
        "music_sing_enabled",
        "music_sing_grace_seconds",
        "music_lyric_enabled",
        "music_lyric_lead_seconds",
        "music_lyric_cache_limit",
        "music_lyric_offset_seconds",
        "music_browser_media_enabled",
        "music_player_paths",
        "music_player",
        "music_filter_enabled",
        "music_filter_extra_ids",
    }
)

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
    "market_index_url": "",
    "edge_probe_enabled": False,
    "hotkey_toggle_pet": "",
    "hotkey_open_chat": "",
    "hotkey_look_screen": "",
    "hotkey_screen_capture": "",
    "ai_service": "",
    "ai_model": "",
    "ai_system_prompt": "",
    "ai_vision_enabled": True,
    "ai_temperature": 0.7,
    "ai_look_screen_auto_open": False,
    "ai_thinking": "auto",
    "ai_reasoning_effort": "high",
    "ai_web_search": False,
    "ai_web_engine": "baidu",
    "ai_web_results": 5,
    "ai_web_fetch": True,
    "ai_proactive_enabled": False,
    "ai_proactive_whitelist": [],
    "ai_proactive_dwell_seconds": 45,
    "ai_proactive_change_threshold": 8,
    "ai_proactive_daily_cap": 15,
    "ai_proactive_cooldown_seconds": 300,
    "ai_proactive_min_interval_seconds": 60,
    "ai_proactive_require_idle": False,
    "ai_proactive_min_idle_seconds": 30,
    "ai_proactive_dry_run": False,
    "ai_proactive_pre_cue": True,
    "ai_proactive_sync_chat": True,
    "ai_agent_enabled": False,
    "ai_agent_dsh_enabled": True,
    "ai_agent_events_enabled": True,
    "ai_agent_custom_agents": [],
    "ai_agent_animation_enabled": True,
    "ai_agent_activity_bubbles": True,
    "ai_agent_done_notice": True,
    "ai_agent_min_interval_seconds": 2.0,
    "ai_agent_sound_enabled": False,
    "ai_agent_sound_volume": 0.65,
    "ai_agent_sound_cooldown_seconds": 2.0,
    "ai_agent_sound_start_path": "builtin:agent-start",
    "ai_agent_sound_done_path": "builtin:agent-done",
    "ai_agent_sound_error_path": "builtin:agent-error",
    "island_enabled": False,
    "island_show_icon": True,
    "island_show_name": True,
    "island_show_status": True,
    "island_info_mode": "time",
    "island_custom_text": "",
    "island_style": "dark",
    "island_opacity": 1.0,
    "island_accent": "blue",
    "island_click_action": "expand",
    "island_metrics": ["cpu", "mem"],
    "island_x": None,
    "island_y": None,
    "chat_always_on_top": False,
    "chat_follow_pet": False,
    "chat_background": "",
    "chat_accent": "",
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
    "divination_speak": False,
    "divination_hint": True,
    "festival_enabled": True,
    "festival_reminder_enabled": False,
    "festival_reminder_cn": True,
    "festival_reminder_solar_terms": True,
    "festival_reminder_west": True,
    "festival_reminder_mode": "times",
    "festival_reminder_count": 2,
    "festival_reminder_times": "09:00",
    "festival_reminder_show_quote": True,
    "festival_reminder_speak": False,
    "festival_custom_quotes_cn": "",
    "festival_custom_quotes_west": "",
    "festival_birthday": "",
    "weather_enabled": True,
    "weather_city": "",
    "weather_city_list": [],
    "weather_city_codes": {},
    "file_reader_enabled": True,
    "file_reader_progress_seconds": 15,
    "file_reader_record": True,
    "todo_items": [],
    "todo_reminder_enabled": True,
    "todo_reminder_lead_minutes": 5,
    "todo_reminder_speak": False,
    "voice_chime_enabled": False,
    "voice_chime_schedule": "hourly",
    "voice_chime_times": [],
    "voice_chime_show_bubble": True,
    "voice_chime_quotes": [],
    "voice_chime_anim": "悠闲哼歌",
    "voice_chime_provider": "",
    "voice_chime_voice": "",
    "voice_chime_rate": 1.0,
    "voice_chime_volume": 1.0,
    "music_enabled": True,
    "music_sing_enabled": True,
    "music_sing_grace_seconds": 5.0,
    "music_lyric_enabled": True,
    "music_lyric_lead_seconds": 0.3,
    "music_lyric_cache_limit": 80,
    "music_lyric_offset_seconds": 0.0,
    "music_browser_media_enabled": False,
    "music_player_paths": {},
    "music_player": "",
    "music_filter_enabled": False,
    "music_filter_extra_ids": "",
    "speech_backend": "edge",
    "speech_fallback": "sapi",
    "speech_voice": "",
    "speech_rate": 1.0,
    "speech_volume": 1.0,
    "speech_cache_limit": 200,
    "speech_doubao_voice": "",
    "speech_mimo_voice": "",
    "menu_hidden": [],
    "menu_order": [],
    "menu_layout": None,
    "positions": {},
    "last_settings_page": "general",
}

_LEGACY_IMPORT_KEYS = ("character", "scale", "rx", "ry", "screen_name")

_LEGACY_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "character": ("character",),
    "scale": ("scale",),
    "rx": ("rx",),
    "ry": ("ry",),
    "screen_name": ("screen_name",),
    "body_rx": ("body_rx",),
    "body_ry": ("body_ry",),
    "pos_x": ("pos_x",),
    "pos_y": ("pos_y",),
    "always_on_top": ("always_on_top", "on_top"),
    "click_through": ("click_through", "mouse_through"),
    "playback_speed": ("playback_speed",),
    "animation_gap_seconds": ("animation_gap_seconds", "animation_gap"),
    "self_talk_enabled": ("self_talk_enabled",),
    "self_talk_min": ("self_talk_min", "self_talk_min_interval"),
    "self_talk_max": ("self_talk_max", "self_talk_max_interval"),
    "self_talk_duration": ("self_talk_duration", "self_talk_duration_seconds"),
    "self_talk_texts": ("self_talk_texts",),
    "self_talk_image_dir": ("self_talk_image_dir",),
    "self_talk_image_scale": ("self_talk_image_scale",),
    "self_talk_image_chance": ("self_talk_image_chance",),
    "bubble_text_scale": ("bubble_text_scale",),
    "drag_physics_enabled": ("drag_physics_enabled", "drag_physics"),
    "drop_gravity_enabled": ("drop_gravity_enabled", "drop_gravity"),
    "lock_position": ("lock_position",),
    "shift_drag": ("shift_drag",),
    "click_sound": ("click_sound", "click_sound_enabled"),
    "click_sound_pack": ("click_sound_pack",),
    "volume": ("volume", "click_sound_volume"),
    "collision_enabled": ("collision_enabled",),
    "collision_sound": ("collision_sound", "collision_sound_enabled"),
    "golden_spin_on_click": ("golden_spin_on_click",),
    "golden_spin_direct": ("golden_spin_direct",),
    "edge_probe_enabled": ("edge_probe_enabled",),
    "no_move": ("no_move",),
    "throw_strength": ("throw_strength",),
    "slingshot_enabled": ("slingshot_enabled",),
    "file_feeding_enabled": ("file_feeding_enabled",),
    "quiet_minutes_default": ("quiet_minutes_default",),
    "quick_launch_apps": ("quick_launch_apps",),
    "divination_enabled": ("divination_enabled",),
    "festival_enabled": ("festival_enabled",),
    "todo_items": ("todo_items",),
    "voice_chime_enabled": ("voice_chime_enabled",),
    "music_enabled": ("music_enabled",),
    "ui_font_size": ("ui_font_size",),
    "stream_capture_mode": ("stream_capture_mode",),
    "allow_feature_mods": ("allow_feature_mods",),
    "active_pets": ("active_pets",),
    "spawn_inherit_size": ("spawn_inherit_size",),
    "spawn_scale": ("spawn_scale",),
    "menu_hidden": ("menu_hidden",),
    "menu_order": ("menu_order",),
    "menu_layout": ("menu_layout", "context_menu_layout"),
}


def _map_legacy_data(raw: dict[str, Any]) -> dict[str, Any]:
    """Map known v4/standalone keys without copying secrets or unknown data."""
    mapped: dict[str, Any] = {}
    for new_key, aliases in _LEGACY_KEY_ALIASES.items():
        for old_key in aliases:
            if old_key in raw:
                mapped[new_key] = raw[old_key]
                break
    return mapped


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


#: 灵动岛指标段的合法 id（``gpu`` / ``fps`` 是保留字：本批未实现，配置里留了也不渲染）。
ISLAND_METRIC_IDS = ("network", "cpu", "mem", "gpu", "fps")
ISLAND_METRIC_LIMIT = 8
#: 灵动岛的强调色词表。
ISLAND_ACCENTS = ("blue", "green", "purple", "pink", "orange")


def _island_metrics(value: Any) -> list[str]:
    """清洗 ``island_metrics``：只留合法 id、去重、保序、限长（未知 id 直接丢）。"""
    from .island.segments import BUILTIN_SEGMENT_IDS

    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        metric_id = str(item or "").strip().lower()
        if metric_id in result:
            continue
        if metric_id not in BUILTIN_SEGMENT_IDS or metric_id not in ISLAND_METRIC_IDS:
            continue
        result.append(metric_id)
        if len(result) >= ISLAND_METRIC_LIMIT:
            break
    return result


#: 自定义联动 Agent 条目上限（防配置文件被塞爆）。
AGENT_LINK_MAX_CUSTOM = 8
#: 内置来源占用的 key，自定义条目不得重复。
AGENT_LINK_RESERVED_KEYS = frozenset({"dsh"})


def _agent_link_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if not 1 <= len(key) <= 32 or not key[0].isalnum():
        return ""
    if not all(char.isalnum() or char in "-_" for char in key):
        return ""
    return key


def _agent_links(value: Any) -> list[dict]:
    """清洗 ``ai_agent_custom_agents``：``[{key,name,path}]``，非法条目直接丢弃。"""
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    seen: set[str] = set()
    for item in value:
        if len(result) >= AGENT_LINK_MAX_CUSTOM:
            break
        if not isinstance(item, dict):
            continue
        key = _agent_link_key(item.get("key"))
        if not key or key in seen or key in AGENT_LINK_RESERVED_KEYS:
            continue
        path = str(item.get("path") or "").strip()[:500]
        if not path:
            continue
        name = str(item.get("name") or "").strip()[:50] or key
        seen.add(key)
        result.append({"key": key, "name": name, "path": path})
    return result


_CLICK_SOUND_KINDS = frozenset({"builtin", "file", "folder"})
_CLICK_SOUND_BUILTINS = frozenset({"default", "duck"})
_CLICK_SOUND_PATH_MAX = 500

#: 语音合成的可选后端（与 ``petcore.net.tts.PROVIDER_SPECS`` 的 id 对应；这里不
#: import 那个模块，配置层不该把网络实现拖进启动路径）。
_SPEECH_BACKENDS = frozenset({"edge", "sapi", "doubao", "mimo"})


def _speech_backend(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in _SPEECH_BACKENDS else DEFAULTS["speech_backend"]


def _speech_fallback(value: Any) -> str:
    """空串表示「不要回退」；未知值回落默认后备（``sapi``）。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text if text in _SPEECH_BACKENDS else DEFAULTS["speech_fallback"]


_CHIME_SCHEDULES = ("hourly", "every_30", "every_15", "every_5", "every_minute", "custom")


def _chime_schedule(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in _CHIME_SCHEDULES else DEFAULTS["voice_chime_schedule"]


def _clock_times(value: Any) -> list[str]:
    """``HH:MM`` 列表清洗：非法项丢弃、去重、按时间排序。"""
    items: list[str] = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        text = str(raw or "").strip()
        parts = text.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            items.append(f"{hour:02d}:{minute:02d}")
    return sorted(set(items))


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
            config._migrate_legacy_slots()
        return config

    def _read_legacy(self) -> dict[str, Any]:
        for root in paths.legacy_data_roots():
            path = root / "config.json"
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            imported = _map_legacy_data(raw)
            if imported:
                return self._normalize({**DEFAULTS, **imported})
        return {}

    def _migrate_legacy_slots(self) -> list[str]:
        """Copy old slot profiles into petcore files without touching the source."""
        migrated: list[str] = []
        source_root = None
        for root in paths.legacy_data_roots():
            if (root / "config.json").is_file():
                source_root = root
                break
        if source_root is None:
            return migrated
        backup_root = self.root / "migration-backup"
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / f"{source_root.name}-config.json"
            if not backup.exists():
                shutil.copy2(source_root / "config.json", backup)
        except OSError:
            # A backup failure must not alter the old source or prevent normal
            # startup; the migration report is represented by diagnostics.
            return migrated
        for candidate in sorted(source_root.glob("config-slot-*.json")) + sorted(
            source_root.glob("config-pet-*.json")
        ):
            stem = candidate.stem
            suffix = stem.removeprefix("config-slot-").removeprefix("config-pet-")
            if not suffix.isdigit() or not 0 < int(suffix) < 16:
                continue
            target = self.root / f"config-pet-{int(suffix)}.json"
            if target.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            mapped = _map_legacy_data(raw)
            if not mapped:
                continue
            Config(self.root, mapped, filename=target.name).save()
            migrated.append(target.name)
            try:
                shutil.copy2(candidate, backup_root / f"{source_root.name}-{candidate.name}")
            except OSError:
                pass
        return migrated

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
        normalized["divination_speak"] = _bool(normalized.get("divination_speak"), False)
        normalized["divination_hint"] = _bool(normalized.get("divination_hint"), True)
        normalized["divination_enabled"] = _bool(normalized.get("divination_enabled"), True)
        normalized["festival_enabled"] = _bool(normalized.get("festival_enabled"), True)
        for key in ("festival_reminder_enabled", "festival_reminder_cn", "festival_reminder_solar_terms",
                    "festival_reminder_west", "festival_reminder_show_quote", "festival_reminder_speak"):
            normalized[key] = _bool(normalized.get(key), DEFAULTS[key])
        normalized["festival_reminder_count"] = int(_number(normalized.get("festival_reminder_count"), 2, 1, 6))
        if normalized.get("festival_reminder_mode") not in ("times", "custom"):
            normalized["festival_reminder_mode"] = "times"
        for key in ("festival_reminder_times", "festival_custom_quotes_cn", "festival_custom_quotes_west"):
            normalized[key] = str(normalized.get(key) or "")
        birthday = str(normalized.get("festival_birthday") or "").strip()
        try:
            from datetime import date
            parsed = date.fromisoformat("2000-" + birthday)
            normalized["festival_birthday"] = birthday if parsed.strftime("%m-%d") == birthday else ""
        except ValueError:
            normalized["festival_birthday"] = ""
        normalized["weather_enabled"] = _bool(normalized.get("weather_enabled"), True)
        normalized["weather_city"] = str(normalized.get("weather_city") or "").strip()[:24]
        normalized["weather_city_list"] = _text_list(normalized.get("weather_city_list"))[:12]
        codes = normalized.get("weather_city_codes")
        normalized["weather_city_codes"] = (
            {
                str(key)[:24]: str(value).strip()
                for key, value in codes.items()
                if isinstance(key, str) and isinstance(value, str) and str(value).strip()
            }
            if isinstance(codes, dict)
            else {}
        )
        normalized["file_reader_enabled"] = _bool(
            normalized.get("file_reader_enabled"), True
        )
        normalized["file_reader_progress_seconds"] = int(
            round(
                _number(
                    normalized.get("file_reader_progress_seconds"), 15.0, 5.0, 120.0
                )
            )
        )
        normalized["file_reader_record"] = _bool(
            normalized.get("file_reader_record"), True
        )
        normalized["todo_items"] = _text_list(normalized.get("todo_items"))
        normalized["todo_reminder_enabled"] = _bool(normalized.get("todo_reminder_enabled"), True)
        normalized["todo_reminder_speak"] = _bool(normalized.get("todo_reminder_speak"), False)
        normalized["todo_reminder_lead_minutes"] = int(_number(
            normalized.get("todo_reminder_lead_minutes"), 5, 0, 60))
        normalized["voice_chime_enabled"] = _bool(normalized.get("voice_chime_enabled"), False)
        normalized["music_enabled"] = _bool(normalized.get("music_enabled"), True)
        normalized["voice_chime_schedule"] = _chime_schedule(
            normalized.get("voice_chime_schedule")
        )
        normalized["voice_chime_times"] = _clock_times(
            normalized.get("voice_chime_times")
        )
        normalized["voice_chime_show_bubble"] = _bool(
            normalized.get("voice_chime_show_bubble"), True
        )
        normalized["voice_chime_quotes"] = _text_list(normalized.get("voice_chime_quotes"))
        normalized["voice_chime_anim"] = str(
            normalized.get("voice_chime_anim") or ""
        ).strip()[:64]
        normalized["voice_chime_provider"] = str(
            normalized.get("voice_chime_provider") or ""
        ).strip().lower()[:32]
        normalized["voice_chime_voice"] = str(
            normalized.get("voice_chime_voice") or ""
        ).strip()[:64]
        normalized["voice_chime_rate"] = _number(
            normalized.get("voice_chime_rate"), 1.0, 0.5, 2.0
        )
        normalized["voice_chime_volume"] = _number(
            normalized.get("voice_chime_volume"), 1.0, 0.0, 1.0
        )
        normalized["music_sing_enabled"] = _bool(
            normalized.get("music_sing_enabled"), True
        )
        normalized["music_sing_grace_seconds"] = _number(
            normalized.get("music_sing_grace_seconds"), 5.0, 0.0, 120.0
        )
        normalized["music_lyric_enabled"] = _bool(
            normalized.get("music_lyric_enabled"), True
        )
        normalized["music_lyric_lead_seconds"] = _number(
            normalized.get("music_lyric_lead_seconds"), 0.3, -2.0, 3.0
        )
        normalized["music_lyric_cache_limit"] = int(
            round(
                _number(normalized.get("music_lyric_cache_limit"), 80.0, 1.0, 2000.0)
            )
        )
        normalized["music_lyric_offset_seconds"] = _number(
            normalized.get("music_lyric_offset_seconds"), 0.0, -3.0, 3.0
        )
        normalized["music_browser_media_enabled"] = _bool(
            normalized.get("music_browser_media_enabled"), False
        )
        paths = normalized.get("music_player_paths")
        normalized["music_player_paths"] = (
            {
                str(key): str(value).strip()
                for key, value in paths.items()
                if isinstance(key, str)
                and isinstance(value, str)
                and str(value).strip()
            }
            if isinstance(paths, dict)
            else {}
        )
        normalized["music_player"] = str(
            normalized.get("music_player") or ""
        ).strip()[:32]
        normalized["music_filter_enabled"] = _bool(
            normalized.get("music_filter_enabled"), False
        )
        normalized["music_filter_extra_ids"] = str(
            normalized.get("music_filter_extra_ids") or ""
        ).strip()[:200]
        normalized["speech_backend"] = _speech_backend(normalized.get("speech_backend"))
        normalized["speech_fallback"] = _speech_fallback(normalized.get("speech_fallback"))
        normalized["speech_voice"] = (
            str(normalized.get("speech_voice") or "").strip()[:64]
        )
        normalized["speech_rate"] = _number(
            normalized.get("speech_rate"), 1.0, 0.5, 2.0
        )
        normalized["speech_volume"] = _number(
            normalized.get("speech_volume"), 1.0, 0.0, 1.0
        )
        normalized["speech_cache_limit"] = int(
            round(_number(normalized.get("speech_cache_limit"), 200.0, 10.0, 2000.0))
        )
        normalized["speech_doubao_voice"] = (
            str(normalized.get("speech_doubao_voice") or "").strip()[:64]
        )
        normalized["speech_mimo_voice"] = (
            str(normalized.get("speech_mimo_voice") or "").strip()[:64]
        )
        frameseq = str(normalized.get("frameseq") or "auto")
        normalized["frameseq"] = frameseq if frameseq in {"auto", "off", "only"} else "auto"
        normalized["allow_feature_mods"] = _bool(normalized.get("allow_feature_mods"), False)
        normalized["edge_probe_enabled"] = _bool(normalized.get("edge_probe_enabled"), False)
        normalized["hotkey_toggle_pet"] = hotkey_spec.normalize(
            normalized.get("hotkey_toggle_pet")
        )
        for hotkey_key in (
            "hotkey_open_chat",
            "hotkey_look_screen",
            "hotkey_screen_capture",
        ):
            normalized[hotkey_key] = hotkey_spec.normalize(normalized.get(hotkey_key))
        normalized["ai_service"] = str(normalized.get("ai_service") or "").strip()
        normalized["ai_model"] = str(normalized.get("ai_model") or "").strip()
        normalized["ai_system_prompt"] = str(normalized.get("ai_system_prompt") or "")[:4000]
        normalized["ai_vision_enabled"] = _bool(
            normalized.get("ai_vision_enabled"), True
        )
        normalized["ai_temperature"] = _number(
            normalized.get("ai_temperature"), 0.7, 0.0, 2.0
        )
        normalized["ai_look_screen_auto_open"] = _bool(
            normalized.get("ai_look_screen_auto_open"), False
        )
        thinking = str(normalized.get("ai_thinking") or "auto")
        normalized["ai_thinking"] = (
            thinking if thinking in {"auto", "enabled", "disabled"} else "auto"
        )
        effort = str(normalized.get("ai_reasoning_effort") or "high")
        normalized["ai_reasoning_effort"] = (
            effort if effort in {"low", "high", "max"} else "high"
        )
        normalized["ai_web_search"] = _bool(normalized.get("ai_web_search"), False)
        engine = str(normalized.get("ai_web_engine") or "baidu")
        normalized["ai_web_engine"] = (
            engine if engine in {"baidu", "duckduckgo", "bocha", "tavily"} else "baidu"
        )
        normalized["ai_web_results"] = int(
            _number(normalized.get("ai_web_results"), 5, 1, 10)
        )
        normalized["ai_web_fetch"] = _bool(normalized.get("ai_web_fetch"), True)
        normalized["ai_proactive_enabled"] = _bool(
            normalized.get("ai_proactive_enabled"), False
        )
        normalized["ai_proactive_whitelist"] = [
            rule.strip()[:120]
            for rule in _text_list(normalized.get("ai_proactive_whitelist"))
            if rule.strip()
        ][:50]
        normalized["ai_proactive_dwell_seconds"] = int(
            round(_number(normalized.get("ai_proactive_dwell_seconds"), 45, 15, 600))
        )
        normalized["ai_proactive_change_threshold"] = int(
            round(_number(normalized.get("ai_proactive_change_threshold"), 8, 0, 32))
        )
        normalized["ai_proactive_daily_cap"] = int(
            round(_number(normalized.get("ai_proactive_daily_cap"), 15, 1, 9999))
        )
        normalized["ai_proactive_cooldown_seconds"] = int(
            round(_number(normalized.get("ai_proactive_cooldown_seconds"), 300, 30, 7200))
        )
        normalized["ai_proactive_min_interval_seconds"] = int(
            round(
                _number(normalized.get("ai_proactive_min_interval_seconds"), 60, 30, 3600)
            )
        )
        normalized["ai_proactive_require_idle"] = _bool(
            normalized.get("ai_proactive_require_idle"), False
        )
        normalized["ai_proactive_min_idle_seconds"] = int(
            round(_number(normalized.get("ai_proactive_min_idle_seconds"), 30, 0, 3600))
        )
        normalized["ai_proactive_dry_run"] = _bool(
            normalized.get("ai_proactive_dry_run"), False
        )
        normalized["ai_proactive_pre_cue"] = _bool(
            normalized.get("ai_proactive_pre_cue"), True
        )
        normalized["ai_proactive_sync_chat"] = _bool(
            normalized.get("ai_proactive_sync_chat"), True
        )
        normalized["ai_agent_enabled"] = _bool(normalized.get("ai_agent_enabled"), False)
        normalized["ai_agent_dsh_enabled"] = _bool(
            normalized.get("ai_agent_dsh_enabled"), True
        )
        normalized["ai_agent_events_enabled"] = _bool(
            normalized.get("ai_agent_events_enabled"), True
        )
        normalized["ai_agent_custom_agents"] = _agent_links(
            normalized.get("ai_agent_custom_agents")
        )
        normalized["ai_agent_animation_enabled"] = _bool(
            normalized.get("ai_agent_animation_enabled"), True
        )
        normalized["ai_agent_activity_bubbles"] = _bool(
            normalized.get("ai_agent_activity_bubbles"), True
        )
        normalized["ai_agent_done_notice"] = _bool(
            normalized.get("ai_agent_done_notice"), True
        )
        normalized["ai_agent_min_interval_seconds"] = round(
            _number(normalized.get("ai_agent_min_interval_seconds"), 2.0, 0.5, 10.0), 2
        )
        normalized["ai_agent_sound_enabled"] = _bool(
            normalized.get("ai_agent_sound_enabled"), False
        )
        normalized["ai_agent_sound_volume"] = round(
            _number(normalized.get("ai_agent_sound_volume"), 0.65, 0.0, 1.0), 2
        )
        normalized["ai_agent_sound_cooldown_seconds"] = round(
            _number(normalized.get("ai_agent_sound_cooldown_seconds"), 2.0, 0.0, 10.0), 2
        )
        for _sound_key, _fallback in (
            ("ai_agent_sound_start_path", "builtin:agent-start"),
            ("ai_agent_sound_done_path", "builtin:agent-done"),
            ("ai_agent_sound_error_path", "builtin:agent-error"),
        ):
            normalized[_sound_key] = (
                str(normalized.get(_sound_key) or "").strip()[:500] or _fallback
            )
        normalized["island_enabled"] = _bool(normalized.get("island_enabled"), False)
        for _island_flag in ("island_show_icon", "island_show_name", "island_show_status"):
            normalized[_island_flag] = _bool(normalized.get(_island_flag), True)
        mode = str(normalized.get("island_info_mode") or "time").strip().lower()
        normalized["island_info_mode"] = mode if mode in {"time", "custom"} else "time"
        normalized["island_custom_text"] = str(
            normalized.get("island_custom_text") or ""
        ).strip()[:80]
        style = str(normalized.get("island_style") or "dark").strip().lower()
        normalized["island_style"] = (
            style if style in {"dark", "light", "glass"} else "dark"
        )
        normalized["island_opacity"] = round(
            _number(normalized.get("island_opacity"), 1.0, 0.4, 1.0), 2
        )
        accent = str(normalized.get("island_accent") or "blue").strip().lower()
        normalized["island_accent"] = accent if accent in ISLAND_ACCENTS else "blue"
        action = str(normalized.get("island_click_action") or "expand").strip().lower()
        normalized["island_click_action"] = (
            action if action in {"expand", "toggle_pet"} else "expand"
        )
        normalized["island_metrics"] = _island_metrics(normalized.get("island_metrics"))
        for _axis in ("island_x", "island_y"):
            coordinate = _optional_number(normalized.get(_axis))
            normalized[_axis] = (
                int(round(coordinate))
                if coordinate is not None and abs(coordinate) <= 100000
                else None
            )
        normalized["chat_always_on_top"] = _bool(
            normalized.get("chat_always_on_top"), False
        )
        normalized["chat_follow_pet"] = _bool(normalized.get("chat_follow_pet"), False)
        normalized["chat_background"] = str(
            normalized.get("chat_background") or ""
        ).strip()[:500]
        normalized["chat_accent"] = str(
            normalized.get("chat_accent") or ""
        ).strip()[:32]
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


class ScopedConfig:
    """Route settings reads/writes to a global config or the selected pet.

    The settings UI historically received ``CoreHost`` directly, so pages call
    ``host.config``.  Keeping this small Config-shaped facade lets existing
    pages and feature settings gain correct per-pet behavior without giving
    them a second configuration API.
    """

    def __init__(self, global_config: Config, pet_config: Config | None = None):
        self.global_config = global_config
        self.pet_config = pet_config or global_config

    def _config(self, key: str) -> Config:
        if self.pet_config is self.global_config or key in GLOBAL_CONFIG_KEYS:
            return self.global_config
        return self.pet_config

    @property
    def root(self) -> Path:
        return self.pet_config.root

    @property
    def path(self) -> Path:
        return self.pet_config.path

    @property
    def data(self) -> dict[str, Any]:
        merged = self.global_config.snapshot()
        if self.pet_config is not self.global_config:
            merged.update(self.pet_config.snapshot())
            for key in GLOBAL_CONFIG_KEYS:
                merged[key] = self.global_config.get(key)
        return merged

    def get(self, key: str, default: Any = None) -> Any:
        return self._config(str(key)).get(str(key), default)

    def set(self, key: str, value: Any) -> None:
        self._config(str(key)).set(str(key), value)

    def snapshot(self) -> dict[str, Any]:
        return self.data

    def restore(self, snapshot: dict[str, Any]) -> None:
        if self.pet_config is self.global_config:
            self.global_config.restore(snapshot)
            return
        for key, value in snapshot.items():
            self._config(str(key)).set(str(key), value)

    def save(self) -> None:
        self.global_config.save()
        if self.pet_config is not self.global_config:
            self.pet_config.save()
