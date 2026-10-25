from __future__ import annotations

import json
import sys
import textwrap
import threading
import zipfile
from pathlib import Path

import pytest

from petcore.chat.session_store import SessionStore
from petcore.config import Config
from petcore.media.click_sound import ClickSoundPair
from petcore.platform.worker import WorkerHost
from petcore.content.importer import install_character_source


_WORKER_WITH_INVALID = textwrap.dedent(
    """
    import json, sys
    protocol = "petcore-worker/v1"
    for raw in sys.stdin:
        message = json.loads(raw)
        if message.get("type") == "hello":
            print(json.dumps({"protocol": protocol, "type": "unknown"}), flush=True)
            print(json.dumps({"protocol": protocol, "type": "ready"}), flush=True)
        elif message.get("type") == "shutdown":
            break
    """
).strip()


def _argv(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_worker_rejects_unknown_protocol_messages_without_delivering_them() -> None:
    errors: list[object] = []
    messages: list[dict] = []
    ready = threading.Event()
    host = WorkerHost()
    session = host.start(
        "invalid-message",
        _argv(_WORKER_WITH_INVALID),
        on_error=lambda error: errors.append(error),
        on_message=lambda message: (messages.append(message), ready.set()),
        heartbeat_timeout=0,
        ready_timeout=2.0,
    )
    try:
        assert ready.wait(2.0)
        assert any("unsupported worker message type" in str(error) for error in errors)
        assert all(message.get("type") != "unknown" for message in messages)
        assert session.shutdown(timeout=1.0) is True
    finally:
        host.shutdown_all(timeout=1.0)


def test_config_migration_records_backup_and_is_retryable(tmp_path, monkeypatch) -> None:
    import petcore.config as config_module

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    legacy.mkdir()
    (legacy / "config.json").write_text(
        json.dumps({"character": "legacy-cat", "scale": 1.2}), encoding="utf-8"
    )
    monkeypatch.setattr(config_module.paths, "legacy_data_roots", lambda: (legacy,))

    config = Config.load(target)
    statuses = [record.status for record in config.migration_records]
    assert "migrated" in statuses
    assert (target / "migration-backup" / "legacy-config.json").is_file()
    assert config.get("character") == "legacy-cat"
    assert (target / "config.json").is_file()

    again = Config.load(target)
    assert any(record.status == "not_needed" for record in again.migration_records)


def test_session_store_records_invalid_schema_without_deleting_file(tmp_path) -> None:
    store = SessionStore(tmp_path, slot=2, character_id="pet")
    store.directory.mkdir(parents=True)
    path = store.directory / "broken.json"
    path.write_text(json.dumps({"schema": 99, "session_id": "broken"}), encoding="utf-8")

    assert store.list_sessions() == []
    assert path.is_file()
    assert store.diagnostics
    assert store.diagnostics[-1].status == "skipped_invalid"


def test_click_sound_pair_is_tokenized_and_idempotent(tmp_path) -> None:
    calls: list[Path] = []
    press = tmp_path / "press.wav"
    release = tmp_path / "release.wav"
    pair = ClickSoundPair(lambda path: calls.append(path) or True)

    token = pair.begin([press])
    assert pair.active_count == 1
    assert pair.release(token, [release]) is True
    assert calls == [press, release]
    assert pair.release(token, [release]) is False
    assert pair.active_count == 0

    cancelled = pair.begin([press])
    assert pair.cancel(cancelled) is True
    assert pair.release(cancelled, [release]) is False
    pair.cancel_all()
    assert pair.active_count == 0


def _write_character_source(root: Path) -> Path:
    source = root / "character"
    videos = source / "videos"
    videos.mkdir(parents=True)
    (videos / "idle.webm").write_bytes(b"fake")
    (source / "manifest.json").write_text(
        json.dumps({"name": "Imported", "body_box": [0, 0, 10, 10]}),
        encoding="utf-8",
    )
    return source


def test_character_zip_import_is_atomic_and_does_not_overwrite(tmp_path) -> None:
    source = _write_character_source(tmp_path)
    archive = tmp_path / "import.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in source.rglob("*"):
            if path.is_file():
                bundle.write(path, Path("bundle") / path.relative_to(source))

    data_root = tmp_path / "data"
    ok, message, character_id = install_character_source(archive, data_root, character_id="zipcat")
    assert ok, message
    assert character_id == "character.zipcat"
    installed = data_root / "mods" / "character.zipcat" / "videos" / "idle.webm"
    assert installed.read_bytes() == b"fake"

    ok, message, _ = install_character_source(archive, data_root, character_id="zipcat")
    assert not ok
    assert "already" in message.lower() or "exists" in message.lower() or "not empty" in message.lower()
    assert installed.read_bytes() == b"fake"


def test_character_zip_import_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "no")

    ok, message, character_id = install_character_source(archive, tmp_path / "data")
    assert not ok
    assert character_id is None
    assert "不安全路径" in message or "越界" in message
    assert not (tmp_path / "escape.txt").exists()
