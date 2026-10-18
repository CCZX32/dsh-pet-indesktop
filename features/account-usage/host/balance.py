# -*- coding: utf-8 -*-
"""余额查询与展示（纯标准库；不导入 Core 的任何业务模块）。

请求形状与内置余额查询一致：``GET {base_url}/user/balance``，Bearer 认证。
这里只保留包自己需要的最小面：取数、格式化、把失败翻译成用户能看懂的固定
文案。密钥从不进入异常文本，也不写日志。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT = 10.0


class BalanceError(RuntimeError):
    """固定文案的失败原因；消息里不含密钥、URL 查询串或后端异常文本。"""


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def fetch_balance(
    base_url: str,
    api_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
) -> dict:
    if not api_key.strip():
        raise BalanceError("未配置 API Key")
    endpoint = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/") + "/user/balance"
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "dsh-pet-account-usage/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout), context=_ssl_context(verify_ssl)) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise BalanceError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            raise BalanceError("请求超时") from None
        raise BalanceError("网络连接失败") from None
    except TimeoutError:
        raise BalanceError("请求超时") from None
    except OSError:
        raise BalanceError("网络连接失败") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BalanceError("响应格式异常") from None
    if not isinstance(payload, dict):
        raise BalanceError("响应格式异常")
    return payload


def _money(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def format_balance(payload: dict) -> str:
    """把余额响应变成一行气泡文案；多币种取第一项。"""
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
        raise BalanceError("响应格式异常")
    info = infos[0]
    currency = str(info.get("currency") or "").strip().upper()
    symbol = "¥" if currency in ("", "CNY", "RMB") else f"{currency} "
    total = _money(info.get("total_balance"))
    granted = _money(info.get("granted_balance"))
    topped = _money(info.get("topped_up_balance"))
    text = f"余额 {symbol}{total}"
    if granted != "0.00" or topped != "0.00":
        text += f"（充值 {symbol}{topped} + 赠送 {symbol}{granted}）"
    if payload.get("is_available") is False:
        text += " · 额度不可用"
    return text
