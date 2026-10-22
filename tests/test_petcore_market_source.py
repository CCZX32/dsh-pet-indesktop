from __future__ import annotations

import json

from petcore.market import source


def _index_doc(package_id: str = "fun.divination", version: str = "1.0.0") -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-10-22T00:00:00Z",
        "packages": [
            {
                "id": package_id,
                "kind": "content",
                "name": package_id,
                "latest": version,
                "api_version": "1",
                "versions": [
                    {
                        "version": version,
                        "size": 10,
                        "sha256": "c" * 64,
                        "urls": [f"https://example.invalid/{package_id}.zip"],
                    }
                ],
            }
        ],
    }


def _body(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


class FakeFetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def fetch_index(self, url, *, etag="", timeout=8.0):
        self.calls.append((url, etag))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_load_uses_first_successful_source(tmp_path):
    first = source.IndexFetch(body=_body(_index_doc("fun.first")))
    fetcher = FakeFetcher([first])
    market = source.MarketSource(
        tmp_path,
        fetcher,
        urls=("https://one.invalid/index.json", "https://two.invalid/index.json"),
    )

    result = market.load(force=True)

    assert result.stale is False
    assert result.origin == "https://one.invalid/index.json"
    assert [package.id for package in result.index.packages] == ["fun.first"]
    assert fetcher.calls == [("https://one.invalid/index.json", "")]


def test_failure_falls_through_to_the_next_source(tmp_path):
    fetcher = FakeFetcher(
        [
            source.IndexFetchError("network", "https://one.invalid/index.json"),
            source.IndexFetch(body=_body(_index_doc("fun.second"))),
        ]
    )
    market = source.MarketSource(
        tmp_path, fetcher, urls=("https://one.invalid/index.json", "https://two.invalid/index.json")
    )

    result = market.load(force=True)

    assert result.stale is False
    assert result.origin == "https://two.invalid/index.json"
    assert result.index.packages[0].id == "fun.second"
    assert any("one.invalid" in problem for problem in result.problems)


def test_custom_source_is_tried_before_the_official_one(tmp_path):
    fetcher = FakeFetcher([source.IndexFetch(body=_body(_index_doc()))])
    market = source.MarketSource(tmp_path, fetcher, urls=("https://official.invalid/index.json",))

    market.load(custom_url="https://mirror.invalid/index.json", force=True)

    assert fetcher.calls[0] == ("https://mirror.invalid/index.json", "")


def test_etag_is_reused_for_the_same_url(tmp_path):
    document = _body(_index_doc())
    first = FakeFetcher([source.IndexFetch(body=document, etag="v1")])
    market = source.MarketSource(tmp_path, first, urls=("https://one.invalid/index.json",))
    market.load(force=True)

    second = FakeFetcher([source.IndexFetch(body=b"", not_modified=True)])
    market = source.MarketSource(tmp_path, second, urls=("https://one.invalid/index.json",))
    result = market.load(force=True)

    assert second.calls == [("https://one.invalid/index.json", "v1")]
    assert result.stale is False
    assert result.index.packages[0].id == "fun.divination"


def test_memory_ttl_skips_the_network_until_forced(tmp_path):
    fetcher = FakeFetcher([source.IndexFetch(body=_body(_index_doc()))])
    now = [1000.0]
    market = source.MarketSource(
        tmp_path, fetcher, urls=("https://one.invalid/index.json",), clock=lambda: now[0], ttl=300
    )
    market.load()
    market.load()
    assert len(fetcher.calls) == 1

    now[0] += 301
    fetcher.responses.append(source.IndexFetch(body=_body(_index_doc(version="1.1.0"))))
    result = market.load()

    assert len(fetcher.calls) == 2
    assert result.index.packages[0].version == "1.1.0"


def test_all_sources_failing_falls_back_to_the_disk_cache(tmp_path):
    fetcher = FakeFetcher([source.IndexFetch(body=_body(_index_doc()))])
    source.MarketSource(tmp_path, fetcher, urls=("https://one.invalid/index.json",)).load(force=True)

    failing = FakeFetcher(
        [
            source.IndexFetchError("timeout", "https://one.invalid/index.json"),
            source.IndexFetchError("network", "https://two.invalid/index.json"),
        ]
    )
    market = source.MarketSource(
        tmp_path, failing, urls=("https://one.invalid/index.json", "https://two.invalid/index.json")
    )
    result = market.load(force=True)

    assert result.stale is True
    assert result.origin == "https://one.invalid/index.json"
    assert result.index.packages[0].id == "fun.divination"
    assert any("过期" in problem or "stale" in problem for problem in result.problems)


def test_no_cache_and_no_network_returns_an_empty_stale_index(tmp_path):
    fetcher = FakeFetcher([source.IndexFetchError("network", "https://one.invalid/index.json")])
    market = source.MarketSource(tmp_path, fetcher, urls=("https://one.invalid/index.json",))

    result = market.load(force=True)

    assert result.stale is True
    assert result.index.packages == ()
    assert result.problems


def test_corrupt_disk_cache_is_ignored(tmp_path):
    cache_dir = tmp_path / "market"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index-cache.json").write_text("{broken", encoding="utf-8")
    (cache_dir / "index-cache.meta.json").write_text(
        json.dumps({"url": "https://one.invalid/index.json", "etag": "", "fetched_at": 1.0}),
        encoding="utf-8",
    )
    fetcher = FakeFetcher([source.IndexFetchError("network", "https://one.invalid/index.json")])
    market = source.MarketSource(tmp_path, fetcher, urls=("https://one.invalid/index.json",))

    result = market.load(force=True)

    assert result.stale is True
    assert result.index.packages == ()
    assert any("缓存" in problem or "cache" in problem for problem in result.problems)


def test_corrupt_cache_is_replaced_by_a_good_fetch(tmp_path):
    cache_dir = tmp_path / "market"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index-cache.json").write_text("{broken", encoding="utf-8")
    fetcher = FakeFetcher([source.IndexFetch(body=_body(_index_doc()))])
    market = source.MarketSource(tmp_path, fetcher, urls=("https://one.invalid/index.json",))

    result = market.load(force=True)

    assert result.stale is False
    assert json.loads((cache_dir / "index-cache.json").read_text(encoding="utf-8"))["schema_version"] == 1
