# -*- coding: utf-8 -*-
"""账户用量包自己的配置面：偏好字段 + 凭据库引用。

包读不到 Core 的 ``config.json``。偏好落在 ``feature-data/<owner>/preferences.json``，
API Key 落在 owner 作用域的凭据库（操作集只有 ``balance.query``），偏好里只保存
一个不透明的 ``credential_ref``。
"""

from __future__ import annotations

from .balance import DEFAULT_BASE_URL

PROFILE = "account-usage"

DEFAULTS = {
    "enabled": True,
    "base_url": DEFAULT_BASE_URL,
    "refresh_minutes": 0,
    "verify_ssl": True,
    "credential_ref": "",
}


def _bool(value, fallback):
    return value if isinstance(value, bool) else fallback


def _minutes(value):
    try:
        return max(0, min(1440, int(value)))
    except (TypeError, ValueError):
        return 0


def _text(value, fallback):
    return value if isinstance(value, str) and value.strip() else fallback


class AccountConfig:
    def __init__(self, context):
        self._context = context
        self._values = dict(DEFAULTS)
        self.reload()

    def reload(self) -> None:
        try:
            raw = self._context.preferences.read()
        except Exception:
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        self._values = {
            "enabled": _bool(raw.get("enabled"), DEFAULTS["enabled"]),
            "base_url": _text(raw.get("base_url"), DEFAULTS["base_url"]).rstrip("/"),
            "refresh_minutes": _minutes(raw.get("refresh_minutes")),
            "verify_ssl": _bool(raw.get("verify_ssl"), DEFAULTS["verify_ssl"]),
            "credential_ref": _text(raw.get("credential_ref"), ""),
        }

    @property
    def enabled(self) -> bool:
        return bool(self._values["enabled"])

    @property
    def base_url(self) -> str:
        return str(self._values["base_url"])

    @property
    def refresh_minutes(self) -> int:
        return int(self._values["refresh_minutes"])

    @property
    def verify_ssl(self) -> bool:
        return bool(self._values["verify_ssl"])

    @property
    def credential_ref(self) -> str:
        return str(self._values["credential_ref"])

    def api_key(self) -> str | None:
        ref = self.credential_ref
        if not ref:
            return None
        try:
            return self._context.credentials.acquire(ref, PROFILE, self.base_url, "balance.query")
        except Exception:
            return None

    def store_secret(self, secret: str, *, base_url: str | None = None) -> str:
        return self._context.credentials.save(PROFILE, base_url or self.base_url, secret)

    def save(self, *, enabled: bool, base_url: str, refresh_minutes: int, verify_ssl: bool, credential_ref: str) -> bool:
        values = {
            "enabled": bool(enabled),
            "base_url": str(base_url).strip().rstrip("/") or DEFAULT_BASE_URL,
            "refresh_minutes": _minutes(refresh_minutes),
            "verify_ssl": bool(verify_ssl),
            "credential_ref": str(credential_ref or ""),
        }
        self._context.preferences.stage(values)
        if not self._context.preferences.flush():
            return False
        self._values = values
        return True
