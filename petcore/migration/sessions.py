"""旧壳聊天会话的迁移。

口径：

- 目录一对一：旧 ``sessions/<character>/`` 与 ``sessions-slot-N/<character>/``
  原样映射到新根的同名目录，槽位语义不变（slot 0 就是 ``sessions``）；
- 只补缺，不覆盖：目标文件已存在一律 ``already_migrated``，新壳可能已经在同一
  id 上续写过，覆盖等于丢掉用户现在的对话；
- 时间口径：旧文件 ``updated_at`` 是 ISO 字符串，新 schema 只收 epoch 秒
  float（``ChatSession.from_dict`` 对字符串直接 ``ValueError``）；naive 时间
  按本地时区解释，解析失败退回文件 mtime 并留痕；
- 旧 schema 的 ``provider_id``/``system_prompt``/``pinned`` 新壳没有落点，
  丢弃但写进 ``detail``，不静默；
- 旧源文件是原始证据：只读、不改、不备份；回滚映射记「目标原本不存在」，
  回滚即删除新文件。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..chat.session_store import (
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_TITLE_CHARS,
    ChatSession,
)
from . import (
    STATUS_ALREADY,
    STATUS_FAILED_VALIDATION,
    STATUS_MIGRATED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
    MigrationContext,
    MigrationEntry,
)

KIND = "sessions"
#: 新壳只认这四种角色；其余一律归一成 user。
ROLES = frozenset({"system", "user", "assistant", "tool"})
#: 新 schema 里没有落点的旧字段；丢弃要计数。
DROP_FIELDS = ("provider_id", "system_prompt", "pinned")
MAX_ACTIVITY_LINES = 40
MAX_ACTIVITY_CHARS = 500
SLOT_PREFIX = "sessions-slot-"


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _safe_session_id(value: Any, fallback: str) -> str:
    """新壳按文件名存取，id 带路径分隔符会写不回来；非法就退回文件名。"""
    for candidate in (str(value or "").strip(), str(fallback or "").strip()):
        if not candidate or candidate in {".", ".."}:
            continue
        if any(char in candidate for char in "/\\:\x00"):
            continue
        return candidate[:128]
    return ""


def _iso_to_epoch(value: Any) -> float | None:
    """旧 ISO 字符串 → epoch 秒；naive 就是写盘机器的本地时间。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.timestamp()


def _fallback_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return time.time()


def _normalise_messages(raw: Any) -> tuple[list[dict[str, Any]], int, int]:
    """消息逐条过新壳的闸门：角色、content 长度、reasoning/activity 上限。

    返回 (消息, 归一角色条数, 丢弃条数)；空 content 的消息新壳读回时也会丢，
    这里先丢并计数，保证写出去的 payload 与读回来的一致。
    """
    messages: list[dict[str, Any]] = []
    role_fixed = 0
    dropped = 0
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in ROLES:
            role = "user"
            role_fixed += 1
        content = str(item.get("content") or "")[:MAX_MESSAGE_CHARS]
        if not content:
            dropped += 1
            continue
        record: dict[str, Any] = {"role": role, "content": content}
        reasoning = str(item.get("reasoning") or "")[:MAX_MESSAGE_CHARS]
        if reasoning:
            record["reasoning"] = reasoning
        activity = item.get("activity")
        if isinstance(activity, list) and activity:
            record["activity"] = [
                str(line)[:MAX_ACTIVITY_CHARS] for line in activity[-MAX_ACTIVITY_LINES:]
            ]
        messages.append(record)
    return messages, role_fixed, dropped


