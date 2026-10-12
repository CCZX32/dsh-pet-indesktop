"""Local MOD management: character-package install, enable/disable, removal.

Rewritten from the DLC branch blueprints (`tests/test_mod_center_contracts.py`
and `tests/test_feature_packages.py`) because the host surface differs: on this
topology a character package is a directory under the roots owned by
:mod:`pet.catalog` (``assets/characters`` plus the external roots), not a
``content/characters/<id>/versions/<version>`` layout.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from pet import catalog, mod_management
from pet.mod_management import ModEntry, ModError, ModOutcome, ModSelection, ResourceMods


def _write_package(root: Path, *, character_id: str = "demo", version: str = "1.0.0",
                   name: str = "Demo", description: str | None = None) -> Path:
    package = root / "package"
    videos = package / "videos"
    videos.mkdir(parents=True)
    (videos / "idle.webm").write_bytes(b"test-video")
    manifest: dict[str, object] = {"id": character_id, "name": name, "version": version}
    if description is not None:
        manifest["description"] = description
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


def _zip_package(source: Path, target: Path, *, prefix: str = "") -> Path:
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, prefix + path.relative_to(source).as_posix())
    return target


# ------------------------------------------------------------- value objects

def test_mod_selection_is_limited_to_visible_results():
    rows = [ModEntry("sample.one", "功能扩展", "一", "1.0.0", "", False, Path("one")),
            ModEntry("sample.two", "角色资源", "二", "1.0.0", "", False, Path("two"))]
    selection = ModSelection()
    selection.set_visible(rows)
    selection.select_all()
    assert selection.selected == {"sample.one", "sample.two"}
    selection.set_visible(rows[1:])
    assert not selection.selected


def test_mod_entry_separates_managed_copies_from_loose_ones():
    managed = ModEntry("demo", "角色资源", "Demo", "1.0.0", "", True, Path("live"))
    loose = ModEntry("resource:external:demo", "角色资源", "Demo", "0.0.0", "", True,
                     Path("loose"), source="external", character_id="demo")
    assert managed.managed and managed.key == "角色资源:demo"
    assert not loose.managed


def test_mod_outcome_defaults_to_a_settled_result():
    outcome = ModOutcome(True, "已启用")
    assert not outcome.pending


# ------------------------------------------------------------ discovery

def test_entries_list_managed_and_unmanaged_packages(tmp_path):
    builtin = tmp_path / "builtin"
    external = tmp_path / "external"
    for root, character in ((builtin, "shenshen"), (external, "loose")):
        (root / character / "videos").mkdir(parents=True)
        (root / character / "videos" / "idle.webm").write_bytes(b"video")
    resources = ResourceMods(tmp_path / "data", character_roots=[("builtin", builtin), ("external", external)])
    resources.install(_write_package(tmp_path / "source"))

    rows = {row.id: row for row in resources.entries()}
    assert rows["demo"].managed and rows["demo"].source == "installed"
    assert rows["resource:builtin:shenshen"].source == "builtin"
    assert rows["resource:external:loose"].source == "external"
    assert all(row.character_id for row in rows.values())


def test_entries_never_duplicate_a_package_that_is_also_managed(tmp_path):
    external = tmp_path / "external"
    (external / "demo" / "videos").mkdir(parents=True)
    (external / "demo" / "videos" / "idle.webm").write_bytes(b"video")
    resources = ResourceMods(tmp_path / "data", character_roots=[("external", external)])
    resources.install(_write_package(tmp_path / "source"))

    rows = resources.entries()
    assert [row.id for row in rows] == ["demo"]
    assert rows[0].managed


def test_entries_can_exclude_unmanaged_packages(tmp_path):
    builtin = tmp_path / "builtin"
    (builtin / "shenshen" / "videos").mkdir(parents=True)
    (builtin / "shenshen" / "videos" / "idle.webm").write_bytes(b"video")
    resources = ResourceMods(tmp_path / "data", character_roots=[("builtin", builtin)])
    assert resources.entries(include_unmanaged=False) == []


def test_a_directory_without_videos_is_not_offered(tmp_path):
    builtin = tmp_path / "builtin"
    (builtin / "notacandidate" / "notes").mkdir(parents=True)
    resources = ResourceMods(tmp_path / "data", character_roots=[("builtin", builtin)])
    assert resources.entries() == []


def test_an_existing_non_ascii_character_folder_is_still_offered(tmp_path):
    builtin = tmp_path / "builtin"
    videos = builtin / "深海小鲸鱼" / "videos"
    videos.mkdir(parents=True)
    (videos / "idle.webm").write_bytes(b"video")
    resources = ResourceMods(tmp_path / "data", character_roots=[("builtin", builtin)])
    assert [row.id for row in resources.entries()] == ["resource:builtin:深海小鲸鱼"]


def test_display_metadata_is_clamped_without_hiding_the_package(tmp_path):
    package = _write_package(tmp_path / "source", name="长" * 400, description="说明" * 4000)
    resources = ResourceMods(tmp_path / "data")
    entry = resources.install(package)
    assert len(entry.name) == 256
    assert len(entry.description) == 4096
    assert entry.id == "demo"


def test_install_accepts_a_non_ascii_character_id(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    entry = resources.install(_write_package(tmp_path / "source", character_id="深海小鲸鱼"))
    assert entry.path == tmp_path / "data" / "mod-disabled" / "深海小鲸鱼"


@pytest.mark.parametrize("character_id", ["../escape", "a/b", "a\\b", ".", "..", "nul", "demo."])
def test_install_rejects_an_id_that_cannot_be_one_directory_name(tmp_path, character_id):
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.install(_write_package(tmp_path / "source", character_id=character_id))


def test_a_managed_folder_name_that_cannot_be_an_id_is_reported_not_deleted(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source"))
    resources.set_enabled(entry.id, True)
    stray = tmp_path / "data" / "characters" / " trailing"
    (stray / "videos").mkdir(parents=True)
    (stray / "videos" / "idle.webm").write_bytes(b"video")

    assert [row.id for row in resources.entries(include_unmanaged=False)] == ["demo"]
    assert stray.is_dir()


# ------------------------------------------------------------- installation

def test_a_fresh_install_lands_disabled_and_outside_the_live_root(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    entry = resources.install(_write_package(tmp_path / "source"))
    assert entry.id == "demo"
    assert entry.enabled is False
    assert entry.path == tmp_path / "data" / "mod-disabled" / "demo"
    assert not (tmp_path / "data" / "characters" / "demo").exists()


def test_enabling_moves_the_package_into_the_root_the_catalog_scans(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    managed_root = data_root / "characters"
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [managed_root])
    resources = ResourceMods(data_root)
    entry = resources.install(_write_package(tmp_path / "source"))
    assert entry.id not in catalog.list_available_characters()

    outcome = resources.set_enabled(entry.id, True)
    assert outcome.success and not outcome.pending
    assert entry.id in catalog.list_available_characters()
    assert catalog.resolve_character_video_dir(entry.id) == managed_root / entry.id / "videos"

    rows = resources.entries()
    assert rows[0].enabled is True
    assert rows[0].path == managed_root / entry.id


def test_disabling_moves_the_package_back_out_of_the_live_root(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    managed_root = data_root / "characters"
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [managed_root])
    resources = ResourceMods(data_root, prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source"))
    resources.set_enabled(entry.id, True)
    resources.set_enabled(entry.id, False)

    assert entry.id not in catalog.list_available_characters()
    assert (data_root / "mod-disabled" / entry.id / "videos" / "idle.webm").is_file()


def test_set_enabled_is_idempotent(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    entry = resources.install(_write_package(tmp_path / "source"))
    assert resources.set_enabled(entry.id, False) == ModOutcome(True, "已停用")
    assert resources.set_enabled(entry.id, False) == ModOutcome(True, "已停用")


def test_disabling_refuses_while_the_character_is_still_in_use(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: False)
    entry = resources.install(_write_package(tmp_path / "source"))
    resources.set_enabled(entry.id, True)

    outcome = resources.set_enabled(entry.id, False)
    assert not outcome.success and outcome.pending
    assert (tmp_path / "data" / "characters" / entry.id).is_dir()


def test_install_rejects_a_mismatched_expected_identity(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError, match="同一个角色包"):
        resources.install(_write_package(tmp_path / "source"), expected_id="other")


def test_install_rejects_a_package_without_videos(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text(json.dumps({"id": "demo"}), encoding="utf-8")
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.install(package)


@pytest.mark.parametrize("suffix", [".py", ".dll", ".exe", ".bat"])
def test_install_rejects_executables_inside_a_package(tmp_path, suffix):
    package = _write_package(tmp_path / "source")
    (package / "videos" / ("payload" + suffix)).write_bytes(b"no")
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.install(package)


def test_install_rejects_a_source_that_is_neither_directory_nor_zip(tmp_path):
    source = tmp_path / "broken.zip"
    source.write_bytes(b"not a zip")
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.install(source)


def test_install_accepts_a_zip_package(tmp_path):
    source = _zip_package(_write_package(tmp_path / "source"), tmp_path / "demo.zip")
    resources = ResourceMods(tmp_path / "data")
    entry = resources.install(source)
    assert entry.id == "demo"
    assert (entry.path / "videos" / "idle.webm").read_bytes() == b"test-video"


def test_install_accepts_a_zip_with_one_wrapping_directory(tmp_path):
    source = _zip_package(_write_package(tmp_path / "source"), tmp_path / "demo.zip", prefix="demo-1.0.0/")
    resources = ResourceMods(tmp_path / "data")
    assert resources.install(source).id == "demo"


def test_install_rejects_a_zip_that_escapes_its_root(tmp_path):
    source = tmp_path / "evil.zip"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("../escape.webm", b"video")
        archive.writestr("manifest.json", json.dumps({"id": "demo"}))
        archive.writestr("videos/idle.webm", b"video")
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.install(source)


def test_install_leaves_no_staging_debris_after_success(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    resources.install(_zip_package(_write_package(tmp_path / "source"), tmp_path / "demo.zip"))
    staging = tmp_path / "data" / "mod-staging"
    assert not staging.exists() or not any(staging.iterdir())


def test_reinstalling_the_same_version_over_the_live_copy_stays_usable(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.set_enabled(entry.id, True)
    live = tmp_path / "data" / "characters" / entry.id

    again = resources.install(live)
    assert again.enabled is True
    assert (live / "videos" / "idle.webm").read_bytes() == b"test-video"


def test_a_failed_publish_puts_the_previous_copy_back(tmp_path, monkeypatch):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.set_enabled(entry.id, True)
    live = tmp_path / "data" / "characters" / entry.id

    replace = os.replace

    def flaky(source, target):
        # Refuse only the final publish rename, after the old copy was moved out.
        if Path(target) == live and Path(source).name == entry.id:
            raise OSError(13, "simulated busy rename")
        return replace(source, target)

    monkeypatch.setattr(mod_management.os, "replace", flaky)
    with pytest.raises(ModError):
        resources.install(_write_package(tmp_path / "next", version="1.0.1"))

    assert live.is_dir(), "an interrupted update must not leave the live root empty"
    manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0"
    assert resources.entries(include_unmanaged=False)[0].enabled is True


# ------------------------------------------------------------------ update

def test_update_of_an_enabled_package_requires_release_of_the_old_copy(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: False)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.set_enabled(entry.id, True)

    with pytest.raises(ModError, match="角色仍在使用"):
        resources.install(_write_package(tmp_path / "next", version="1.0.1"))
    assert (tmp_path / "data" / "characters" / entry.id / "manifest.json").is_file()


def test_update_keeps_the_enabled_choice_and_retains_the_old_version(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.set_enabled(entry.id, True)

    updated = resources.install(_write_package(tmp_path / "next", version="1.0.1"))
    assert updated.enabled is True
    assert updated.version == "1.0.1"
    assert (tmp_path / "data" / "characters" / entry.id / "manifest.json").is_file()
    assert (tmp_path / "data" / "mod-versions" / entry.id / "1.0.0" / "manifest.json").is_file()


def test_update_of_a_disabled_package_stays_disabled(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    updated = resources.install(_write_package(tmp_path / "next", version="1.0.1"))
    assert updated.enabled is False
    assert updated.path == tmp_path / "data" / "mod-disabled" / entry.id


# --------------------------------------------------------------- removal

def test_resource_removal_refuses_in_use_when_fallback_is_rejected(tmp_path):
    source = _write_package(tmp_path / "source")
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: False)
    entry = resources.install(source)
    outcome = resources.remove(entry.id)
    assert not outcome.success
    assert entry.path.exists() and source.exists()


def test_removal_deletes_the_installed_copy_and_keeps_the_source(tmp_path):
    source = _write_package(tmp_path / "source")
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(source)
    resources.set_enabled(entry.id, True)

    outcome = resources.remove(entry.id)
    assert outcome.success and not outcome.pending
    assert not (tmp_path / "data" / "characters" / entry.id).exists()
    assert not (tmp_path / "data" / "mod-disabled" / entry.id).exists()
    assert source.is_dir()
    assert resources.entries(include_unmanaged=False) == []


def test_removal_deletes_retained_versions_too(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.install(_write_package(tmp_path / "next", version="1.0.1"))
    resources.remove(entry.id)
    assert not (tmp_path / "data" / "mod-versions" / entry.id).exists()


def test_removal_leaves_no_empty_managed_root_behind(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source"))
    resources.set_enabled(entry.id, True)
    resources.remove(entry.id)
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == []


def test_removal_refuses_when_an_unrecognized_retained_copy_exists(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source"))
    stray = tmp_path / "data" / "mod-versions" / entry.id / "9.9.9"
    stray.mkdir(parents=True)
    (stray / "mystery.bin").write_bytes(b"?")

    outcome = resources.remove(entry.id)
    assert not outcome.success
    assert entry.path.exists(), "an unrecognized retained copy must keep the ledger intact"


def test_removal_of_an_unknown_package_raises(tmp_path):
    resources = ResourceMods(tmp_path / "data")
    with pytest.raises(ModError):
        resources.remove("nobody")


# -------------------------------------------------------------- rollback

def test_rollback_restores_the_previous_version(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.set_enabled(entry.id, True)
    resources.install(_write_package(tmp_path / "next", version="1.0.1"))

    outcome = resources.rollback(entry.id)
    assert outcome.success and not outcome.pending
    current = resources.entries(include_unmanaged=False)
    assert [row.version for row in current] == ["1.0.0"]
    assert current[0].enabled is True


def test_rollback_without_a_retained_version_reports_a_settled_failure(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source"))
    outcome = resources.rollback(entry.id)
    assert not outcome.success and not outcome.pending


def test_rollback_refuses_while_the_character_is_still_in_use(tmp_path):
    resources = ResourceMods(tmp_path / "data", prepare_removal=lambda _entry: True)
    entry = resources.install(_write_package(tmp_path / "source", version="1.0.0"))
    resources.install(_write_package(tmp_path / "next", version="1.0.1"))
    resources.prepare_removal = lambda _entry: False

    outcome = resources.rollback(entry.id)
    assert not outcome.success and outcome.pending
