from __future__ import annotations

import json
import urllib.error
from email.message import Message

import pytest

from petcore.account.service import AccountError, AccountService
from petcore.api.credentials import KeyringCredentials
from petcore.api.spec import ApiService
from petcore.api.store import ApiStore


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str):
        return self.values.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.values[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.values.pop((service, key), None)


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.closed = False

    def read(self, _limit: int):
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        self.closed = True


def _service(tmp_path, key: str = "secret"):
    store = ApiStore(tmp_path)
    store.upsert(
        ApiService(
            service_id="deepseek",
            name="DeepSeek",
            base_url="https://api.deepseek.com",
            balance_protocol="deepseek",
        )
    )
    backend = _Keyring()
    credentials = KeyringCredentials(backend=backend)
    credentials.set("core.api", "deepseek", key)
    return store, credentials


def test_account_service_fetches_and_caches_balance(tmp_path) -> None:
    store, credentials = _service(tmp_path)
    calls = []

    def transport(request, **_kwargs):
        calls.append(request.full_url)
        return _Response(
            {
                "is_available": True,
                "balance_infos": [
                    {"currency": "USD", "total_balance": "0"},
                    {
                        "currency": "CNY",
                        "total_balance": "12.34",
                        "granted_balance": "2.00",
                        "topped_up_balance": "10.34",
                    },
                ],
            }
        )

    service = AccountService(store, credentials, transport=transport)
    result = service.fetch_balance("deepseek")
    cached = service.fetch_balance("deepseek")

    assert result is cached
    assert result.format_text() == "余额 ¥12.34（充值 ¥10.34 / 赠送 ¥2.00）"
    assert calls == ["https://api.deepseek.com/user/balance"]


def test_account_service_requires_key_and_protocol(tmp_path) -> None:
    store, credentials = _service(tmp_path, key="")
    service = AccountService(store, credentials, transport=lambda *_args, **_kwargs: None)
    with pytest.raises(AccountError) as missing:
        service.fetch_balance("deepseek")
    assert missing.value.reason == "auth"

    with pytest.raises(AccountError) as unknown:
        service.fetch_balance("missing")
    assert unknown.value.reason == "protocol"


def test_account_service_classifies_http_errors(tmp_path) -> None:
    store, credentials = _service(tmp_path)
    headers = Message()
    headers["Retry-After"] = "4"

    def transport(_request, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.deepseek.com/user/balance", 429, "busy", headers, None
        )

    service = AccountService(store, credentials, transport=transport)
    with pytest.raises(AccountError) as error:
        service.fetch_balance("deepseek")
    assert error.value.reason == "rate_limit"
