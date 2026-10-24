"""根候选索引（T06）：结构、可移植性，以及 CLI 的本地 file: 链路。"""

from __future__ import annotations

import json
from pathlib import Path

from petcore.market import cli, model
from petcore.market.source import MarketSource

ROOT = Path(__file__).resolve().parents[1]
INDEX_FILE = ROOT / "extensions-index.json"


def _document() -> dict:
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def test_root_index_parses_and_keeps_every_package_blocked():
    index, problems = model.parse_index(_document())

    assert index is not None, problems
    assert problems == []
    ids = {package.id for package in index.packages}
    assert ids == {"reminder.todo", "fun.festival", "fun.divination", "voice.chime"}
    for package in index.packages:
        assert package.blocked is True
        assert package.blocked_reason


def test_root_index_versions_carry_size_and_sha256_and_managed_urls():
    index, _ = model.parse_index(_document())

    for package in index.packages:
        assert package.versions, package.id
        for version in package.versions:
            assert version.size > 0
            assert len(version.sha256) == 64
            int(version.sha256, 16)
            assert version.urls
            for url in version.urls:
                assert url.startswith("https://github.com/MerZlin/dsh-pet-indesktop/")
                assert not url.startswith("file:")


def test_root_index_matches_capabilities_of_the_four_example_packs():
    index, _ = model.parse_index(_document())

    for package in index.packages:
        manifest = json.loads(
            (
                ROOT
                / "examples"
                / "petcore-mods"
                / package.id
                / "mod.json"
            ).read_text(encoding="utf-8")
        )
        assert manifest["version"] == package.version
        assert manifest["core_requires"] == package.core_requires
        assert set(manifest.get("capabilities", [])) == set(package.capabilities)


def test_local_file_index_is_loadable_offline(tmp_path):
    from petcore.net.market import HttpFetcher

    source = MarketSource(tmp_path, HttpFetcher())

    result = source.load(custom_url=INDEX_FILE.as_uri(), force=True)

    assert result.index is not None
    assert len(result.index.packages) == 4
    assert result.stale is False


def test_cli_lists_the_local_index_and_refuses_blocked_install(tmp_path, capsys):
    url = INDEX_FILE.as_uri()

    code = cli.main(["--root", str(tmp_path), "--index-url", url, "list", "--json"])
    listing = json.loads(capsys.readouterr().out)

    assert code == 0
    assert {item["id"] for item in listing["packages"]} == {
        "reminder.todo",
        "fun.festival",
        "fun.divination",
        "voice.chime",
    }
    assert {item["state"] for item in listing["packages"]} == {model.STATE_BLOCKED}
    assert all(item["reason"] for item in listing["packages"])

    blocked = cli.main(
        [
            "--root",
            str(tmp_path),
            "--index-url",
            url,
            "install",
            "reminder.todo",
            "--allow-feature",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert blocked == 1
    assert payload["ok"] is False
    assert "待发布" in payload["message"]
    assert not (tmp_path / "mods" / "reminder.todo").exists()


def test_file_index_does_not_fall_back_to_public_sources(tmp_path):
    from petcore.net.market import HttpFetcher

    source = MarketSource(
        tmp_path, HttpFetcher(), urls=("https://official.invalid/index.json",)
    )

    assert source.urls(INDEX_FILE.as_uri()) == (INDEX_FILE.as_uri(),)
    assert source.urls("https://mirror.invalid/index.json")[0] == (
        "https://mirror.invalid/index.json"
    )
    assert len(source.urls("https://mirror.invalid/index.json")) == 2