def _convert(raw: dict[str, Any], source: Path) -> tuple[dict[str, Any] | None, str]:
    """旧会话 → 新 schema；第二项是给诊断看的口径说明。"""
    details: list[str] = []
    dropped_fields = [name for name in DROP_FIELDS if name in raw]
    if dropped_fields:
        details.append("dropped:" + ",".join(dropped_fields))
    session_id = _safe_session_id(raw.get("session_id"), source.stem)
    if not session_id:
        return None, "invalid-session-id"
    updated_at = _iso_to_epoch(raw.get("updated_at"))
    if updated_at is None:
        updated_at = _fallback_mtime(source)
        details.append("mtime-fallback")
    messages, role_fixed, dropped_messages = _normalise_messages(raw.get("messages"))
    if role_fixed:
        details.append(f"role-normalized:{role_fixed}")
    if dropped_messages:
        details.append(f"dropped-empty:{dropped_messages}")
    if len(messages) > MAX_MESSAGES:
        details.append(f"trimmed-messages:{len(messages) - MAX_MESSAGES}")
        messages = messages[-MAX_MESSAGES:]
    try:
        payload = ChatSession(
            session_id=session_id,
            title=str(raw.get("title") or "新会话")[:MAX_TITLE_CHARS],
            messages=messages,
            updated_at=updated_at,
        ).as_dict()
        # 写前自检：新壳读不回来就不算迁移成功。
        ChatSession.from_dict(payload)
    except (TypeError, ValueError):
        return None, "invalid-session"
    return payload, ",".join(details)


def _slot_directories(legacy_root: Path) -> list[tuple[int, Path]]:
    """旧壳会话根：``sessions`` 是 slot 0，``sessions-slot-N`` 是子宠槽位。"""
    roots: list[tuple[int, Path]] = []
    for candidate in sorted(legacy_root.glob("sessions*")):
        if not candidate.is_dir():
            continue
        if candidate.name == "sessions":
            roots.append((0, candidate))
            continue
        suffix = candidate.name[len(SLOT_PREFIX) :] if candidate.name.startswith(SLOT_PREFIX) else ""
        if suffix.isdigit():
            roots.append((int(suffix), candidate))
    return roots


def _character_dirs(directory: Path) -> list[Path]:
    try:
        return sorted(item for item in directory.iterdir() if item.is_dir())
    except OSError:
        return []


def _migrate_file(ctx: MigrationContext, source: Path, target: Path) -> MigrationEntry | None:
    if target.exists():
        return ctx.record(
            KIND, STATUS_ALREADY, source=str(source), target=str(target), detail="target-exists"
        )
    raw = _read_object(source)
    if raw is None:
        return ctx.record(
            KIND, STATUS_SKIPPED, source=str(source), target=str(target), detail="invalid-json"
        )
    payload, detail = _convert(raw, source)
    if payload is None:
        return ctx.record(
            KIND, STATUS_FAILED_VALIDATION, source=str(source), target=str(target), detail=detail
        )
    # 旧文件只读；目标原本不存在，回滚就是删掉它。
    ctx.remember_restore(KIND, Path(""), target)
    if not ctx.write_json(KIND, target, payload):
        return None
    return ctx.record(
        KIND,
        STATUS_MIGRATED,
        source=str(source),
        target=str(target),
        detail=detail,
        count=len(payload["messages"]),
    )


def migrate(ctx: MigrationContext) -> list[MigrationEntry]:
    entries: list[MigrationEntry] = []
    found_dirs = False
    for legacy_root in ctx.legacy_roots:
        for slot, directory in _slot_directories(Path(legacy_root)):
            found_dirs = True
            base = "sessions" if slot == 0 else f"sessions-slot-{slot}"
            for character_dir in _character_dirs(directory):
                for source in sorted(character_dir.glob("*.json")):
                    if not source.is_file():
                        continue
                    target = ctx.root / base / character_dir.name / source.name
                    entry = _migrate_file(ctx, source, target)
                    if entry is not None:
                        entries.append(entry)
    if not entries:
        entries.append(
            ctx.record(
                KIND,
                STATUS_NOT_FOUND,
                target=str(ctx.root),
                detail="no-legacy-sessions" if not found_dirs else "no-session-files",
            )
        )
    return entries
