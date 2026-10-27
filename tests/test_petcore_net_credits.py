"""GitHub / B 站致谢取数的解析与失败分类（全部注入假传输，不联网）。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from petcore.net import bilibili, github
from petcore.net.errors import AuthError, NetworkError

SESSDATA = "very-secret-cookie-value"


class Truncated(bytes):
    truncated = True


def _json_response(payload: Any, status: int = 200):
    return status, (("Content-Type", "application/json"),), json.dumps(payload).encode()


# ---------------------------------------------------------------- GitHub


def test_fetch_contributors_normalizes_and_pages(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return _json_response(
            [
                {"login": "klxxya", "contributions": 742},
                {"login": "b", "contributions": "4"},
                {"login": ""},
            ]
        )

    monkeypatch.setattr(github, "fetch_url", fake_fetch)

    rows = github.fetch_contributors("MerZlin/dsh-pet-indesktop")

    assert rows == [
        {"login": "klxxya", "contributions": 742},
        {"login": "b", "contributions": 4},
    ]
    assert calls[0][0].endswith("/repos/MerZlin/dsh-pet-indesktop/contributors")
    assert calls[0][1]["params"] == (("per_page", "100"),)


def test_fetch_contributors_rejects_bad_repo() -> None:
    with pytest.raises(NetworkError) as caught:
        github.fetch_contributors("not a repo")
    assert caught.value.reason == "protocol"


def test_fetch_activity_authors_counts_issues_and_prs(monkeypatch) -> None:
    payload = [
        {"user": {"login": "reporter"}, "pull_request": None},
        {"user": {"login": "coder"}, "pull_request": {"url": "x"}},
        {"user": {"login": "reporter"}, "pull_request": {"url": "x"}},
    ]
    monkeypatch.setattr(github, "fetch_url", lambda *a, **k: _json_response(payload))

    result = github.fetch_activity_authors("MerZlin/repo", pages=3)

    by_login = {item["login"]: item for item in result["authors"]}
    assert by_login["reporter"] == {"login": "reporter", "issues": 1, "prs": 1}
    assert by_login["coder"] == {"login": "coder", "issues": 0, "prs": 1}
    assert result["scanned"] == 3
    assert result["pages"] == 1
    assert result["truncated"] is False


def test_fetch_activity_authors_stops_at_page_limit(monkeypatch) -> None:
    full_page = [
        {"user": {"login": f"u{index}"}, "pull_request": None} for index in range(100)
    ]
    monkeypatch.setattr(github, "fetch_url", lambda *a, **k: _json_response(full_page))

    result = github.fetch_activity_authors("MerZlin/repo", pages=2)

    assert result["pages"] == 2
    assert result["truncated"] is True


def test_github_propagates_rate_limit_as_auth(monkeypatch) -> None:
    def fake_fetch(*_args, **_kwargs):
        raise AuthError(403)

    monkeypatch.setattr(github, "fetch_url", fake_fetch)
    with pytest.raises(NetworkError) as caught:
        github.fetch_contributors("MerZlin/repo")
    assert caught.value.reason == "auth"


def test_github_rejects_truncated_payload(monkeypatch) -> None:
    monkeypatch.setattr(github, "fetch_url", lambda *a, **k: (200, (), Truncated(b"[]")))
    with pytest.raises(NetworkError) as caught:
        github.fetch_contributors("MerZlin/repo")
    assert caught.value.reason == "protocol"


# ---------------------------------------------------------------- B 站


def test_fetch_fan_count_reads_stat(monkeypatch) -> None:
    monkeypatch.setattr(
        bilibili,
        "fetch_url",
        lambda *a, **k: _json_response({"code": 0, "data": {"follower": 3929}}),
    )
    assert bilibili.fetch_fan_count(293026389) == 3929


@pytest.mark.parametrize("data", [{}, {"follower": None}, {"follower": "nan"}])
def test_fetch_fan_count_refuses_to_invent_zero(monkeypatch, data) -> None:
    """缺字段不能当 0：0 会让「总数变了」永远成立，每次都重拉整份名单。"""
    monkeypatch.setattr(
        bilibili,
        "fetch_url",
        lambda *a, **k: _json_response({"code": 0, "data": data}),
    )
    with pytest.raises(NetworkError) as info:
        bilibili.fetch_fan_count(293026389)
    assert info.value.reason == "protocol"


def test_fetch_fans_pages_and_sends_cookie_header(monkeypatch) -> None:
    calls: list[dict] = []
    pages = {
        1: {"code": 0, "data": {"total": 3, "list": [{"uname": "甲"}, {"uname": "乙"}]}},
        2: {"code": 0, "data": {"total": 3, "list": [{"uname": "丙"}]}},
    }

    def fake_fetch(_url, **kwargs):
        params = dict(kwargs["params"])
        calls.append(kwargs)
        return _json_response(pages[int(params["pn"])])

    monkeypatch.setattr(bilibili, "fetch_url", fake_fetch)

    result = bilibili.fetch_fans(293026389, sessdata=SESSDATA, page_size=2)

    assert result["names"] == ["甲", "乙", "丙"]
    assert result["total"] == 3
    assert result["partial"] is False
    assert dict(calls[0]["headers"])["Cookie"] == f"SESSDATA={SESSDATA}"
    assert "SESSDATA" not in json.dumps(calls[0]["params"])


def test_fetch_fans_partial_when_page_limit_hits(monkeypatch) -> None:
    monkeypatch.setattr(
        bilibili,
        "fetch_url",
        lambda *a, **k: _json_response(
            {"code": 0, "data": {"total": 100, "list": [{"uname": "a"}, {"uname": "b"}]}}
        ),
    )
    result = bilibili.fetch_fans(
        293026389, sessdata=SESSDATA, page_size=2, max_pages=1
    )
    assert result["partial"] is True
    assert result["names"] == ["a", "b"]


def test_fetch_fans_is_complete_when_total_exceeds_visible_names(monkeypatch) -> None:
    # 隐私设置可能让 total 大于实际展示的昵称数；最后一页短于 ps 就是读完。
    monkeypatch.setattr(
        bilibili,
        "fetch_url",
        lambda *a, **k: _json_response(
            {"code": 0, "data": {"total": 100, "list": [{"uname": "a"}, {"uname": "b"}]}}
        ),
    )
    result = bilibili.fetch_fans(
        293026389, sessdata=SESSDATA, page_size=10, max_pages=1
    )
    assert result["partial"] is False
    assert result["names"] == ["a", "b"]


def test_fetch_fans_risk_control_is_auth_without_leaking_cookie(monkeypatch) -> None:
    monkeypatch.setattr(
        bilibili, "fetch_url", lambda *a, **k: _json_response({"code": -352, "message": "-352"})
    )
    with pytest.raises(NetworkError) as caught:
        bilibili.fetch_fans(293026389, sessdata=SESSDATA)
    assert caught.value.reason == "auth"
    assert SESSDATA not in str(caught.value)


def test_fetch_fans_requires_credentials() -> None:
    with pytest.raises(NetworkError) as caught:
        bilibili.fetch_fans(293026389, sessdata="")
    assert caught.value.reason == "auth"


def test_sessdata_accepts_a_full_cookie_header() -> None:
    assert bilibili.sessdata_value("a=1; SESSDATA=abc123; b=2") == "abc123"
    assert bilibili.sessdata_value("SESSDATA=abc123") == "abc123"
    assert bilibili.sessdata_value("abc123") == "abc123"
    with pytest.raises(NetworkError):
        bilibili.sessdata_value("  ")


def test_sessdata_rejects_a_cookie_without_sessdata() -> None:
    with pytest.raises(NetworkError) as caught:
        bilibili.sessdata_value("foo=1; b=2")
    assert caught.value.reason == "auth"
