"""旧壳 ``chat.providers`` 与系统钥匙串凭据的迁移。

口径：

- 一个旧 provider → 一条 ``ApiService``；``service_id`` 取旧 key，不符合新正则
  就规整成安全 slug，并在 ``detail`` 记 ``id-normalized``；
- **密钥永不进 ``api.json``**：``api_key`` / ``api_key_ref`` 一律丢弃，明文值
  既不落盘也不进报告；
- 目标里已有的 ``service_id`` 不覆盖；``api_service_id``（余额选哪个服务）只补缺；
- 新 schema 没有落点的旧字段（``temperature`` / ``max_tokens`` / ``thinking`` /
  ``reasoning_effort`` / ``default_system_prompt`` / ``web_search``）丢弃但写进
  ``detail``，不静默；
- 凭据只在系统钥匙串里搬：service ``dsh-pet-standalone`` → ``dsh-pet-core``，
  读到的值只用于写目标条目，不进日志、不进报告、不进异常文本。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..api.spec import ApiService
from ..api.store import SCHEMA_VERSION as API_SCHEMA_VERSION
from . import (
    STATUS_ALREADY,
    STATUS_MIGRATED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
    STATUS_UNSUPPORTED,
    MigrationContext,
    MigrationEntry,
)

KIND_API = "api"
KIND_CREDENTIALS = "credentials"

API_FILENAME = "api.json"
CONFIG_FILENAME = "config.json"
DEFAULT_CHAT_PATH = "/v1/chat/completions"
DEFAULT_TIMEOUT = 60
MIN_TIMEOUT = 1
MAX_TIMEOUT = 300
MAX_NAME_LENGTH = 128

#: 与 ``petcore/api/spec.py`` 的 ``_SERVICE_ID_RE`` 同口径（那边是私有常量）。
SERVICE_ID_MAX_LENGTH = 96
_SERVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")

#: 新 ``api.json`` 没有落点的旧 provider 字段；出现在旧数据里就要在 detail 点名。
DROPPED_PROVIDER_FIELDS = (
    "temperature",
    "max_tokens",
    "thinking",
    "reasoning_effort",
    "vision_base_url",
)
#: 同样的全局字段（挂在 ``chat`` 上，不挂在单个 provider 上）。
DROPPED_CHAT_FIELDS = ("default_system_prompt", "web_search")

#: 旧壳钥匙串命名。
LEGACY_KEYRING_SERVICE = "dsh-pet-standalone"
KEYRING_SERVICE = "dsh-pet-core"
LEGACY_PROVIDER_REF = "provider/{provider_id}"
LEGACY_VISION_REF = "provider/{provider_id}/vision"
LEGACY_WEB_SEARCH_REF = "websearch/api"
LEGACY_MIMO_REF = "tts/mimo"

#: 新壳钥匙串 owner（account 统一是 ``owner:key``）：
#: ``core.api`` / ``core.websearch`` / ``speech.<provider>``。
API_CREDENTIAL_OWNER = "core.api"
WEB_SEARCH_CREDENTIAL_OWNER = "core.websearch"
SPEECH_CREDENTIAL_OWNER = "speech.{provider}"
MIMO_PROVIDER = "mimo"
SPEECH_API_KEY_FIELD = "api_key"

#: 与 ``petcore/net/websearch.py`` 的 ``search(engine=...)`` 默认值、KEYED_ENGINES 同口径；
#: 迁移层不 import ``petcore.net``（那会把网络栈拖进启动路径）。
DEFAULT_WEB_SEARCH_ENGINE = "baidu"
KEYED_WEB_SEARCH_ENGINES = frozenset({"bocha", "tavily"})


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _clamp_timeout(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, number))


def _service_id(raw: Any) -> tuple[str, bool]:
    """旧 provider key → 合法 ``service_id``；第二项表示是否规整过。"""
    key = str(raw or "").strip()
    if _SERVICE_ID_RE.match(key):
        return key, False
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    slug = slug[:SERVICE_ID_MAX_LENGTH].strip("-")
    return (slug or "service"), True


def _balance_protocol(record: dict[str, Any]) -> str:
    """旧壳的余额只认 DeepSeek 官方口径；其它地址一律 ``none``。"""
    endpoint = str(record.get("base_url") or "").strip().lower()
    _scheme, _separator, remainder = endpoint.partition("://")
    authority = remainder.partition("/")[0]
    host = authority.partition(":")[0]
    return "deepseek" if host == "api.deepseek.com" else "none"


def _build_service(service_id: str, record: dict[str, Any]) -> ApiService:
    model = str(record.get("model") or "").strip()
    vision_model = str(record.get("vision_model") or "").strip()
    same_as_chat = bool(record.get("vision_same_as_chat", True))
    if not vision_model and same_as_chat:
        # 旧壳「视觉同聊天模型」= 用聊天模型识屏；新壳空值等于「不支持视觉」，
        # 照抄会让识屏能力凭空消失，所以这里落成聊天模型名。
        vision_model = model
    name = str(record.get("name") or "").strip() or service_id
    return ApiService(
        service_id=service_id,
        name=name[:MAX_NAME_LENGTH],
        base_url=str(record.get("base_url") or "").strip(),
        chat_path=str(record.get("chat_path") or DEFAULT_CHAT_PATH).strip(),
        model=model,
        vision_model=vision_model,
        verify_ssl=bool(record.get("verify_ssl", True)),
        timeout=_clamp_timeout(record.get("timeout")),
        balance_protocol=_balance_protocol(record),
    )


def _provider_detail(
    provider_id: str,
    service_id: str,
    normalized: bool,
    record: dict[str, Any],
    service: ApiService,
) -> str:
    tokens: list[str] = []
    if normalized:
        tokens.append(f"id-normalized:{provider_id}->{service_id}")
    dropped = [
        name
        for name in DROPPED_PROVIDER_FIELDS
        if record.get(name) not in (None, "")
    ]
    if dropped:
        tokens.append("dropped:" + ",".join(dropped))
    if service.balance_protocol != "none":
        tokens.append(f"balance:{service.balance_protocol}")
    if not str(record.get("vision_model") or "").strip() and service.vision_model:
        tokens.append("vision:same-as-chat")
    return ";".join(tokens)


def _load_services(path: Path) -> tuple[dict[str, dict[str, Any]], int]:
    """读目标 ``api.json``：services 字典 + 上一次的 version。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, 0
    if not isinstance(raw, dict) or not isinstance(raw.get("services"), dict):
        return {}, 0
    services = {
        str(service_id): record
        for service_id, record in raw["services"].items()
        if isinstance(record, dict)
    }
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        version = 0
    return services, version


