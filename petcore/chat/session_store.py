from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 24_000
MAX_TITLE_CHARS = 120


@dataclass
class ChatSession:
    session_id: str
    title: str
    messages: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = 0.0

    def append(self, role: str, content: str) -> None:
        role = str(role or "user").strip().lower()
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        text = str(content or "")[:MAX_MESSAGE_CHARS]
        if not text:
            return
        self.messages.append({"role": role, "content": text})
        if len(self.messages) > MAX_MESSAGES:
            del self.messages[: len(self.messages) - MAX_MESSAGES]
        if not self.title or self.title == "新会话":
            self.title = text.replace("\n", " ").strip()[:MAX_TITLE_CHARS] or "新会话"
        self.updated_at = time.time()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "session_id": self.session_id,
            "title": self.title[:MAX_TITLE_CHARS],
            "messages": list(self.messages[-MAX_MESSAGES:]),
            "updated_at": float(self.updated_at or 0.0),
        }

    @classmethod
    def from_dict(cls, raw: Any, fallback_id: str = "") -> "ChatSession":
        if not isinstance(raw, dict):
            raise ValueError("session must be an object")
        session_id = str(raw.get("session_id") or fallback_id).strip()
        if not session_id:
            raise ValueError("session id is empty")
        messages: list[dict[str, str]] = []
        for item in raw.get("messages", []) if isinstance(raw.get("messages"), list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower()
            content = str(item.get("content") or "")[:MAX_MESSAGE_CHARS]
            if role in {"system", "user", "assistant", "tool"} and content:
                messages.append({"role": role, "content": content})
        return cls(
            session_id=session_id,
            title=str(raw.get("title") or "新会话")[:MAX_TITLE_CHARS],
            messages=messages[-MAX_MESSAGES:],
            updated_at=float(raw.get("updated_at") or 0.0),
        )


class SessionStore:
    """Per-pet chat history store; no credentials or provider state is written."""

    def __init__(self, root: Path, *, slot: int = 0, character_id: str = "default") -> None:
        self.root = Path(root)
        self.slot = max(0, int(slot))
        self.character_id = _safe_component(character_id) or "default"
        self.directory = self.root / (
            "sessions" if self.slot == 0 else f"sessions-slot-{self.slot}"
        ) / self.character_id

    def new_session(self, title: str = "新会话", session_id: str | None = None) -> ChatSession:
        session = ChatSession(
            session_id=_safe_component(session_id or uuid.uuid4().hex) or uuid.uuid4().hex,
            title=str(title or "新会话")[:MAX_TITLE_CHARS],
            updated_at=time.time(),
        )
        self.save(session)
        return session

    def list_sessions(self) -> list[ChatSession]:
        if not self.directory.is_dir():
            return []
        sessions: list[ChatSession] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(ChatSession.from_dict(raw, path.stem))
            except (OSError, ValueError, TypeError):
                continue
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def load(self, session_id: str) -> ChatSession | None:
        path = self._path(session_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ChatSession.from_dict(raw, path.stem)
        except (OSError, ValueError, TypeError):
            return None

    def save(self, session: ChatSession) -> None:
        path = self._path(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(session.as_dict(), ensure_ascii=False, indent=2) + "\n"
        handle, temp_name = tempfile.mkstemp(prefix="session.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _path(self, session_id: str) -> Path:
        safe = _safe_component(session_id)
        if not safe:
            raise ValueError("invalid session id")
        return self.directory / f"{safe}.json"


def _safe_component(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."}:
        return ""
    if any(char in text for char in "/\\:\x00"):
        return ""
    return text[:128]
