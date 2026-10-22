"""流式对话传输：SSE、非流式回退、取消、错误分类。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from petcore.api.chat import ChatCancelled, build_payload, stream_chat
from petcore.contracts.api import ApiMetadata, ApiRequest
from petcore.net import errors


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "sse"
    seen: list[dict] = []

    def log_message(self, *_args):  # noqa: A003 - 静音
        return

    def do_POST(self):  # noqa: N802 - HTTP 方法名
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw.decode("utf-8"))
        type(self).seen.append(
            {"body": body, "auth": self.headers.get("Authorization", "")}
        )
        if type(self).mode == "auth":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if type(self).mode == "rate":
            self.send_response(429)
            self.send_header("Retry-After", "3")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if type(self).mode == "json":
            payload = {
                "choices": [{"message": {"content": "一次性回答"}, "finish_reason": "stop"}]
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        chunks = ["你", "好", "！"]
        for chunk in chunks:
            payload = {"choices": [{"delta": {"content": chunk}}]}
            line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
            self._write_chunk(line)
        done = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        self._write_chunk(f"data: {json.dumps(done)}\n\n".encode())
        self._write_chunk(b"data: [DONE]\n\n")
        self._write_chunk(b"")

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # 取消时客户端会先关连接，服务端写失败是预期噪声。
        return


@pytest.fixture()
def server():
    _Handler.mode = "sse"
    _Handler.seen = []
    httpd = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _request(httpd, *, model: str = "deepseek-chat") -> ApiRequest:
    metadata = ApiMetadata(
        service_id="test",
        name="Test",
        base_url=f"http://127.0.0.1:{httpd.server_address[1]}",
        model=model,
    )
    return ApiRequest(metadata, "secret-key")


def test_stream_chat_collects_deltas_in_order(server) -> None:
    seen: list[str] = []
    result = stream_chat(
        _request(server),
        [{"role": "user", "content": "在吗"}],
        on_delta=seen.append,
        timeout=5,
    )
    assert result.text == "你好！"
    assert result.chunks == 3
    assert seen == ["你", "好", "！"]
    assert result.cancelled is False
    assert _Handler.seen[0]["auth"] == "Bearer secret-key"
    assert _Handler.seen[0]["body"]["stream"] is True


def test_stream_chat_falls_back_to_one_shot_json(server) -> None:
    _Handler.mode = "json"
    result = stream_chat(_request(server), [{"role": "user", "content": "hi"}], timeout=5)
    assert result.text == "一次性回答"
    assert result.chunks == 1


def test_stream_chat_reports_auth_and_rate_limits(server) -> None:
    _Handler.mode = "auth"
    with pytest.raises(errors.NetworkError) as caught:
        stream_chat(_request(server), [{"role": "user", "content": "x"}], timeout=5)
    assert caught.value.reason == errors.AUTH

    _Handler.mode = "rate"
    with pytest.raises(errors.NetworkError) as caught:
        stream_chat(_request(server), [{"role": "user", "content": "x"}], timeout=5)
    assert caught.value.reason == errors.RATE_LIMIT


def test_stream_chat_stops_on_cancel(server) -> None:
    cancel = threading.Event()

    def on_delta(_delta: str) -> None:
        cancel.set()

    result = stream_chat(
        _request(server),
        [{"role": "user", "content": "x"}],
        on_delta=on_delta,
        cancel=cancel,
        timeout=5,
    )
    assert result.cancelled is True
    assert result.text == "你"


def test_build_payload_respects_model_and_temperature() -> None:
    request = _request(type("S", (), {"server_address": ("127.0.0.1", 1)})(), model="m1")
    payload = build_payload(
        request, [{"role": "user", "content": "hi"}], model="m2", temperature=9
    )
    assert payload["model"] == "m2"
    assert payload["temperature"] == 2.0
    assert payload["stream"] is True
    default = build_payload(request, [])
    assert default["model"] == "m1"


def test_chat_cancelled_is_not_a_network_error() -> None:
    assert issubclass(ChatCancelled, RuntimeError)
