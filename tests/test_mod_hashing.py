# -*- coding: utf-8 -*-
"""资源包逻辑摘要：目录与 ZIP 同 digest、跳过清单、拒绝越界与符号链接。"""

from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from pet.mod_hashing import (
    content_sha256,
    safe_relative_path,
    sha256_directory,
    sha256_zip,
    validate_zip_members,
)


def _write_tree(root: Path, *, video: bytes = b"video", manifest: bytes = b'{"id":"demo"}') -> Path:
    package = root / "package"
    (package / "videos").mkdir(parents=True)
    (package / "videos" / "idle.webm").write_bytes(video)
    (package / "manifest.json").write_bytes(manifest)
    return package


def _zip_tree(source: Path, target: Path) -> Path:
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return target


def test_directory_and_zip_share_one_logical_digest(tmp_path):
    source = _write_tree(tmp_path / "source")
    archive = _zip_tree(source, tmp_path / "package.zip")

    assert sha256_directory(source) == sha256_zip(archive) == content_sha256(archive)
    assert content_sha256(source) == content_sha256(archive)


def test_the_manifest_itself_is_not_part_of_the_digest(tmp_path):
    source = _write_tree(tmp_path / "source")
    before = content_sha256(source)
    (source / "manifest.json").write_bytes(b'{"id":"demo","name":"changed"}')

    assert content_sha256(source) == before


def test_any_content_byte_changes_the_digest(tmp_path):
    source = _write_tree(tmp_path / "source")
    before = content_sha256(source)
    (source / "videos" / "idle.webm").write_bytes(b"other-video")

    assert content_sha256(source) != before


def test_relative_path_is_part_of_the_digest(tmp_path):
    first = _write_tree(tmp_path / "first")
    second = _write_tree(tmp_path / "second")
    second.joinpath("videos", "idle.webm").rename(second.joinpath("videos", "other.webm"))

    assert content_sha256(first) != content_sha256(second)


def test_symlinks_are_rejected(tmp_path):
    source = _write_tree(tmp_path / "source")
    link = source / "videos" / "link.webm"
    try:
        os.symlink(source / "videos" / "idle.webm", link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symlinks without extra privileges")

    with pytest.raises(ValueError, match="symlink"):
        sha256_directory(source)


def test_zip_members_reject_traversal_duplicates_and_symlinks(tmp_path):
    traversal = tmp_path / "traversal.zip"
    with ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.webm", b"x")
    with pytest.raises(ValueError, match="unsafe relative path"):
        sha256_zip(traversal)

    duplicate = tmp_path / "duplicate.zip"
    with ZipFile(duplicate, "w") as archive:
        archive.writestr("videos/idle.webm", b"one")
        archive.writestr("videos/idle.webm", b"two")
    with pytest.raises(ValueError, match="duplicate"):
        sha256_zip(duplicate)

    with ZipFile(tmp_path / "fine.zip", "w") as archive:
        archive.writestr("videos/idle.webm", b"one")
    with ZipFile(tmp_path / "fine.zip") as archive:
        assert len(validate_zip_members(archive)) == 1


def test_safe_relative_path_rejects_absolute_and_empty_segments():
    for unsafe in ("../x", "/abs/x", "a//b", "a/./b", "C:/x"):
        with pytest.raises(ValueError):
            safe_relative_path(unsafe)
    assert safe_relative_path("videos/idle.webm").as_posix() == "videos/idle.webm"


def test_unsupported_sources_are_refused(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_text("not a package", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        content_sha256(plain)