def _write_services(
    ctx: MigrationContext,
    target: Path,
    services: dict[str, dict[str, Any]],
    version: int,
) -> bool:
    if target.exists():
        if ctx.backup(KIND_API, target, target=target) is None:
            return False
    else:
        ctx.remember_restore(KIND_API, Path(""), target)
    payload = {
        "schema_version": API_SCHEMA_VERSION,
        "version": int(version),
        "services": {service_id: services[service_id] for service_id in sorted(services)},
    }
    return ctx.write_json(KIND_API, target, payload)


def _backup_config(ctx: MigrationContext, path: Path) -> bool:
    """备份 ``config.json``；前面的域已备份过同一份时复用最早那份。

    配置域先跑并会备份同一文件；再复制一遍只会得到「已被配置域改过」的快照，
    回滚就会把迁移结果留在原处。复用已有备份，回滚才真的回到迁移前。
    """
    if ctx.backup_root.is_dir() and not ctx.dry_run:
        suffix = f"-{path.parent.name}-{path.name}"
        for candidate in sorted(ctx.backup_root.iterdir()):
            if candidate.is_file() and candidate.name.endswith(suffix):
                ctx.remember_restore(KIND_API, candidate, path)
                return True
    return ctx.backup(KIND_API, path, target=path) is not None


def _fill_api_service_id(ctx: MigrationContext, service_id: str) -> MigrationEntry | None:
    """``config.json`` 的 ``api_service_id`` 只补缺，已有的用户选择优先。"""
    path = ctx.root / CONFIG_FILENAME
    current: dict[str, Any] = {}
    if path.exists():
        loaded = _read_object(path)
        if loaded is None:
            return ctx.record(
                KIND_API, STATUS_SKIPPED, target=str(path), detail="api_service_id:config-invalid"
            )
        current = loaded
    if str(current.get("api_service_id") or "").strip():
        return ctx.record(
            KIND_API, STATUS_ALREADY, target=str(path), detail="api_service_id"
        )
    if path.exists():
        if not _backup_config(ctx, path):
            return None
    else:
        ctx.remember_restore(KIND_API, Path(""), path)
    if not ctx.write_json(KIND_API, path, {**current, "api_service_id": service_id}):
        return None
    return ctx.record(KIND_API, STATUS_MIGRATED, target=str(path), detail="api_service_id")


