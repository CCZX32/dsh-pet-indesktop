from __future__ import annotations

import email.message
import ssl
import urllib.error

import pytest

from petcore.net import http as http_module
from petcore.net import (
    AuthError,
    HttpStatusError,
    NetworkError,
    NetworkTimeout,
    RateLimitError,
    classify_exception,
    classify_http_status,
    describe,
    force_direct,
    reset_transport,
    urlopen,
)
from petcore.net.errors import (
    NETWORK,
    PROTOCOL,
    RATE_LIMIT,
    TIMEOUT,
    http_error,
)


@pytest.fixture(autouse=True)
def _isolate_transport():
    reset_transport()
    yield
    reset_transport()


class _StubOpener:
    def __init__(self, outcome: object):
        self._outcome = outcome

    def open(self, request, **kwargs):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def _factory(proxy_result: object, direct_result: object, calls: list[bool]):
    def build(use_proxy: bool, context):
        calls.append(use_proxy)
        return _StubOpener(proxy_result if use_proxy else direct_result)

    return build


def _http_error(url: str, status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(url, status, "boom", headers, None)


# ---------------------------------------------------------------- urlopen fallback


def test_proxy_failure_falls_back_to_direct_and_pins_it(monkeypatch):
    sentinel = object()
    calls: list[bool] = []
    factory = _factory(urllib.error.URLError("proxy down"), sentinel, calls)
    monkeypatch.setattr(http_module, "_opener", factory)

    response = urlopen("https://example.invalid/x", timeout=3.0)

    assert response is sentinel
    assert calls == [True, False]
    assert force_direct() is True


def test_pinned_direct_attempts_once_until_reset(monkeypatch):
    sentinel = object()
    calls: list[bool] = []
    first = _factory(urllib.error.URLError("proxy down"), sentinel, calls)
    monkeypatch.setattr(http_module, "_opener", first)
    assert urlopen("https://example.invalid/x", timeout=3.0) is sentinel
    assert force_direct() is True

    second_calls: list[bool] = []
    second = _factory(urllib.error.URLError("should not be used"), sentinel, second_calls)
    monkeypatch.setattr(http_module, "_opener", second)
    assert urlopen("https://example.invalid/x", timeout=3.0) is sentinel
    assert second_calls == [False]

    reset_transport()
    assert force_direct() is False

    third_calls: list[bool] = []
    third = _factory(urllib.error.URLError("proxy down"), sentinel, third_calls)
    monkeypatch.setattr(http_module, "_opener", third)
    assert urlopen("https://example.invalid/x", timeout=3.0) is sentinel
    assert third_calls == [True, False]


def test_http_error_is_raised_without_direct_retry(monkeypatch):
    calls: list[bool] = []
    failure = _http_error("https://example.invalid/x", 503)
    factory = _factory(failure, object(), calls)
    monkeypatch.setattr(http_module, "_opener", factory)

    with pytest.raises(urllib.error.HTTPError) as caught:
        urlopen("https://example.invalid/x", timeout=3.0)

    assert caught.value is failure
    assert calls == [True]
    assert force_direct() is False


def test_both_transports_failing_raises_the_last_exception(monkeypatch):
    calls: list[bool] = []
    proxy_failure = urllib.error.URLError("proxy down")
    direct_failure = urllib.error.URLError("direct down")
    factory = _factory(proxy_failure, direct_failure, calls)
    monkeypatch.setattr(http_module, "_opener", factory)

    with pytest.raises(urllib.error.URLError) as caught:
        urlopen("https://example.invalid/x", timeout=3.0)

    assert caught.value is direct_failure
    assert calls == [True, False]
    assert force_direct() is False


def test_custom_opener_does_not_pin_process_transport():
    sentinel = object()
    calls: list[bool] = []
    factory = _factory(urllib.error.URLError("proxy down"), sentinel, calls)

    assert urlopen("https://example.invalid/x", timeout=3.0, opener=factory) is sentinel
    assert calls == [True, False]
    assert force_direct() is False

    again: list[bool] = []
    factory_again = _factory(urllib.error.URLError("proxy down"), sentinel, again)
    assert urlopen("https://example.invalid/x", timeout=3.0, opener=factory_again) is sentinel
    assert again == [True, False]


# ---------------------------------------------------------------- status classification


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "auth"),
        (403, "auth"),
        (429, RATE_LIMIT),
        (408, NETWORK),
        (425, NETWORK),
        (500, NETWORK),
        (502, NETWORK),
        (503, NETWORK),
        (504, NETWORK),
        (400, PROTOCOL),
        (404, PROTOCOL),
        (422, PROTOCOL),
    ],
)
def test_classify_http_status(status: int, reason: str):
    assert classify_http_status(status) == reason


def test_http_error_builds_rate_limit_with_retry_after():
    converted = http_error(_http_error("https://example.invalid/x", 429, "7"))

    assert isinstance(converted, RateLimitError)
    assert isinstance(converted, HttpStatusError)
    assert converted.status == 429
    assert converted.retry_after == 7.0
    assert converted.reason == "rate_limit"
    assert str(converted) == "HTTP 429"


def test_http_error_builds_auth_error():
    converted = http_error(_http_error("https://example.invalid/x", 401))

    assert isinstance(converted, AuthError)
    assert converted.status == 401
    assert converted.retry_after is None
    assert converted.reason == "auth"


def test_http_error_without_retry_after_header_is_none():
    converted = http_error(_http_error("https://example.invalid/x", 500))

    assert type(converted) is HttpStatusError
    assert converted.retry_after is None
    assert converted.reason == NETWORK


# ---------------------------------------------------------------- exception classification


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (urllib.error.URLError(TimeoutError()), TIMEOUT),
        (urllib.error.URLError(ConnectionRefusedError()), NETWORK),
        (TimeoutError(), TIMEOUT),
        (ssl.SSLError(), NETWORK),
        (ConnectionResetError(), NETWORK),
    ],
)
def test_classify_exception_transport_failures(exc: BaseException, reason: str):
    assert classify_exception(exc) == reason


def test_classify_exception_preserves_network_error_reason():
    assert classify_exception(NetworkTimeout("late")) == TIMEOUT
    assert classify_exception(NetworkError("odd", reason=PROTOCOL)) == PROTOCOL
    assert classify_exception(NetworkError("plain")) == NETWORK


def test_classify_exception_unknown_returns_none():
    assert classify_exception(ValueError("nope")) is None


# ---------------------------------------------------------------- describe


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("auth", "密钥无效或没有权限"),
        ("rate_limit", "请求过于频繁，稍后再试"),
        ("network", "网络不可达"),
        ("timeout", "连接超时"),
        ("protocol", "服务端返回了无法识别的响应"),
        ("made-up", "未知错误"),
    ],
)
def test_describe_returns_chinese_sentence(reason: str, text: str):
    assert describe(reason) == text
    assert describe(reason).strip()


def test_network_error_uses_the_reason_when_message_is_empty() -> None:
    from petcore.net.errors import REASON_TEXT, TIMEOUT, NetworkError

    exc = NetworkError("", reason=TIMEOUT)
    assert exc.reason == TIMEOUT
    assert str(exc) == REASON_TEXT[TIMEOUT]


def test_normalizing_http_error_closes_its_body():
    import io

    body = io.BytesIO(b"sensitive upstream response")
    raw = urllib.error.HTTPError("https://example.invalid/x", 429, "limited", {"Retry-After": "3"}, body)
    converted = http_error(raw)
    assert converted.status == 429
    assert converted.retry_after == 3
    assert body.closed
