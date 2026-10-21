from __future__ import annotations

import json
from typing import Any

PROTOCOL = "petcore-worker/v1"

HELLO = "hello"
CONFIG_PUSH = "config_push"
READY = "ready"
EVENT = "event"
HEARTBEAT = "heartbeat"
ERROR = "error"
SHUTDOWN = "shutdown"
CANCEL = "cancel"
REQUEST_ID = "request_id"


def encode(message: dict[str, Any]) -> str:
    payload = {"protocol": PROTOCOL, **message}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode(line: str) -> dict[str, Any]:
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("worker message must be a JSON object")
    if message.get("protocol") != PROTOCOL:
        raise ValueError(f"unsupported worker protocol: {message.get('protocol')!r}")
    return message
