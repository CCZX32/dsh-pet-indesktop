"""带「系统代理不通就直连」兜底的 urlopen（移植自 `pet/http_util.py`）。

背景：Windows 的系统代理常被加速器/VPN 打开，进程退出后代理解析仍然生效，
`urllib.request.urlopen` 会照着死代理走 ⇒ 所有请求 `ConnectionRefused`。
这里的口径与主分支逐条一致：

- 先按系统代理试一次（尊重用户的加速器/VPN）；
- 只在**传输失败**时改直连重试，并把结论固化在进程内；
- 服务器明确答复（`HTTPError` 4xx/5xx）不重试也不换路——链路本来就是通的。
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any, Callable

from .errors import (
    NETWORK,
    TIMEOUT,
    HttpStatusError,
    NetworkError,
    NetworkTimeout,
    classify_exception,
    http_error,
)

logger = logging.getLogger("petcore.net.http")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 4_000_000
DEFAULT_FALLBACK_STATUSES = (500, 502, 504)
_READ_CHUNK = 65_536


def is_https_url(url: str) -> bool:
    parts = urlsplit(str(url))
    return parts.scheme.lower() == "https" and bool(parts.hostname)


def is_allowed_https_url(url: str, hosts) -> bool:
    parts = urlsplit(str(url))
    return parts.scheme.lower() == "https" and (parts.hostname or "").lower() in {
        str(host).lower() for host in hosts
    }

_force_direct = False
_direct_opener: urllib.request.OpenerDirector | None = None

OpenerFactory = Callable[[bool, Any], urllib.request.OpenerDirector]


def _opener(use_proxy: bool, context=None) -> urllib.request.OpenerDirector:
    """取 opener：``use_proxy=False`` 强制直连；``context`` 为 SSL 上下文。"""
    handlers: list[Any] = []
    if not use_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    if not handlers:
        return urllib.request.build_opener()
    if not use_proxy and context is None:
        global _direct_opener
        if _direct_opener is None:
            _direct_opener = urllib.request.build_opener(*handlers)
        return _direct_opener
    return urllib.request.build_opener(*handlers)


def force_direct() -> bool:
    """本进程是否已确定「系统代理不可用、固定直连」（诊断/测试用）。"""
    return _force_direct


def reset_transport() -> None:
    """复位传输层结论（测试隔离；网络环境变化后可显式重试代理）。"""
    global _force_direct, _direct_opener
    _force_direct = False
    _direct_opener = None


def urlopen(
    request,
    *,
    timeout: float,
    context=None,
    opener: OpenerFactory | None = None,
    **kwargs,
):
    """同 :func:`urllib.request.urlopen`，但代理连不上时自动改直连重试一次。

    ``opener`` 是测试接缝：给定时用它构造 opener，且不固化进程级结论。
    ``HTTPError`` 原样抛出；两种方式都失败时抛最后一次的传输异常。
    """
    global _force_direct
    attempts = (False,) if _force_direct else (True, False)
    build = opener or _opener
    last_exc: Exception | None = None
    for use_proxy in attempts:
        try:
            response = build(use_proxy, context).open(request, timeout=timeout, **kwargs)
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001 - 传输失败：换下一种方式再试
            last_exc = exc
            continue
        if opener is None and not use_proxy and not _force_direct:
            _force_direct = True
            logger.info(
                "网络请求改走直连：系统代理不可用（%s）", type(last_exc).__name__
            )
        return response
    assert last_exc is not None
    raise last_exc


def build_request(
    url: str,
    *,
    method: str = "GET",
    headers: tuple[tuple[str, str], ...] = (),
    body: bytes = b"",
    params: tuple[tuple[str, str], ...] = (),
) -> urllib.request.Request:
    """构造一次请求；每次换路由都重新构造，避免复用被 OpenDirector 改过的对象。"""
    target = str(url)
    if params:
        query = urllib.parse.urlencode([(str(k), str(v)) for k, v in params])
        if query:
            separator = "&" if "?" in target else "?"
            target = f"{target}{separator}{query}"
    data = body if body else None
    request = urllib.request.Request(target, data=data, method=str(method or "GET"))
    for key, value in headers:
        request.add_header(str(key), str(value))
    return request


def fetch_url(
    url: str,
    *,
    method: str = "GET",
    headers: tuple[tuple[str, str], ...] = (),
    body: bytes = b"",
    params: tuple[tuple[str, str], ...] = (),
    timeout: float = DEFAULT_TIMEOUT,
    prefer_direct: bool = False,
    retry_statuses: tuple[int, ...] = DEFAULT_FALLBACK_STATUSES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    context=None,
    opener: OpenerFactory | None = None,
    clock: Callable[[], float] = time.monotonic,
):
    """按显式路由取数，返回 ``(status, headers, body)``。

    与 :func:`urlopen` 的区别：**不改写进程级「固定直连」结论**。天气这类
    「国内站直连、海外站走代理」的功能要求每次请求自己决定路由，任何一次失败
    都不该污染其它域（主分支 `pet/weather.py` 的口径）。

    路由顺序由 ``prefer_direct`` 决定，最多两次；两次共享同一个 ``timeout``
    预算。换路由条件只有两种：传输失败，或状态码在 ``retry_statuses`` 里
    （404/429/503 等明确答复不换，避免把限流当成链路故障）。
    """
    deadline = clock() + max(0.05, float(timeout))
    order = (False, True) if prefer_direct else (True, False)
    last: BaseException | None = None
    for index, use_proxy in enumerate(order):
        remaining = deadline - clock()
        if remaining <= 0:
            raise NetworkTimeout("连接超时")
        request = build_request(
            url, method=method, headers=headers, body=body, params=params
        )
        build = opener or _opener
        try:
            response = build(use_proxy, context).open(request, timeout=remaining)
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            if index == 0 and status in retry_statuses:
                last = http_error(exc)  # consume and close the discarded response
                logger.info("HTTP %s：换路由重试一次", status)
                continue
            raise http_error(exc) from None
        except Exception as exc:  # noqa: BLE001 - 传输失败：换下一种方式
            last = exc
            if index == 0:
                continue
            raise _transport_error(exc) from None
        try:
            headers_out = tuple(
                (str(key), str(value)) for key, value in (response.headers or {}).items()
            )
            status = int(getattr(response, "status", 0) or 0)
            body_bytes = _read_bounded(response, deadline, max_bytes, clock)
        finally:
            try:
                response.close()
            except Exception:  # closing must not mask the original read failure
                pass
        return status, headers_out, body_bytes
    raise _transport_error(last) from None


def _read_bounded(response, deadline: float, max_bytes: int, clock) -> bytes:
    """读响应体：硬上限 + 共享 deadline；超限部分截断，由调用方判定协议错误。"""
    limit = max(0, int(max_bytes))
    remaining = deadline - clock()
    if remaining <= 0:
        raise NetworkTimeout("连接超时")
    chunks: list[bytes] = []
    total = 0
    while total <= limit:
        want = min(_READ_CHUNK, limit + 1 - total)
        if want <= 0:
            break
        chunk = response.read(want)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if clock() > deadline:
            raise NetworkTimeout("连接超时")
    return b"".join(chunks)[:limit]


def _transport_error(exc: BaseException | None) -> NetworkError:
    if exc is None:
        return NetworkError(reason=NETWORK)
    if isinstance(exc, HttpStatusError):
        return exc
    reason = classify_exception(exc) or NETWORK
    if reason == TIMEOUT:
        return NetworkTimeout("连接超时")
    return NetworkError(reason=reason)