def migrate_api(ctx: MigrationContext) -> list[MigrationEntry]:
    """旧 ``chat.providers`` → ``<root>/api.json``（密钥一律不搬）。"""
    entries: list[MigrationEntry] = []
    target = ctx.root / API_FILENAME
    services, version = _load_services(target)
    added = 0
    seen_chat = False
    active_names: list[str] = []

    for legacy_root in ctx.legacy_roots:
        source = legacy_root / CONFIG_FILENAME
        if not source.is_file():
            continue
        raw = _read_object(source)
        if raw is None:
            entries.append(
                ctx.record(KIND_API, STATUS_SKIPPED, source=str(source), detail="invalid-json")
            )
            continue
        chat = raw.get("chat")
        if not isinstance(chat, dict):
            continue
        seen_chat = True
        providers = chat.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        for provider_id in sorted(providers):
            record = providers[provider_id]
            if not isinstance(record, dict):
                entries.append(
                    ctx.record(
                        KIND_API,
                        STATUS_SKIPPED,
                        source=str(source),
                        detail=f"provider-invalid:{provider_id}",
                    )
                )
                continue
            service_id, normalized = _service_id(provider_id)
            if service_id in services:
                detail = "exists" + (";id-normalized" if normalized else "")
                entries.append(
                    ctx.record(
                        KIND_API,
                        STATUS_ALREADY,
                        source=str(source),
                        target=str(target),
                        detail=detail,
                    )
                )
                continue
            try:
                service = _build_service(service_id, record).validate()
            except ValueError as exc:
                # 稳定错误码（如 api_endpoint_insecure）：旧数据不合规，不写坏数据。
                entries.append(
                    ctx.record(
                        KIND_API,
                        STATUS_SKIPPED,
                        source=str(source),
                        target=str(target),
                        detail=f"invalid:{exc}",
                    )
                )
                continue
            services[service.service_id] = service.as_dict()
            added += 1
            entries.append(
                ctx.record(
                    KIND_API,
                    STATUS_MIGRATED,
                    source=str(source),
                    target=str(target),
                    detail=_provider_detail(provider_id, service.service_id, normalized, record, service),
                    count=1,
                )
            )

        dropped_chat = [
            name for name in DROPPED_CHAT_FIELDS if chat.get(name) not in (None, "", {}, [])
        ]
        if dropped_chat:
            entries.append(
                ctx.record(
                    KIND_API,
                    STATUS_SKIPPED,
                    source=str(source),
                    detail="dropped:" + ",".join(dropped_chat),
                )
            )
        active_provider = str(chat.get("active_provider") or "").strip()
        if active_provider:
            active_names.append(active_provider)

    if not seen_chat:
        entries.append(
            ctx.record(KIND_API, STATUS_NOT_FOUND, target=str(target), detail="chat-missing")
        )
        return entries
    if added == 0 and not entries:
        entries.append(
            ctx.record(KIND_API, STATUS_NOT_FOUND, target=str(target), detail="providers-empty")
        )

    if added:
        if not _write_services(ctx, target, services, version + 1):
            return entries

    for active_provider in active_names:
        candidate, _normalized = _service_id(active_provider)
        if candidate in services:
            filled = _fill_api_service_id(ctx, candidate)
            if filled is not None:
                entries.append(filled)
            break
    return entries


@dataclass(frozen=True)
class _CredentialMove:
    """一条钥匙串搬家：旧 ref → 新 ``owner:key``。"""

    old_ref: str
    owner: str
    key: str


class _KeyringUnavailable(RuntimeError):
    """钥匙串/后端不可用；消息固定，不含任何凭据内容。"""


def _open_backend(backend: Any) -> Any:
    if backend is not None:
        return backend
    try:
        import keyring
    except Exception as exc:  # noqa: BLE001 - 没装 keyring 就是「不可用」
        raise _KeyringUnavailable("keyring-unavailable") from exc
    return keyring


