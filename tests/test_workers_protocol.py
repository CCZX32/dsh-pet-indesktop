# -*- coding: utf-8 -*-
"""Worker JSONL 协议契约（host-neutral 重写）。

蓝本 = DLC 分支的 ``tests/test_workers_protocol.py``；本仓库的宿主面没有
agent-link worker，用例里的 worker_id 一律换成中性标识 ``demo-worker``，
并补一条本仓库独有的**导入图契约**：子进程侧只导入 ``pet.workers.protocol``
时不得把 Qt 拉进进程（协议模块的存在意义就是让子进程不背 GUI 依赖）。

本文件是纯逻辑用例：零 Qt、零子进程、零时序。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pet.workers.protocol import (
    MAX_MESSAGE_BYTES,
    MESSAGE_TYPES,
    PROTOCOL,
    WorkerMessage,
    WorkerProtocolError,
    build_message,
    decode_message,
    encode_message,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_protocol_import_pulls_no_qt():
    """子进程侧导入协议模块不得连带加载 PySide6。

    在**新进程**里验（本进程早已被别的用例导入过 Qt，断言等于没验）：
    ``pet/workers/__init__.py`` 用模块级 ``__getattr__`` 惰性暴露 supervisor，
    这条用例就是防止那次惰性失去意义的机器守卫。
    """
    probe = "import sys; import pet.workers.protocol; print('PySide6' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", result.stdout + result.stderr


def test_round_trip_preserves_request_id_timestamp_and_payload() -> None:
    message = build_message(
        "demo-worker",
        "event",
        {"generation": 3, "record": {"event": "task/started", "ok": True}},
        request_id="req-7",
        timestamp="2026-09-25T00:00:00Z",
    )

    decoded = decode_message(encode_message(message))

    assert decoded == message
    assert decoded.as_dict()["request_id"] == "req-7"


def test_encode_rejects_unknown_message_type() -> None:
    with pytest.raises(WorkerProtocolError, match="unknown message type"):
        build_message("demo-worker", "not-supported", {})


def test_payload_must_be_json_serializable() -> None:
    with pytest.raises(WorkerProtocolError, match="not JSON serializable"):
        build_message("demo-worker", "config_push", {"bad": object()})


def test_decode_rejects_invalid_json_protocol_and_message_type() -> None:
    cases = [
        (b"not-json\n", "invalid JSON"),
        (
            json.dumps(
                {
                    "protocol": "pet-worker/v0",
                    "worker_id": "demo-worker",
                    "type": "hello",
                    "timestamp": "2026-09-25T00:00:00Z",
                    "payload": {},
                }
            ).encode()
            + b"\n",
            "unsupported protocol",
        ),
        (
            json.dumps(
                {
                    "protocol": "pet-worker/v1",
                    "worker_id": "demo-worker",
                    "type": "unknown",
                    "timestamp": "2026-09-25T00:00:00Z",
                    "payload": {},
                }
            ).encode()
            + b"\n",
            "unknown message type",
        ),
    ]

    for raw, expected in cases:
        with pytest.raises(WorkerProtocolError, match=expected):
            decode_message(raw)


def test_decode_rejects_multiline_and_oversized_messages() -> None:
    with pytest.raises(WorkerProtocolError, match="exactly one line"):
        decode_message(b'{"protocol":"pet-worker/v1"}\nextra\n')

    with pytest.raises(WorkerProtocolError, match="exactly one line"):
        decode_message('{"protocol":"pet-worker/v1"}\rintra')

    oversized = b"{" + b"x" * (MAX_MESSAGE_BYTES + 1) + b"}\n"
    with pytest.raises(WorkerProtocolError, match="exceeds"):
        decode_message(oversized)

    large = WorkerMessage(
        protocol="pet-worker/v1",
        worker_id="demo-worker",
        type="hello",
        payload={"blob": "x" * MAX_MESSAGE_BYTES},
    )
    with pytest.raises(WorkerProtocolError, match="exceeds"):
        encode_message(large)


def test_trailing_carriage_return_is_tolerated_for_crlf_children() -> None:
    """CRLF（Windows 文本模式子进程）等价于 LF。

    父进程的分行器按 LF 切，所以 ``\\r`` 会单独落到 decode 手里——不兑掉它，
    每个来自 ``print`` 写法的帧都会被当成"多行"拒收（DLC 侧就是这个行为，
    它的用例只写 LF 字节绕开了）。整行带 ``\\n`` 与裸尾 ``\\r`` 两种入口都要认。
    """
    message = build_message("demo-worker", "hello", {}, timestamp="2026-09-25T00:00:00Z")
    body = json.dumps(message.as_dict(), separators=(",", ":"))

    assert decode_message(body + "\r\n") == message
    assert decode_message(body + "\r") == message


def test_decode_requires_object_payload_and_required_fields() -> None:
    base = {
        "protocol": "pet-worker/v1",
        "worker_id": "demo-worker",
        "type": "hello",
        "timestamp": "2026-09-25T00:00:00Z",
    }

    missing_timestamp = dict(base)
    missing_timestamp.pop("timestamp")
    with pytest.raises(WorkerProtocolError, match="timestamp"):
        decode_message(json.dumps(missing_timestamp).encode())

    bad_payload = dict(base, payload=[])
    with pytest.raises(WorkerProtocolError, match="payload must be an object"):
        decode_message(json.dumps(bad_payload).encode())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("worker_id", "   ", "worker_id"),
        ("timestamp", "   ", "timestamp"),
        ("request_id", 123, "request_id"),
    ],
)
def test_protocol_rejects_invalid_scalar_fields(field: str, value: object, message: str) -> None:
    data = build_message("worker", "hello").as_dict()
    data[field] = value

    with pytest.raises(WorkerProtocolError, match=message):
        decode_message(json.dumps(data))


def test_encode_revalidates_directly_constructed_messages() -> None:
    invalid = WorkerMessage("pet-worker/v1", "worker", "hello", timestamp="   ")

    with pytest.raises(WorkerProtocolError, match="timestamp"):
        encode_message(invalid)


@pytest.mark.parametrize("message_type", ["request", "response"])
def test_request_and_response_require_request_id(message_type: str) -> None:
    message = build_message("demo-worker", message_type, {}, request_id="req-1")
    assert decode_message(encode_message(message)) == message

    with pytest.raises(WorkerProtocolError, match="request_id"):
        build_message("demo-worker", message_type, {})

    raw = message.as_dict()
    raw.pop("request_id")
    with pytest.raises(WorkerProtocolError, match="request_id"):
        decode_message(json.dumps(raw))


def test_request_response_message_types_remain_jsonl_compatible() -> None:
    request = build_message(
        "demo-worker",
        "request",
        {"operation": "observe_foreground", "arguments": {"generation": 2}},
        request_id="req-observe",
    )
    response = build_message(
        "demo-worker",
        "response",
        {"operation": "observe_foreground", "status": "ok", "result": {}},
        request_id="req-observe",
    )

    assert decode_message(encode_message(request)).type == "request"
    assert decode_message(encode_message(response)).type == "response"


def test_message_type_set_and_protocol_id_are_pinned() -> None:
    """协议 id 与消息集合是跨进程契约：改名/增删必须是有意识的动作。"""
    assert PROTOCOL == "pet-worker/v1"
    assert MESSAGE_TYPES == frozenset(
        {"hello", "ready", "config_push", "event", "error", "heartbeat", "shutdown", "request", "response"}
    )
