"""远程包解包预算（T03）：预检声明、写入计数、失败不留半包。

预算只由市场通道显式传入（`limits=`）；本地目录 / ZIP 安装传 ``None``，行为不变。
"""

from __future__ import annotations

import copy
import json
import stat
import zipfile
from pathlib import Path

import pytest

from petcore.contracts.archive import ArchiveLimits, BudgetExceeded
from petcore.mods.install import install, open_pack

GENEROUS = ArchiveLimits(1 << 20, 1 << 20, 100)


def _manifest(**overrides) -> bytes:
    payload = {
        "schema": 1,
        "id": "character.demo",
        "kind": "content",
        "name": "Demo",
        "version": "1.0.0",
        "api_version": "1",
        "character": {"id": "demo", "media_dir": "media"},
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def _make_zip(
    path: Path, files: dict[str, bytes], *, dirs: tuple[str, ...] = ()
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in dirs:
            archive.writestr(zipfile.ZipInfo(name.rstrip("/") + "/"), b"")
        for name, body in files.items():
            archive.writestr(name, body)
    return path


def _declared_bytes(archive: Path) -> int:
    with zipfile.ZipFile(archive) as handle:
        return sum(info.file_size for info in handle.infolist())


def test_entry_count_counts_directories_and_writes_nothing(tmp_path):
    archive = _make_zip(
        tmp_path / "pack.zip",
        {"mod.json": _manifest(), "media/a.txt": b"a", "media/b.txt": b"b"},
        dirs=("media",),
    )
    work = tmp_path / "work"

    with pytest.raises(BudgetExceeded) as caught:
        with open_pack(archive, work, limits=ArchiveLimits(1 << 20, 1 << 20, 3)):
            pass

    assert (caught.value.kind, caught.value.limit, caught.value.actual) == ("entries", 3, 4)
    assert work.is_dir() and list(work.iterdir()) == []


def test_declared_expanded_bytes_over_limit_writes_nothing(tmp_path):
    archive = _make_zip(
        tmp_path / "pack.zip",
        {"mod.json": _manifest(), "media/big.bin": b"x" * 4096},
    )
    declared = _declared_bytes(archive)
    assert declared > 1024
    work = tmp_path / "work"

    with pytest.raises(BudgetExceeded) as caught:
        with open_pack(archive, work, limits=ArchiveLimits(1 << 20, 1024, 100)):
            pass

    assert caught.value.kind == "expanded"
    assert (caught.value.limit, caught.value.actual) == (1024, declared)
    assert work.is_dir() and list(work.iterdir()) == []


def test_declared_size_lie_is_stopped_by_the_write_counter(tmp_path, monkeypatch):
    """声明小、实际大：预检按 ZipInfo.file_size 放行，写入计数按实际字节拦下。

    本用例只测计数路径：真实 zip 的中央目录由 zipfile 正确写入，不会撒谎；
    这里把 ``infolist()`` 的声明改成小值模拟撒谎的中央目录，并在 ``open()``
    里把真实长度还给解压流——否则 zipfile 会按声明截断读取，根本走不到
    我们的计数循环。
    """
    body = b"y" * 8192
    archive = _make_zip(
        tmp_path / "pack.zip", {"mod.json": _manifest(), "media/big.bin": body}
    )
    assert len(_manifest()) + 16 <= 2048  # 声明值必须低于预算，否则测的是预检
    real_infolist = zipfile.ZipFile.infolist

    def lying_infolist(self):
        clones = []
        for info in real_infolist(self):
            clone = copy.copy(info)
            if clone.filename == "media/big.bin":
                clone.file_size = 16
            clones.append(clone)
        return clones

    real_open = zipfile.ZipFile.open

    def lying_open(self, name, *args, **kwargs):
        stream = real_open(self, name, *args, **kwargs)
        if getattr(name, "filename", "") == "media/big.bin":
            stream._left = len(body)
        return stream

    monkeypatch.setattr(zipfile.ZipFile, "infolist", lying_infolist)
    monkeypatch.setattr(zipfile.ZipFile, "open", lying_open)
    work = tmp_path / "work"

    with pytest.raises(BudgetExceeded) as caught:
        with open_pack(archive, work, limits=ArchiveLimits(1 << 20, 2048, 100)):
            pass

    assert caught.value.kind == "expanded"
    assert caught.value.limit == 2048
    assert caught.value.actual > 2048
    assert work.is_dir() and list(work.iterdir()) == []


def test_install_within_limits_installs_normally(tmp_path):
    root = tmp_path / "data"
    archive = _make_zip(
        tmp_path / "pack.zip",
        {"mod.json": _manifest(), "media/idle.png": b"image-bytes"},
    )

    ok, message = install(archive, root, limits=GENEROUS)

    assert ok, message
    target = root / "mods" / "character.demo"
    assert (target / "media" / "idle.png").read_bytes() == b"image-bytes"
    assert json.loads((target / "install.json").read_text(encoding="utf-8"))["id"] == (
        "character.demo"
    )
    assert not list((root / "mods").glob(".unpack-*"))
    assert not list((root / "mods").glob(".staging-*"))


def test_limits_none_keeps_todays_behaviour(tmp_path):
    archive = _make_zip(
        tmp_path / "pack.zip",
        {"mod.json": _manifest(), "media/big.bin": b"z" * 8192},
    )
    source_dir = tmp_path / "src" / "demo"
    source_dir.mkdir(parents=True)
    (source_dir / "mod.json").write_bytes(_manifest(version="2.0.0"))
    (source_dir / "media").mkdir()
    (source_dir / "media" / "idle.png").write_bytes(b"image")

    zip_root = tmp_path / "zip-data"
    ok, message = install(archive, zip_root)
    assert ok, message
    assert (zip_root / "mods" / "character.demo" / "media" / "big.bin").stat().st_size == 8192

    dir_root = tmp_path / "dir-data"
    ok, message = install(source_dir, dir_root)
    assert ok, message
    assert (dir_root / "mods" / "character.demo" / "media" / "idle.png").is_file()

    with open_pack(archive) as pack:
        assert (pack / "mod.json").is_file()


def test_budget_failure_leaves_no_staging_and_keeps_the_old_install(tmp_path):
    root = tmp_path / "data"
    old = _make_zip(
        tmp_path / "v1.zip",
        {"mod.json": _manifest(version="1.0.0"), "media/old.txt": b"old"},
    )
    assert install(old, root)[0]
    target = root / "mods" / "character.demo"

    huge = _make_zip(
        tmp_path / "v2.zip",
        {"mod.json": _manifest(version="2.0.0"), "media/big.bin": b"z" * 4096},
    )
    ok, message = install(huge, root, force=True, limits=ArchiveLimits(1 << 20, 1024, 100))

    assert not ok
    assert "expanded budget exceeded" in message
    assert json.loads((target / "mod.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
    assert (target / "media" / "old.txt").read_bytes() == b"old"
    mods = root / "mods"
    assert not list(mods.glob(".unpack-*"))
    assert not list(mods.glob(".staging-*"))
    assert not list(mods.glob(".trash-*"))


def test_entry_budget_failure_in_install_reports_and_leaves_nothing(tmp_path):
    root = tmp_path / "data"
    archive = _make_zip(
        tmp_path / "pack.zip",
        {"mod.json": _manifest(), "media/a.txt": b"a", "media/b.txt": b"b"},
        dirs=("media",),
    )

    ok, message = install(archive, root, limits=ArchiveLimits(1 << 20, 1 << 20, 2))

    assert not ok
    assert "entries budget exceeded" in message
    assert not (root / "mods" / "character.demo").exists()
    assert not list((root / "mods").glob(".unpack-*"))
    assert not list((root / "mods").glob(".staging-*"))


def test_path_escape_is_still_rejected_with_limits(tmp_path):
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", _manifest())
        handle.writestr("../evil.txt", "escaped")

    ok, message = install(archive, tmp_path / "data", limits=GENEROUS)

    assert not ok
    assert "unsafe zip entry" in message
    assert not (tmp_path / "evil.txt").exists()
    assert not list((tmp_path / "data" / "mods").glob(".unpack-*"))


def test_symlink_entry_is_still_rejected_with_limits(tmp_path):
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mod.json", _manifest())
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        handle.writestr(link, "../../outside")

    ok, message = install(archive, tmp_path / "data", limits=GENEROUS)

    assert not ok
    assert "symlink entry rejected" in message
    assert not (tmp_path / "outside").exists()
    assert not list((tmp_path / "data" / "mods").glob(".unpack-*"))