def _credential_moves(
    ctx: MigrationContext,
) -> tuple[list[_CredentialMove], list[MigrationEntry]]:
    """按旧 ``config.json`` 推出要搬哪些条目；顺带记「视觉没有落点」的说明。"""
    moves: list[_CredentialMove] = []
    notes: list[MigrationEntry] = []
    vision_seen = False
    for legacy_root in ctx.legacy_roots:
        source = legacy_root / CONFIG_FILENAME
        if not source.is_file():
            continue
        raw = _read_object(source)
        if raw is None:
            continue
        chat = raw.get("chat")
        if not isinstance(chat, dict):
            continue
        providers = chat.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        for provider_id in sorted(providers):
            record = providers[provider_id]
            if not isinstance(record, dict):
                continue
            service_id, _normalized = _service_id(provider_id)
            ref = str(record.get("api_key_ref") or "").strip() or LEGACY_PROVIDER_REF.format(
                provider_id=provider_id
            )
            moves.append(_CredentialMove(ref, API_CREDENTIAL_OWNER, service_id))
            if str(record.get("vision_api_key_ref") or "").strip() or str(
                record.get("vision_api_key") or ""
            ).strip():
                vision_seen = True

        web_search = chat.get("web_search")
        if not isinstance(web_search, dict):
            web_search = {}
        web_ref = str(web_search.get("api_key_ref") or "").strip() or LEGACY_WEB_SEARCH_REF
        engine = str(web_search.get("engine") or "").strip().lower()
        if engine not in KEYED_WEB_SEARCH_ENGINES:
            # 旧壳「引擎 + 一把 Key」：免 Key 引擎时退回默认引擎名，值仍然搬过去，
            # 免得以后换引擎时凭据凭空消失。
            engine = DEFAULT_WEB_SEARCH_ENGINE
        moves.append(_CredentialMove(web_ref, WEB_SEARCH_CREDENTIAL_OWNER, engine))
        moves.append(
            _CredentialMove(
                LEGACY_MIMO_REF,
                SPEECH_CREDENTIAL_OWNER.format(provider=MIMO_PROVIDER),
                SPEECH_API_KEY_FIELD,
            )
        )
    if vision_seen:
        # 新壳没有独立视觉凭据位（识别/识屏都用服务自己的 Key）。
        notes.append(
            ctx.record(KIND_CREDENTIALS, STATUS_SKIPPED, detail="vision-skipped:no-slot")
        )

    unique: list[_CredentialMove] = []
    seen: set[tuple[str, str, str]] = set()
    for move in moves:
        marker = (move.old_ref, move.owner, move.key)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(move)
    return unique, notes


def migrate_credentials(
    ctx: MigrationContext, *, backend: Any = None
) -> list[MigrationEntry]:
    """旧钥匙串 → 新钥匙串；``backend`` 只为测试注入内存假后端。"""
    try:
        backend = _open_backend(backend)
    except _KeyringUnavailable:
        return [
            ctx.record(KIND_CREDENTIALS, STATUS_UNSUPPORTED, detail="keyring-unavailable")
        ]

    moves, notes = _credential_moves(ctx)
    if not moves:
        return [
            ctx.record(KIND_CREDENTIALS, STATUS_NOT_FOUND, detail="chat-missing"),
            *notes,
        ]

    entries: list[MigrationEntry] = []
    try:
        for move in moves:
            account = f"{move.owner}:{move.key}"
            source = f"{LEGACY_KEYRING_SERVICE}:{move.old_ref}"
            target = f"{KEYRING_SERVICE}:{account}"
            stored = backend.get_password(LEGACY_KEYRING_SERVICE, move.old_ref)
            value = "" if stored is None else str(stored)
            if not value:
                entries.append(
                    ctx.record(
                        KIND_CREDENTIALS, STATUS_NOT_FOUND, source=source, target=target, detail="missing"
                    )
                )
                continue
            current = backend.get_password(KEYRING_SERVICE, account)
            if current is not None and str(current):
                entries.append(
                    ctx.record(
                        KIND_CREDENTIALS, STATUS_ALREADY, source=source, target=target, detail="exists"
                    )
                )
                continue
            if not ctx.dry_run:
                backend.set_password(KEYRING_SERVICE, account, value)
                written = backend.get_password(KEYRING_SERVICE, account)
                if not written or str(written) != value:
                    # 后端「写成功但不记」：不能对外说已迁移。
                    raise _KeyringUnavailable("keyring-unavailable")
            entries.append(
                ctx.record(
                    KIND_CREDENTIALS,
                    STATUS_MIGRATED,
                    source=source,
                    target=target,
                    count=1,
                )
            )
    except Exception:  # noqa: BLE001 - 后端坏了整域降级；异常文本可能带值，这里不转发
        return [
            ctx.record(KIND_CREDENTIALS, STATUS_UNSUPPORTED, detail="keyring-unavailable")
        ]
    return entries + notes
