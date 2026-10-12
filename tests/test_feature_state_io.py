"""Bounded local metadata I/O: atomic replace, path safety, kernel locks.

Ported from the DLC branch blueprint (`tests/test_feature_state_io.py`) and
extended to the seams the MOD center depends on. Host-neutral: no Qt, no
config, no overlay surface.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from pet import feature_state_io as io


# --------------------------------------------------------------- atomic_write

@pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing semantics")
def test_atomic_write_retries_a_real_transient_windows_reader(tmp_path, monkeypatch):
    path = tmp_path / "transaction.json"
    path.write_bytes(b"old")
    reader = path.open("rb")
    replace = os.replace
    failures = []

    def observed_replace(source, target):
        try:
            return replace(source, target)
        except PermissionError as exc:
            # The actual OS denies replacing an open Python reader. Release
            # only after observing that denial, without guessing a sleep time.
            failures.append(exc.winerror)
            assert path.read_bytes() == b"old"
            reader.close()
            raise

    monkeypatch.setattr(io.os, "replace", observed_replace)
    try:
        io.atomic_write(path, b"new")
    finally:
        reader.close()
    assert failures and set(failures) <= {5, 32}
    assert path.read_bytes() == b"new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["transaction.json"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing semantics")
def test_atomic_write_does_not_hide_persistent_windows_denial(tmp_path):
    path = tmp_path / "transaction.json"
    path.write_bytes(b"old")
    start = time.monotonic()
    with path.open("rb"), pytest.raises(PermissionError):
        io.atomic_write(path, b"new")
    assert time.monotonic() - start < 5  # bounded failure, wide CI budget
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["transaction.json"]


def test_atomic_write_does_not_retry_other_os_errors(tmp_path, monkeypatch):
    path = tmp_path / "transaction.json"
    path.write_bytes(b"old")
    attempts = []

    def unavailable(source, target):
        attempts.append(target)
        raise OSError("simulated unavailable filesystem")

    monkeypatch.setattr(io.os, "replace", unavailable)
    with pytest.raises(OSError, match="unavailable"):
        io.atomic_write(path, b"new")
    assert len(attempts) == 1
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["transaction.json"]


def test_atomic_write_creates_missing_parents_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "nested" / "deeper" / "mod-catalog.revision"
    io.atomic_write(path, b"token")
    assert path.read_bytes() == b"token"
    assert [p.name for p in path.parent.iterdir()] == ["mod-catalog.revision"]


def test_atomic_write_replaces_existing_content_without_a_reader_window(tmp_path):
    path = tmp_path / "state.json"
    io.atomic_write(path, b"first")
    io.atomic_write(path, b"second")
    assert path.read_bytes() == b"second"


# ------------------------------------------------------------ path + read

def test_safe_path_rejects_a_symlinked_ancestor(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")
    with pytest.raises(io.StateError) as exc:
        io.safe_path(link / "child.json")
    assert exc.value.code == "unsafe_path"


def test_safe_path_rejects_hardlinked_metadata(tmp_path):
    original = tmp_path / "a.json"
    original.write_bytes(b"x")
    linked = tmp_path / "b.json"
    try:
        os.link(original, linked)
    except (OSError, NotImplementedError):
        pytest.skip("hardlink creation is not permitted on this host")
    with pytest.raises(io.StateError) as exc:
        io.safe_path(linked)
    assert exc.value.code == "unsafe_path"


def test_safe_path_accepts_a_plain_existing_directory(tmp_path):
    target = tmp_path / "logs" / "state.json"
    (tmp_path / "logs").mkdir()
    io.safe_path(target)


def test_safe_path_rejects_a_non_directory_ancestor(tmp_path):
    file_path = tmp_path / "afile"
    file_path.write_bytes(b"x")
    with pytest.raises(io.StateError) as exc:
        io.safe_path(file_path / "child.json")
    assert exc.value.code == "io_error"


def test_read_bytes_is_bounded(tmp_path):
    path = tmp_path / "journal.json"
    path.write_bytes(b"x" * 32)
    assert io.read_bytes(path, 32) == b"x" * 32
    with pytest.raises(io.StateError) as exc:
        io.read_bytes(path, 31)
    assert exc.value.code == "metadata_limit"


# ------------------------------------------------------------- kernel locks

def test_open_kernel_lock_is_exclusive_until_closed(tmp_path):
    path = tmp_path / "locks" / "management.lock"
    holder = io.open_kernel_lock(path)
    try:
        with pytest.raises(io.StateError) as exc:
            io.open_kernel_lock(path)
        assert exc.value.code == "lock_busy"
    finally:
        holder.close()
    assert holder.closed
    io.open_kernel_lock(path).close()


def test_open_kernel_lock_without_create_reports_missing(tmp_path):
    with pytest.raises(io.StateError) as exc:
        io.open_kernel_lock(tmp_path / "absent.lock", create=False)
    assert exc.value.code == "missing"


def test_kernel_lock_context_manager_releases_on_exit(tmp_path):
    path = tmp_path / "locks" / "operation.lock"
    with io.open_kernel_lock(path):
        pass
    with io.open_kernel_lock(path):
        pass


def test_state_lock_reports_busy_when_timeout_is_zero(tmp_path):
    path = tmp_path / "locks" / "state.lock"
    holder = io.open_kernel_lock(path)
    try:
        with pytest.raises(io.StateError) as exc:
            with io.state_lock(path):
                raise AssertionError("must not enter while the lock is held")
        assert exc.value.code == "lock_busy"
    finally:
        holder.close()


def test_state_lock_waits_for_a_transient_holder_within_budget(tmp_path):
    path = tmp_path / "locks" / "state.lock"
    holder = io.open_kernel_lock(path)
    released = threading.Event()

    def release_later():
        time.sleep(0.05)
        holder.close()
        released.set()

    thread = threading.Thread(target=release_later, daemon=True)
    thread.start()
    entered = []
    with io.state_lock(path, timeout=1.0):
        entered.append(True)
    thread.join(5)
    assert released.is_set()
    assert entered == [True]


def test_state_lock_without_create_yields_to_a_missing_target(tmp_path):
    entered = []
    with io.state_lock(tmp_path / "absent.lock", create=False, exclusive=False):
        entered.append(True)
    assert entered == [True]
    assert not (tmp_path / "absent.lock").exists()


def test_state_lock_does_not_relabel_an_error_from_its_body(tmp_path):
    path = tmp_path / "locks" / "state.lock"
    with pytest.raises(io.StateError) as exc:
        with io.state_lock(path):
            raise io.StateError("journal_corrupt")
    assert exc.value.code == "journal_corrupt"


def test_state_lock_releases_the_kernel_lock_after_the_body(tmp_path):
    path = tmp_path / "locks" / "state.lock"
    with io.state_lock(path):
        pass
    probe = io.open_kernel_lock(path)
    probe.close()
