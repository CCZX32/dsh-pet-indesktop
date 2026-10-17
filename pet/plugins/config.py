# -*- coding: utf-8 -*-
"""进程内插件的配置命名空间与旧扁平字段兼容适配。零 Qt。

与上游 ``pet/plugins/config.py`` 的差异只有一处：**命名空间与旧字段可以是两本账**。
本仓库的 Core 配置键有严格的白名单快照（``tests/test_config_schema.py``），为 Phase 2
新增一个顶层 ``plugins`` 键会牵动迁移与设置门；因此命名空间落在独立的插件配置
文件（由 :class:`pet.plugins.runtime.PluginRegistry` 注入一个带 ``data`` / ``save``
的适配器），而节日提醒的 11 个旧扁平键仍读写 Core 的 ``Config``。两边各有唯一
真相，且旧字段原样保留——设置页不需要在本阶段整体重写。
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, Callable

from .capabilities import CapabilitySet


class PluginConfigError(ValueError):
    """插件配置不是可持久化的 JSON 数据。"""


FESTIVAL_LEGACY_CONFIG_MAP: dict[str, str] = {
    "enabled": "festival_reminder_enabled",
    "cn": "festival_reminder_cn",
    "solar_terms": "festival_reminder_solar_terms",
    "west": "festival_reminder_west",
    "mode": "festival_reminder_mode",
    "count": "festival_reminder_count",
    "times": "festival_reminder_times",
    "show_quote": "festival_reminder_show_quote",
    "speak": "festival_reminder_speak",
    "custom_quotes_cn": "festival_custom_quotes_cn",
    "custom_quotes_west": "festival_custom_quotes_west",
}

_MISSING = object()


def _copy_json(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise PluginConfigError("plugin configuration must be JSON serializable") from exc
    return copy.deepcopy(value)


class JsonConfig:
    """一个最小的 ``Config`` 形状适配器：``data`` 字典 + 原子 ``save``。

    插件命名空间写在 Core 配置树之外；这个对象只负责把它落盘，不参与 Core 的
    配置合并、迁移或设置页。路径由 Registry 给出（通常在 ``feature-data`` 下）。
    """

    def __init__(self, path) -> None:
        from pathlib import Path

        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = {}
        return raw if isinstance(raw, dict) else {}

    @property
    def data(self) -> dict[str, Any]:
        if not hasattr(self, "_data"):
            self._data = self._load()
        return self._data

    def save(self) -> bool:
        import os

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        return True


class PluginConfigStore:
    """只允许插件访问自身 ``plugins.<plugin_id>`` 命名空间的配置门面。

    ``legacy_map`` 左侧是插件内部稳定键，右侧是 Core 仍在使用的旧字段；适配器
    会把插件写入镜像回旧字段，并侦测旧字段被设置页/外部进程改写后同步回命名空间。
    """

    def __init__(
        self,
        core_config: Any,
        plugin_id: str,
        *,
        legacy_config: Any | None = None,
        legacy_map: Mapping[str, str] | None = None,
        schema_version: int = 1,
        capabilities: CapabilitySet | None = None,
    ) -> None:
        if not hasattr(core_config, "data") or not isinstance(core_config.data, dict):
            raise TypeError("core_config must expose a dict-like data attribute")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ValueError("plugin_id must be a non-empty string")
        self._core_config = core_config
        self._legacy_config = legacy_config if legacy_config is not None else core_config
        if not hasattr(self._legacy_config, "data") or not isinstance(self._legacy_config.data, dict):
            raise TypeError("legacy_config must expose a dict-like data attribute")
        self.plugin_id = plugin_id
        self.schema_version = int(schema_version)
        self.legacy_map = {str(key): str(value) for key, value in (legacy_map or {}).items()}
        self._capabilities = capabilities
        self._legacy_snapshot: dict[str, Any] = {}
        self._ensure_namespace()

    def _require_read(self) -> None:
        if self._capabilities is not None:
            self._capabilities.require("settings.read")

    def _require_write(self) -> None:
        if self._capabilities is not None:
            self._capabilities.require("settings.write")

    @property
    def _plugins(self) -> dict[str, Any]:
        plugins = self._core_config.data.get("plugins")
        if not isinstance(plugins, dict):
            plugins = {}
            self._core_config.data["plugins"] = plugins
        return plugins

    def _ensure_namespace(self) -> dict[str, Any]:
        plugins = self._plugins
        namespace = plugins.get(self.plugin_id)
        if not isinstance(namespace, dict):
            namespace = {}
        settings = namespace.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        legacy = namespace.get("legacy")
        if not isinstance(legacy, dict):
            legacy = {}
        namespace["schema_version"] = int(namespace.get("schema_version", self.schema_version) or self.schema_version)
        namespace["settings"] = settings
        namespace["legacy"] = legacy
        plugins[self.plugin_id] = namespace

        # 首次创建命名空间时从旧字段复制当前值；旧字段原样留在 legacy，便于
        # 迁移报告与设置页兼容，不把旧用户数据静默丢掉。
        for canonical, legacy_key in self.legacy_map.items():
            current = self._legacy_config.data.get(legacy_key, _MISSING)
            if canonical not in settings and current is not _MISSING:
                settings[canonical] = _copy_json(current)
            if legacy_key not in legacy and current is not _MISSING:
                legacy[legacy_key] = _copy_json(current)
            baseline = legacy.get(legacy_key, current)
            if baseline is not _MISSING:
                self._legacy_snapshot[canonical] = _copy_json(baseline)
        self._refresh_from_legacy()
        return namespace

    @property
    def namespace(self) -> dict[str, Any]:
        self._require_read()
        return copy.deepcopy(self._ensure_namespace())

    @property
    def settings(self) -> dict[str, Any]:
        self._require_read()
        return copy.deepcopy(self._ensure_namespace()["settings"])

    @property
    def legacy(self) -> dict[str, Any]:
        self._require_read()
        return copy.deepcopy(self._ensure_namespace()["legacy"])

    def _namespace_parts(self) -> tuple[dict[str, Any], dict[str, Any]]:
        namespace = self._ensure_namespace()
        return namespace["settings"], namespace["legacy"]

    def _refresh_from_legacy(self) -> None:
        settings, legacy = self._namespace_parts_without_refresh()
        for canonical, legacy_key in self.legacy_map.items():
            current = self._legacy_config.data.get(legacy_key, _MISSING)
            if current is _MISSING:
                continue
            previous = self._legacy_snapshot.get(canonical, _MISSING)
            if previous is _MISSING:
                self._legacy_snapshot[canonical] = _copy_json(current)
                legacy.setdefault(legacy_key, _copy_json(current))
                continue
            if current != previous:
                settings[canonical] = _copy_json(current)
                legacy[legacy_key] = _copy_json(current)
                self._legacy_snapshot[canonical] = _copy_json(current)

    def _namespace_parts_without_refresh(self) -> tuple[dict[str, Any], dict[str, Any]]:
        plugins = self._core_config.data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            self._core_config.data["plugins"] = plugins
        namespace = plugins.setdefault(self.plugin_id, {})
        if not isinstance(namespace, dict):
            namespace = {}
            plugins[self.plugin_id] = namespace
        settings = namespace.setdefault("settings", {})
        legacy = namespace.setdefault("legacy", {})
        if not isinstance(settings, dict):
            settings = {}
            namespace["settings"] = settings
        if not isinstance(legacy, dict):
            legacy = {}
            namespace["legacy"] = legacy
        return settings, legacy

    def get(self, key: str, default: Any = None) -> Any:
        self._require_read()
        self._ensure_namespace()
        self._refresh_from_legacy()
        settings, _ = self._namespace_parts_without_refresh()
        if key in settings:
            return copy.deepcopy(settings[key])
        # 迁移期允许用旧字段名读取，但不把旧字段暴露成写入接口。
        reverse = {legacy: canonical for canonical, legacy in self.legacy_map.items()}
        canonical = reverse.get(key)
        if canonical is not None and canonical in settings:
            return copy.deepcopy(settings[canonical])
        return copy.deepcopy(default)

    def set(self, key: str, value: Any) -> None:
        self._require_write()
        value = _copy_json(value)
        self._ensure_namespace()
        settings, legacy = self._namespace_parts_without_refresh()
        settings[str(key)] = value
        legacy_key = self.legacy_map.get(str(key))
        if legacy_key is not None:
            self._legacy_config.data[legacy_key] = copy.deepcopy(value)
            legacy[legacy_key] = copy.deepcopy(value)
            self._legacy_snapshot[str(key)] = copy.deepcopy(value)

    def update(self, values: Mapping[str, Any]) -> None:
        self._require_write()
        if not isinstance(values, Mapping):
            raise TypeError("plugin config update expects a mapping")
        for key, value in values.items():
            self.set(str(key), value)

    def sync_legacy(self) -> None:
        self._require_write()
        self._sync_legacy_impl()

    def _sync_legacy_impl(self) -> None:
        self._ensure_namespace()
        self._refresh_from_legacy()
        settings, legacy = self._namespace_parts_without_refresh()
        for canonical, legacy_key in self.legacy_map.items():
            if canonical not in settings:
                continue
            value = _copy_json(settings[canonical])
            self._legacy_config.data[legacy_key] = copy.deepcopy(value)
            legacy[legacy_key] = copy.deepcopy(value)
            self._legacy_snapshot[canonical] = copy.deepcopy(value)

    def as_legacy_config(self) -> dict[str, Any]:
        self._require_read()
        self._sync_legacy_impl()
        settings, _ = self._namespace_parts_without_refresh()
        result: dict[str, Any] = {}
        for canonical, legacy_key in self.legacy_map.items():
            if canonical in settings:
                result[legacy_key] = copy.deepcopy(settings[canonical])
        return result

    def migrate(self, migration: Callable[[dict[str, Any]], Mapping[str, Any]] | Mapping[str, Any]) -> None:
        self._require_read()
        current = self.settings
        migrated = migration(current) if callable(migration) else migration
        if not isinstance(migrated, Mapping):
            raise PluginConfigError("plugin migration must return a mapping")
        self.update(migrated)

    def save(self) -> bool:
        self._require_write()
        self._sync_legacy_impl()
        saver = getattr(self._core_config, "save", None)
        if not callable(saver):
            raise TypeError("core_config does not expose save()")
        saved = bool(saver())
        if self._legacy_config is not self._core_config:
            legacy_saver = getattr(self._legacy_config, "save", None)
            if callable(legacy_saver):
                saved = bool(legacy_saver()) and saved
        return saved


__all__ = [
    "FESTIVAL_LEGACY_CONFIG_MAP",
    "JsonConfig",
    "PluginConfigError",
    "PluginConfigStore",
]
