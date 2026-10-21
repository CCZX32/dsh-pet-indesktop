"""``<root>/api.json`` 的读写。

文件里只有「服务规格」——**任何密钥都不可能出现在这里**：``ApiService`` 没有
凭据字段，本模块的方法签名里也没有 key。写入用临时文件 + ``os.replace``，
坏文件一次性留一份 ``.bak`` 后当空处理（不覆盖已有备份）。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from .spec import ApiService

SCHEMA_VERSION = 1
FILENAME = "api.json"

logger = logging.getLogger("petcore.api.store")


class ApiStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / FILENAME
        self.backup_path = self.root / f"{FILENAME}.bak"
        self._version = 0
        self._services: dict[str, ApiService] = {}
        self._subscribers: list[Callable[[], None]] = []
        self._loaded = False

    def services(self) -> tuple[ApiService, ...]:
        self._load()
        return tuple(self._services[key] for key in sorted(self._services))

    def get(self, service_id: str) -> ApiService | None:
        self._load()
        return self._services.get(str(service_id))

    def upsert(self, service: ApiService) -> ApiService:
        normalized = service.validate()
        self._load()
        services = dict(self._services)
        services[normalized.service_id] = normalized
        self._commit(services, self._version + 1)
        return normalized

    def remove(self, service_id: str) -> bool:
        self._load()
        key = str(service_id)
        if key not in self._services:
            return False
        services = dict(self._services)
        del services[key]
        self._commit(services, self._version + 1)
        return True

    def version(self) -> int:
        self._load()
        return self._version

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            for index, item in enumerate(self._subscribers):
                if item is callback:
                    del self._subscribers[index]
                    return

        return unsubscribe

    def _notify(self) -> None:
        for callback in tuple(self._subscribers):
            callback()

    def _commit(self, services: dict[str, ApiService], version: int) -> None:
        self._write(services, version)
        self._services = services
        self._version = version
        self._notify()

    def _write(self, services: dict[str, ApiService], version: int) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "version": int(version),
            "services": {
                service_id: services[service_id].as_dict()
                for service_id in sorted(services)
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.root.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            prefix=f"{FILENAME}.", suffix=".tmp", dir=str(self.root)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            raw: Any = json.loads(text)
        except ValueError:
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("services"), dict):
            self._quarantine()
            return
        version = raw.get("version")
        if isinstance(version, int) and not isinstance(version, bool) and version >= 0:
            self._version = version
        for service_id, record in raw["services"].items():
            try:
                service = ApiService.from_dict(str(service_id), record).validate()
            except ValueError:
                logger.warning("api.json 里的服务条目无效，已跳过：%s", service_id)
                continue
            self._services[service.service_id] = service

    def _quarantine(self) -> None:
        logger.warning("api.json 无法解析，按空配置处理：%s", self.path)
        if self.backup_path.exists():
            return
        try:
            self.backup_path.write_bytes(self.path.read_bytes())
        except OSError:
            logger.warning("api.json 备份失败：%s", self.backup_path)
