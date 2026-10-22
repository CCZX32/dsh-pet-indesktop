"""通用取数端口的契约与路由策略（P4-a）。

覆盖三件事：

- ``fetch_url`` 的路由顺序、换路由条件、共享 deadline 与体积上限；
- 显式路由请求**不得**污染进程级「固定直连」结论；
- ``CoreHttpPort`` 把 ``NetworkError`` 收敛成只含 reason/status/retry_after 的
  ``HttpError``，并保持 JSON 解码失败的稳定分类。
"""

from __future__ import annotations

import email.message
import json
import urllib.error

import pytest

from petcore.contracts.http import HttpError, HttpRequest
from petcore.net import errors as net_errors
from petcore.net.http import fetch_url, force_direct, reset_transport
from petcore.ui.ports import CoreHttpPort


@pytest.fixture(autouse=True)
def _isolate_transport():
    reset_transport()
    yield
    reset_transport()


class _FakeResponse:
    def __init__(self, body: bytes = b"", status: int = 200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {}
        self._pos = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._body) - self._pos
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.invalid/x", status, "boom", headers, None)


def _factory(by_route: dict[bool, object], calls: list[bool]):
    """按路由返回预设结果；记录实际尝试过的路由顺序。"""

    def build(use_proxy: bool, context):
        calls.append(use_proxy)

        class _Opener:
            def open(self, request, timeout=None, **kwargs):
                outcome = by_route[use_proxy]
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        return _Opener()

    return build


def _clock(values: list[float]):
    pending = list(values)

    def tick() -> float:
        if pending:
            return pending.pop(0)
        return values[-1]

    return tick


# ---------------------------------------------------------------- 路由顺序


def test_prefer_direct_tries_direct_first_then_proxy():
    calls: list[bool] = []
    response = _FakeResponse(b"direct-ok")
    opener = _factory({True: _FakeResponse(b"proxy-ok"), False: response}, calls)

    status, headers, body = fetch_url(
        "https://example.invalid/x", timeout=3.0, prefer_direct=True, opener=opener
    )

    assert (status, body) == (200, b"direct-ok")
    assert calls == [False]


def test_default_route_starts_with_system_proxy():
    calls: list[bool] = []
    opener = _factory({True: _FakeResponse(b"proxy-ok"), False: _FakeResponse(b"direct")}, calls)

    _, _, body = fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert body == b"proxy-ok"
    assert calls == [True]


def test_transport_failure_switches_route_once():
    calls: list[bool] = []
    opener = _factory(
        {True: urllib.error.URLError("proxy down"), False: _FakeResponse(b"direct-ok")},
        calls,
    )

    _, _, body = fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert body == b"direct-ok"
    assert calls == [True, False]


def test_retry_status_switches_route_and_keeps_body():
    calls: list[bool] = []
    opener = _factory({True: _http_error(502), False: _FakeResponse(b"second")}, calls)

    _, _, body = fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert body == b"second"
    assert calls == [True, False]


def test_definitive_statuses_never_switch_route():
    for status in (404, 429, 503):
        calls: list[bool] = []
        opener = _factory({True: _http_error(status), False: _FakeResponse(b"unused")}, calls)

        with pytest.raises(net_errors.HttpStatusError) as caught:
            fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

        assert caught.value.status == status
        assert calls == [True]


def test_rate_limit_keeps_retry_after():
    calls: list[bool] = []
    opener = _factory({True: _http_error(429, "7")}, calls)

    with pytest.raises(net_errors.RateLimitError) as caught:
        fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert caught.value.retry_after == 7.0
    assert calls == [True]


def test_both_routes_failing_raises_network_error():
    calls: list[bool] = []
    opener = _factory(
        {
            True: urllib.error.URLError("proxy down"),
            False: urllib.error.URLError("direct down"),
        },
        calls,
    )

    with pytest.raises(net_errors.NetworkError) as caught:
        fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert caught.value.reason == net_errors.NETWORK
    assert calls == [True, False]


def test_explicit_route_does_not_pin_process_transport():
    calls: list[bool] = []
    opener = _factory({True: urllib.error.URLError("proxy down"), False: _FakeResponse()}, calls)

    fetch_url("https://example.invalid/x", timeout=3.0, opener=opener)

    assert force_direct() is False


