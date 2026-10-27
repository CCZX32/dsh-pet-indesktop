"""GitHub 只读取数：贡献者与 issue/PR 作者（致谢页用）。

未登录 API 限额 60 次/小时；本模块每次刷新最多 1 + 6 次请求。403/429 直接按
``rate_limit`` 分类，不重试、不换路由（GitHub 是海外源，路由交给
:func:`petcore.net.http.fetch_url` 的默认「代理优先」）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .errors import PROTOCOL, NetworkError, classify_exception
from .http import fetch_url

logger = logging.getLogger("petcore.net.github")

API_ROOT = "https://api.github.com"
USER_AGENT = "dsh-pet-core-credits"
MAX_BYTES = 4_000_000
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def clean_repo(repo: str) -> str:
    text = str(repo or "").strip().strip("/")
    if not _REPO_RE.match(text):
        raise NetworkError("GitHub 仓库名不合法", reason=PROTOCOL)
    return text


def _get_json(url: str, *, params: tuple[tuple[str, str], ...], timeout: float) -> Any:
    try:
        _status, _headers, body = fetch_url(
            url,
            headers=(
                ("User-Agent", USER_AGENT),
                ("Accept", "application/vnd.github+json"),
                ("X-GitHub-Api-Version", "2022-11-28"),
            ),
            params=params,
            timeout=timeout,
            max_bytes=MAX_BYTES,
        )
    except NetworkError:
        raise
    except Exception as exc:  # noqa: BLE001 - 传输层意外形态
        raise NetworkError(type(exc).__name__, reason=classify_exception(exc) or PROTOCOL) from exc
    if getattr(body, "truncated", False):
        raise NetworkError("GitHub 响应被截断", reason=PROTOCOL)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise NetworkError("GitHub 返回了无法解析的响应", reason=PROTOCOL) from None


def fetch_contributors(repo: str, *, timeout: float = 8.0, limit: int = 100) -> list[dict]:
    """按提交数降序的贡献者；``login`` 与 ``contributions``。"""
    name = clean_repo(repo)
    payload = _get_json(
        f"{API_ROOT}/repos/{name}/contributors",
        params=(("per_page", str(max(1, min(100, int(limit))))),),
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise NetworkError("GitHub 贡献者响应格式不对", reason=PROTOCOL)
    result: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        login = str(item.get("login") or "").strip()
        if not login:
            continue
        try:
            count = max(0, int(item.get("contributions") or 0))
        except (TypeError, ValueError):
            count = 0
        result.append({"login": login, "contributions": count})
    return result


def fetch_activity_authors(
    repo: str,
    *,
    pages: int = 6,
    per_page: int = 100,
    timeout: float = 8.0,
) -> dict:
    """issue/PR 作者聚合：``{"authors": [...], "scanned": n, "pages": p, "truncated": bool}``。"""
    name = clean_repo(repo)
    limit_pages = max(1, min(10, int(pages)))
    size = max(1, min(100, int(per_page)))
    counts: dict[str, dict[str, int]] = {}
    scanned = 0
    used = 0
    truncated = False
    for page in range(1, limit_pages + 1):
        payload = _get_json(
            f"{API_ROOT}/repos/{name}/issues",
            params=(
                ("state", "all"),
                ("per_page", str(size)),
                ("page", str(page)),
                ("sort", "created"),
                ("direction", "desc"),
            ),
            timeout=timeout,
        )
        if not isinstance(payload, list):
            raise NetworkError("GitHub issue 响应格式不对", reason=PROTOCOL)
        used = page
        scanned += len(payload)
        for item in payload:
            if not isinstance(item, dict):
                continue
            login = str((item.get("user") or {}).get("login") or "").strip()
            if not login:
                continue
            bucket = counts.setdefault(login, {"issues": 0, "prs": 0})
            if item.get("pull_request"):
                bucket["prs"] += 1
            else:
                bucket["issues"] += 1
        if len(payload) < size:
            break
        if page == limit_pages:
            truncated = True
    authors = [
        {"login": login, "issues": value["issues"], "prs": value["prs"]}
        for login, value in counts.items()
    ]
    return {
        "authors": authors,
        "scanned": scanned,
        "pages": used,
        "truncated": truncated,
    }
