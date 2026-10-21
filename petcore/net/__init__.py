"""Core 唯一的联网出口。

规则（见 `petcore/AGENTS.md`）：只有本包、`petcore/api` 与 `petcore/account`
允许 import 网络库；mod 只能通过 HostPorts 拿能力。这里只用标准库。
"""

from __future__ import annotations

from .errors import (
    AuthError,
    HttpStatusError,
    NetworkError,
    NetworkTimeout,
    NetworkUnreachable,
    RateLimitError,
    classify_exception,
    classify_http_status,
    describe,
)
from .http import force_direct, reset_transport, urlopen

__all__ = [
    "AuthError",
    "HttpStatusError",
    "NetworkError",
    "NetworkTimeout",
    "NetworkUnreachable",
    "RateLimitError",
    "classify_exception",
    "classify_http_status",
    "describe",
    "force_direct",
    "reset_transport",
    "urlopen",
]