# ---------------------------------------------------------------- 预算与体积


def test_shared_deadline_stops_before_second_route():
    calls: list[bool] = []
    opener = _factory({True: urllib.error.URLError("proxy down")}, calls)

    with pytest.raises(net_errors.NetworkTimeout):
        fetch_url(
            "https://example.invalid/x",
            timeout=1.0,
            opener=opener,
            clock=_clock([0.0, 0.0, 5.0]),
        )

    assert calls == [True]


def test_params_are_percent_encoded_by_core():
    seen: list[str] = []

    class _Opener:
        def open(self, request, timeout=None, **kwargs):
            seen.append(request.full_url)
            return _FakeResponse(b"{}")

    fetch_url(
        "https://example.invalid/search",
        params=(("cityname", "鹿城区"), ("q", "a b")),
        timeout=3.0,
        opener=lambda use_proxy, context: _Opener(),
    )

    assert len(seen) == 1
    assert "cityname=%E9%B9%BF%E5%9F%8E%E5%8C%BA" in seen[0]
    assert "q=a+b" in seen[0] or "q=a%20b" in seen[0]


def test_body_is_truncated_to_max_bytes():
    calls: list[bool] = []
    opener = _factory({True: _FakeResponse(b"0123456789")}, calls)

    _, _, body = fetch_url(
        "https://example.invalid/x", timeout=3.0, max_bytes=4, opener=opener
    )

    assert body == b"0123"


def test_body_read_over_deadline_raises_timeout():
    calls: list[bool] = []
    opener = _factory({True: _FakeResponse(b"payload")}, calls)

    with pytest.raises(net_errors.NetworkTimeout):
        fetch_url(
            "https://example.invalid/x",
            timeout=1.0,
            opener=opener,
            clock=_clock([0.0, 0.0, 9.0]),
        )


# ---------------------------------------------------------------- CoreHttpPort


def test_get_json_parses_charset_and_headers():
    calls: list[bool] = []
    payload = json.dumps({"ok": [1, 2]}).encode("utf-8")
    opener = _factory(
        {False: _FakeResponse(payload, headers={"Content-Type": "application/json; charset=utf-8"})},
        calls,
    )
    port = CoreHttpPort(opener=opener)

    assert port.get_json("https://example.invalid/api", prefer_direct=True) == {"ok": [1, 2]}
    assert calls == [False]


def test_get_json_rejects_invalid_payload_as_protocol_error():
    calls: list[bool] = []
    opener = _factory({True: _FakeResponse(b"<html>not json</html>")}, calls)

    with pytest.raises(HttpError) as caught:
        CoreHttpPort(opener=opener).get_json("https://example.invalid/api")

    assert caught.value.reason == "protocol"


def test_request_passes_through_status_headers_and_body():
    calls: list[bool] = []
    opener = _factory({True: _FakeResponse(b"body", status=200, headers={"X-Test": "1"})}, calls)

    response = CoreHttpPort(opener=opener).request(
        HttpRequest(url="https://example.invalid/api", headers=(("Accept", "text/plain"),))
    )

    assert response.status == 200
    assert response.header("x-test") == "1"
    assert response.body == b"body"


def test_request_maps_network_error_to_http_error():
    calls: list[bool] = []
    opener = _factory(
        {
            True: urllib.error.URLError("down"),
            False: urllib.error.URLError("still down"),
        },
        calls,
    )

    with pytest.raises(HttpError) as caught:
        CoreHttpPort(opener=opener).request(HttpRequest(url="https://example.invalid/api"))

    assert caught.value.reason == net_errors.NETWORK
    assert caught.value.status == 0


def test_request_maps_rate_limit_status_and_retry_after():
    calls: list[bool] = []
    opener = _factory({True: _http_error(429, "3")}, calls)

    with pytest.raises(HttpError) as caught:
        CoreHttpPort(opener=opener).request(HttpRequest(url="https://example.invalid/api"))

    assert caught.value.reason == net_errors.RATE_LIMIT
    assert caught.value.status == 429
    assert caught.value.retry_after == 3.0
