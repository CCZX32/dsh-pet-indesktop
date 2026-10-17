# -*- coding: utf-8 -*-
"""资源包事务日志：形状、原子读写与三阶段恢复矩阵（真目录，不走 GUI）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pet.mod_management import ModError, ResourceMods
from pet.mod_transactions import JournalError, ModJournal
from tests.mod_package_fakes import write_package


def _resources(root: Path, **kwargs) -> ResourceMods:
    return ResourceMods(root / "data", **kwargs)


def _install(resources: ResourceMods, root: Path, version: str, video: bytes) -> str:
    package = write_package(root / f"src-{version}", version=version, video=video)
    entry = resources.install(package)
    resources.set_enabled(entry.id, True)
    return entry.id


def _journal_for(resources: ResourceMods) -> ModJournal:
    return ModJournal(resources.staging_root)


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    source.rename(target)


def test_journal_round_trips_and_advances_phases(tmp_path):
    journal = ModJournal(tmp_path / "staging")
    record = journal.begin(
        kind="install",
        character_id="demo",
        target=tmp_path / "data" / "characters" / "demo",
        retained=tmp_path / "data" / "mod-versions" / "demo" / "1.0.0",
        incoming=tmp_path / "data" / "mod-staging" / "incoming",
        from_version="1.0.0",
        to_version="2.0.0",
    )
    assert record.phase == "prepared"
    assert [item.operation_id for item in journal.records()] == [record.operation_id]

    record = journal.advance(record, "version_removed")
    assert journal.records()[0].phase == "version_removed"

    journal.finish(record)
    assert journal.records() == []


def test_a_malformed_record_is_not_silently_ignored(tmp_path):
    journal = ModJournal(tmp_path / "staging")
    journal.root.mkdir(parents=True)
    (journal.root / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(JournalError, match="unreadable"):
        journal.records()


def test_an_identity_conflict_is_reported(tmp_path):
    journal = ModJournal(tmp_path / "staging")
    record = journal.begin(
        kind="remove",
        character_id="demo",
        target=tmp_path / "target",
        from_version="1.0.0",
        to_version="",
        targets=[tmp_path / "target"],
    )
    renamed = journal.root / "different.json"
    journal._path(record.operation_id).rename(renamed)

    with pytest.raises(JournalError, match="identity_conflict"):
        journal.records()


def test_recovery_restores_the_old_version_after_version_removed(tmp_path):
    resources = _resources(tmp_path)
    _install(resources, tmp_path / "one", "1.0.0", b"v1")
    live = resources.live_root / "demo"
    retained = resources.retained_root / "demo" / "1.0.0"
    _move(live, retained)
    journal = _journal_for(resources)
    journal.begin(
        kind="install",
        character_id="demo",
        target=live,
        retained=retained,
        incoming=resources.staging_root / "incoming",
        from_version="1.0.0",
        to_version="2.0.0",
    ).operation_id

    recovered = _resources(tmp_path)

    assert (recovered.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v1"
    assert recovered.recovery_diagnostics == []
    assert _journal_for(recovered).records() == []


def test_recovery_accepts_a_verified_swapped_version(tmp_path):
    resources = _resources(tmp_path)
    _install(resources, tmp_path / "one", "1.0.0", b"v1")
    live = resources.live_root / "demo"
    retained = resources.retained_root / "demo" / "1.0.0"
    _move(live, retained)
    new = write_package(tmp_path / "two", version="2.0.0", video=b"v2")
    shutil.copytree(new, live)
    journal = _journal_for(resources)
    record = journal.begin(
        kind="install",
        character_id="demo",
        target=live,
        retained=retained,
        incoming=resources.staging_root / "incoming",
        from_version="1.0.0",
        to_version="2.0.0",
    )
    journal.advance(record, "version_removed")
    journal.advance(record, "swapped")

    recovered = _resources(tmp_path)

    assert (recovered.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v2"
    assert recovered.recovery_diagnostics == []
    assert _journal_for(recovered).records() == []


def test_recovery_rolls_back_a_swapped_version_that_fails_its_check(tmp_path):
    resources = _resources(tmp_path)
    _install(resources, tmp_path / "one", "1.0.0", b"v1")
    live = resources.live_root / "demo"
    retained = resources.retained_root / "demo" / "1.0.0"
    _move(live, retained)
    # A landed tree with no videos can never pass the strict gate.
    live.mkdir(parents=True)
    (live / "manifest.json").write_text("{}", encoding="utf-8")
    journal = _journal_for(resources)
    record = journal.begin(
        kind="install",
        character_id="demo",
        target=live,
        retained=retained,
        incoming=resources.staging_root / "incoming",
        from_version="1.0.0",
        to_version="2.0.0",
    )
    journal.advance(record, "version_removed")
    journal.advance(record, "swapped")

    recovered = _resources(tmp_path)

    assert (recovered.live_root / "demo" / "videos" / "idle.webm").read_bytes() == b"v1"
    assert recovered.recovery_diagnostics == []


def test_recovery_retries_a_partial_remove(tmp_path):
    resources = _resources(tmp_path)
    _install(resources, tmp_path / "one", "1.0.0", b"v1")
    live = resources.live_root / "demo"
    retained_parent = resources.retained_root / "demo"
    journal = _journal_for(resources)
    record = journal.begin(
        kind="remove",
        character_id="demo",
        target=live,
        from_version="1.0.0",
        to_version="",
        targets=[live, retained_parent],
    )
    journal.advance(record, "deleted")
    shutil.rmtree(live)  # partially applied before the crash

    recovered = _resources(tmp_path)

    assert not (recovered.live_root / "demo").exists()
    assert not (recovered.retained_root / "demo").exists()
    assert recovered.recovery_diagnostics == []


def test_an_ambiguous_state_is_kept_and_blocks_destructive_operations(tmp_path):
    resources = _resources(tmp_path)
    journal = _journal_for(resources)
    journal.begin(
        kind="install",
        character_id="demo",
        target=resources.live_root / "demo",
        retained=resources.retained_root / "demo" / "1.0.0",
        incoming=None,
        from_version="1.0.0",
        to_version="2.0.0",
    )

    recovered = _resources(tmp_path)

    assert recovered.recovery_diagnostics
    assert len(_journal_for(recovered).records()) == 1
    with pytest.raises(ModError, match="没有收尾"):
        recovered.install(write_package(tmp_path / "new", version="3.0.0"))


def test_a_journal_pointing_outside_the_data_root_is_refused(tmp_path):
    resources = _resources(tmp_path)
    journal = _journal_for(resources)
    outside = tmp_path / "outside"
    outside.mkdir()
    record = journal.begin(
        kind="install",
        character_id="demo",
        target=outside,
        from_version="1.0.0",
        to_version="2.0.0",
    )
    assert record.operation_id

    recovered = _resources(tmp_path)

    assert any("越界" in message for message in recovered.recovery_diagnostics)


def test_journal_json_is_plain_and_stable(tmp_path):
    journal = ModJournal(tmp_path / "staging")
    record = journal.begin(
        kind="activate",
        character_id="demo",
        target=tmp_path / "live",
        retained=tmp_path / "stash",
        incoming=tmp_path / "retained",
        from_version="2.0.0",
        to_version="1.0.0",
    )
    document = json.loads(journal._path(record.operation_id).read_text(encoding="utf-8"))
    assert document["operation_id"] == record.operation_id
    assert document["kind"] == "activate"
    assert document["phase"] == "prepared"
