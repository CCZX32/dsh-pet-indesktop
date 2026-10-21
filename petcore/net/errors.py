"""联网失败的稳定分类。

上层（设置页、气泡、mod 端口）只认这几个 reason 字符串，不解析异常文本：
``auth`` / ``rate_limit`` / ``network`` / ``timeout`` / ``protocol``。
服务器响应体一律不读、不回显——它可能原样回显请求里的密钥。
"""

from __future__ import annotations

import ssl
import urllib.error

AUTH = "auth"
RATE_LIMIT = "rate_limit"
NETWORK = "network"
TIMEOUT = "timeout"
PROTOCOL = "protocol"

REASON_TEXT = {
    AUTH: "密钥无效或没有权限",
    RATE_LIMIT: "请求过于频繁，稍后再试",
    NETWORK: "网络不可达",
    TIMEOUT: "连接超时",
    PROTOCOL: "服务端返回了无法识别的响应",
}


class NetworkError(RuntimeError):
    """所有联网失败的基类；``reason`` 是稳定分类。"""

    reason = NETWORK

    def __init__(self, message: str = "", *, reason: str | None = None):
        if reason is not None:
            self.reason = reason
        super().__init__(message or REASON_TEXT.get(self.reason, self.reason))


class NetworkUnreachable(NetworkError):
    reason = NETWORK


class NetworkTimeout(NetworkError):
    reason = TIMEOUT


class HttpStatusError(NetworkError):
    """服务器有明确答复（4xx/5xx）。"""

    reason = PROTOCOL

    def __init__(self, status: int, *, retry_after: float | None = None):
        self.status = int(status)
        self.retry_after = retry_after
        super().__init__(
            f"HTTP {self.status}", reason=classify_http_status(self.status)
        )


class AuthError(HttpStatusError):
    reason = AUTH


class RateLimitError(HttpStatusError):
    reason = RATE_LIMIT


def classify_http_status(status: int) -> str:
    """状态码 → 稳定 reason。"""
    try:
        code = int(status)
    except (TypeError, ValueError):
        return PROTOCOL
    if code in (401, 403):
        return AUTH
    if code == 429:
        return RATE_LIMIT
    if code in (408, 425, 500, 502, 503, 504):
        return NETWORK
    return PROTOCOL


def http_error(exc: urllib.error.HTTPError) -> HttpStatusError:
    """把 ``HTTPError`` 收敛成带分类与 ``Retry-After`` 的异常。"""
    retry_after = None
    try:
        raw = exc.headers.get("Retry-After") if exc.headers is not None else None
        if raw is not None:
            retry_after = max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError, AttributeError):
        retry_after = None
    status = int(getattr(exc, "code", 0) or 0)
    reason = classify_http_status(status)
    if reason == AUTH:
        return AuthError(status, retry_after=retry_after)
    if reason == RATE_LIMIT:
        return RateLimitError(status, retry_after=retry_after)
    return HttpStatusError(status, retry_after=retry_after)


def classify_exception(exc: BaseException) -> str | None:
    """传输异常 → 稳定 reason；无法识别返回 ``None``。"""
    if isinstance(exc, NetworkError):
        return exc.reason
    if isinstance(exc, urllib.error.HTTPError):
        return classify_http_status(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return TIMEOUT if isinstance(exc.reason, TimeoutError) else NETWORK
    if isinstance(exc, (TimeoutError, ssl.SSLError)):
        return TIMEOUT if isinstance(exc, TimeoutError) else NETWORK
    if isinstance(exc, OSError):
        return NETWORK
    return None


def describe(reason: str) -> str:
    return REASON_TEXT.get(str(reason), "未知错误")
