from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from ..api.credentials import KeyringCredentials
from ..api.store import ApiStore
from ..net.errors import (
    AUTH,
    NETWORK,
    PROTOCOL,
    classify_exception,
    http_error,
)
from ..net.http import urlopen


@dataclass(frozen=True, slots=True)
class BalanceResult:
    service_id: str
    total: str
    granted: str
    topped_up: str
    is_available: bool = True
    fetched_at: float = 0.0

    def format_text(self) -> str:
        if self.granted and self.topped_up:
            return f"余额 ¥{self.total}（充值 ¥{self.topped_up} / 赠送 ¥{self.granted}）"
        return f"余额 ¥{self.total}" if self.total else "余额信息为空"


class AccountError(RuntimeError):
    def __init__(self, reason: str, message: str | None = None):
        self.reason = str(reason)
        super().__init__(message or self.reason)


class AccountService:
    """Core account/balance service with a bounded in-memory cache."""

    def __init__(
        self,
        store: ApiStore,
        credentials: KeyringCredentials,
        *,
        cache_ttl: float = 30.0,
        transport: Callable[..., Any] = urlopen,
    ) -> None:
        self.store = store
        self.credentials = credentials
        self.cache_ttl = max(0.0, float(cache_ttl))
        self.transport = transport
        self._cache: dict[str, BalanceResult] = {}

    def invalidate(self, service_id: str | None = None) -> None:
        if service_id is None:
            self._cache.clear()
        else:
            self._cache.pop(str(service_id), None)

    def cached(self, service_id: str) -> BalanceResult | None:
        result = self._cache.get(str(service_id))
        if result is None or monotonic() - result.fetched_at > self.cache_ttl:
            return None
        return result

    def fetch_balance(self, service_id: str, *, force: bool = False) -> BalanceResult:
        service_id = str(service_id)
        if not force:
            cached = self.cached(service_id)
            if cached is not None:
                return cached
        service = self.store.get(service_id)
        if service is None or service.balance_protocol != "deepseek":
            raise AccountError(PROTOCOL, "该服务没有可用的余额协议")
        api_key = self.credentials.get("core.api", service_id) or ""
        if not api_key:
            raise AccountError(AUTH, "未配置 API Key")
        endpoint = f"{service.base_url.rstrip('/')}/user/balance"
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="GET",
        )
        context = None if service.verify_ssl else _insecure_context()
        try:
            response = self.transport(request, timeout=float(service.timeout), context=context)
        except urllib.error.HTTPError as exc:
            error = http_error(exc)
            raise AccountError(error.reason, f"HTTP {error.status}") from None
        except Exception as exc:  # noqa: BLE001 - stable network classification
            reason = classify_exception(exc) or NETWORK
            raise AccountError(reason) from None
        try:
            raw = response.read(1024 * 1024)
        except Exception as exc:  # noqa: BLE001
            raise AccountError(NETWORK) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            result = _parse_balance(service_id, data)
        except AccountError:
            raise
        except (UnicodeError, ValueError, TypeError) as exc:
            raise AccountError(PROTOCOL) from exc
        self._cache[service_id] = result
        return result


def _parse_balance(service_id: str, data: Any) -> BalanceResult:
    if not isinstance(data, dict) or not isinstance(data.get("balance_infos"), list):
        raise AccountError(PROTOCOL, "余额响应缺少 balance_infos")
    infos = [item for item in data["balance_infos"] if isinstance(item, dict)]
    if not infos:
        raise AccountError(PROTOCOL, "余额响应没有有效条目")

    def rank(item: dict[str, Any]) -> tuple[bool, bool]:
        try:
            positive = float(item.get("total_balance") or 0) > 0
        except (TypeError, ValueError):
            positive = False
        return positive, str(item.get("currency") or "").upper() == "CNY"

    info = max(infos, key=rank)
    total = str(info.get("total_balance") or "")
    if not total:
        raise AccountError(PROTOCOL, "余额响应缺少 total_balance")
    return BalanceResult(
        service_id=service_id,
        total=total,
        granted=str(info.get("granted_balance") or ""),
        topped_up=str(info.get("topped_up_balance") or ""),
        is_available=bool(data.get("is_available", True)),
        fetched_at=monotonic(),
    )


def _insecure_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


__all__ = ["AccountError", "AccountService", "BalanceResult"]
