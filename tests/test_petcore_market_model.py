from __future__ import annotations

import json

from petcore.market import model


def _entry(**overrides):
    entry = {
        "id": "fun.divination",
        "kind": "feature",
        "name": "Divination",
        "name_zh": "每日一签",
        "summary_zh": "一天一支签",
        "author": "MerZlin",
        "homepage": "https://example.invalid/divination",
        "categories": ["fun"],
        "latest": "1.2.0",
        "api_version": "1",
        "core_requires": ">=0.1.0,<1.0.0",
        "execution": "host-only",
        "capabilities": ["presentation"],
        "platforms": ["win32", "darwin", "linux"],
        "certified": True,
        "blocked": False,
        "blocked_reason": "",
        "superseded_by": None,
        "screenshots": [],
        "versions": [
            {
                "version": "1.2.0",
                "released_at": "2026-10-20",
                "size": 1234,
                "sha256": "a" * 64,
                "urls": ["https://example.invalid/fun.divination-1.2.0.zip"],
                "changelog": "新增语音播报",
            },
            {
                "version": "1.0.0",
                "released_at": "2026-09-01",
                "size": 1000,
                "sha256": "b" * 64,
                "urls": ["https://example.invalid/fun.divination-1.0.0.zip"],
            },
        ],
    }
    entry.update(overrides)
    return entry


def _index(*entries):
    return {"schema_version": 1, "generated_at": "2026-10-22T00:00:00Z", "packages": list(entries)}


def test_parse_index_reads_versions_and_metadata():
    index, problems = model.parse_index(_index(_entry()))

    assert problems == []
    assert index is not None
    package = index.by_id("fun.divination")
    assert package is not None
    assert package.name_zh == "每日一签"
    assert package.execution == "host-only"
    assert [version.version for version in package.versions] == ["1.2.0", "1.0.0"]
    latest = model.latest_version(package)
    assert latest is not None
    assert latest.sha256 == "a" * 64
    assert latest.size == 1234
    assert latest.urls == ("https://example.invalid/fun.divination-1.2.0.zip",)


def test_package_without_hash_or_size_is_not_installable():
    entry = _entry()
    entry["versions"][0].pop("sha256")
    entry["versions"][1]["size"] = -1

    index, problems = model.parse_index(_index(entry))

    assert index is not None
    package = index.by_id("fun.divination")
    assert package is not None
    assert [version.version for version in package.versions] == []
    assert any("sha256" in problem for problem in problems)
    assert any("size" in problem for problem in problems)
    assert model.latest_version(package) is None


def test_latest_must_exist_and_not_be_yanked():
    missing = model.parse_index(_index(_entry(latest="9.9.9")))
    assert missing[0] is not None
    assert missing[0].by_id("fun.divination") is None
    assert any("latest" in problem for problem in missing[1])

    entry = _entry()
    entry["versions"][0]["yanked"] = True
    yanked = model.parse_index(_index(entry))
    assert yanked[0] is not None
    assert yanked[0].by_id("fun.divination") is None
    assert any("yanked" in problem.lower() for problem in yanked[1])


def test_unknown_schema_version_rejects_the_whole_index():
    index, problems = model.parse_index({"schema_version": 2, "packages": []})

    assert index is None
    assert any("schema_version" in problem for problem in problems)


def test_reserved_and_invalid_ids_are_dropped_per_package():
    index, problems = model.parse_index(
        _index(
            _entry(id="fun.self-talk"),
            _entry(id="Bad ID", latest="1.2.0"),
            _entry(id="media.music"),
        )
    )

    assert index is not None
    assert index.by_id("fun.self-talk") is None
    assert index.by_id("media.music") is not None
    assert any("reserved" in problem for problem in problems)
    assert any("invalid id" in problem for problem in problems)


def test_unknown_fields_are_diagnostics_not_failures():
    entry = _entry()
    entry["future_field"] = {"anything": True}
    entry["versions"][0]["future_version_field"] = 1

    index, problems = model.parse_index(_index(entry))

    assert index is not None
    assert index.by_id("fun.divination") is not None
    assert any("future_field" in problem for problem in problems)


def test_platform_support_accepts_common_aliases():
    package = model.parse_index(_index(_entry(platforms=["windows", "macos", "linux"])))[0].by_id(
        "fun.divination"
    )

    assert model.platform_supported(package, "win32")
    assert model.platform_supported(package, "darwin")
    assert model.platform_supported(package, "linux")
    assert not model.platform_supported(package, "freebsd")


def test_core_compatibility_uses_the_manifest_grammar():
    package = model.parse_index(_index(_entry()))[0].by_id("fun.divination")

    assert model.core_compatible(package, "0.1.0")
    assert not model.core_compatible(package, "1.0.0")


def test_state_available_installed_and_update():
    package = model.parse_index(_index(_entry()))[0].by_id("fun.divination")

    assert model.package_state(
        package, installed_version=None, core_version="0.1.0", platform="win32"
    ).state == model.STATE_AVAILABLE
    assert model.package_state(
        package, installed_version="1.2.0", core_version="0.1.0", platform="win32"
    ).state == model.STATE_INSTALLED
    update = model.package_state(
        package, installed_version="1.0.0", core_version="0.1.0", platform="win32"
    )
    assert update.state == model.STATE_UPDATE
    assert update.installed == "1.0.0"
    assert update.latest == "1.2.0"


def test_local_newer_version_is_not_offered_as_downgrade():
    package = model.parse_index(_index(_entry()))[0].by_id("fun.divination")

    state = model.package_state(
        package, installed_version="1.3.0", core_version="0.1.0", platform="win32"
    )

    assert state.state == model.STATE_INSTALLED


def test_blocked_superseded_and_platform_take_precedence():
    package = model.parse_index(_index(_entry()))[0].by_id("fun.divination")

    blocked = model.package_state(
        package,
        installed_version=None,
        core_version="0.1.0",
        platform="win32",
        blocked=True,
        blocked_reason="恶意行为",
    )
    assert blocked.state == model.STATE_BLOCKED
    assert blocked.reason == "恶意行为"

    superseded = model.package_state(
        package, installed_version=None, core_version="0.1.0", platform="win32", superseded_by="fun.other"
    )
    assert superseded.state == model.STATE_SUPERSEDED
    assert superseded.superseded_by == "fun.other"

    unsupported = model.package_state(
        package, installed_version=None, core_version="0.1.0", platform="freebsd"
    )
    assert unsupported.state == model.STATE_UNSUPPORTED
    assert unsupported.reason


def test_incompatible_core_and_api_are_reported_with_reason():
    package = model.parse_index(_index(_entry()))[0].by_id("fun.divination")

    core = model.package_state(
        package, installed_version=None, core_version="1.0.0", platform="win32"
    )
    assert core.state == model.STATE_INCOMPATIBLE
    assert "core" in core.reason.lower()

    api = model.package_state(
        package,
        installed_version=None,
        core_version="0.1.0",
        platform="win32",
        api_version="2",
    )
    assert api.state == model.STATE_INCOMPATIBLE
    assert "api" in api.reason.lower()


def test_parse_index_text_round_trip():
    index, problems = model.parse_index_text(json.dumps(_index(_entry())))

    assert problems == []
    assert index is not None
    assert index.packages[0].id == "fun.divination"


def test_malformed_json_is_a_diagnostic():
    index, problems = model.parse_index_text("{not json")

    assert index is None
    assert problems and "JSON" in problems[0]
