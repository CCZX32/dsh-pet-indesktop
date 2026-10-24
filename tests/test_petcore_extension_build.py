# -*- coding: utf-8 -*-
"""T05：可复现候选 ZIP 构建器与独立校验器回归。

覆盖点（每条都对着 `docs/superpowers/plans/2026-10-24-petcore-p4c3-distribution.md`
§7 与 `docs/PETCORE-MOD-FORMAT.md` §18）：

1. 同输入两次构建，四个 ZIP 的 sha256/size 完全一致（可复现）；
2. ZIP 条目时间戳/权限/压缩方式固定、名称升序；
3. 白名单只收 `mod.json`、`host/**/*.py`、`resources/**`，噪声（`__pycache__`、
   `*.pyc`、`.trusted`、个人数据、未知文件）既不打包也不静默；
4. 生成清单与 ZIP 实际内容逐字一致；
5. 校验器独立重读 ZIP：正常包通过，改 1 字节 / 只改 sha / 注入 `.trusted` 全部拒绝；
6. ZIP 内路径全是相对 POSIX 且不含 `..`；
7. 生成清单不含本机绝对路径、不含默认索引源；
8. 目标 ZIP 内容不同时拒绝覆盖，`force=True` 才覆盖；
9. `build_index` 的待发布/本地两种形态。

所有构建都指向 `tmp_path`，不污染仓库 `dist-extensions/`。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from scripts.build_petcore_extensions import (
    ZIP_DATE_TIME,
    ZIP_EXTERNAL_ATTR,
    BuildError,
    build_candidates,
    build_index,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKS_DIR = REPO_ROOT / "examples" / "petcore-mods"
CANONICAL_IDS = ("reminder.todo", "fun.festival", "fun.divination", "voice.chime")
BUILDER = REPO_ROOT / "scripts" / "build_petcore_extensions.py"
VERIFIER = REPO_ROOT / "scripts" / "verify_petcore_extensions.py"


def _artifacts(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text("utf-8"))
    return data["artifacts"]


def _by_id(manifest_path: Path) -> dict[str, dict]:
    return {item["id"]: item for item in _artifacts(manifest_path)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_pack(tmp_path: Path, pack_id: str = "reminder.todo") -> Path:
    repo = tmp_path / "repo"
    target = repo / "examples" / "petcore-mods" / pack_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PACKS_DIR / pack_id, target)
    return repo


def _run_verifier(manifest_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFIER), "--candidate-manifest", str(manifest_path), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------------------- #
# 1. 可复现
# --------------------------------------------------------------------------- #


def test_two_builds_produce_identical_archives(tmp_path: Path) -> None:
    first = build_candidates(REPO_ROOT, tmp_path / "a")
    second = build_candidates(REPO_ROOT, tmp_path / "b")

    first_artifacts = _artifacts(first)
    assert {item["id"] for item in first_artifacts} == set(CANONICAL_IDS)
    assert first_artifacts == _artifacts(second)

    for item in first_artifacts:
        left = (tmp_path / "a" / item["file"]).read_bytes()
        right = (tmp_path / "b" / item["file"]).read_bytes()
        assert hashlib.sha256(left).hexdigest() == item["sha256"]
        assert left == right, f"{item['id']} 两次构建字节不一致"
        assert len(left) == item["size"]


def test_zip_entries_are_deterministic(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    for item in _artifacts(manifest):
        archive = tmp_path / "out" / item["file"]
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
        assert names == sorted(names), "条目必须按名称升序"
        assert len(names) == len(set(names)), "条目名不得重复"
        for info in infos:
            assert info.date_time == ZIP_DATE_TIME
            assert info.external_attr == ZIP_EXTERNAL_ATTR
            assert info.compress_type == zipfile.ZIP_DEFLATED
        assert item["files"] == names


# --------------------------------------------------------------------------- #
# 2. 白名单
# --------------------------------------------------------------------------- #


def test_build_whitelist_skips_noise_and_reports_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _copy_pack(tmp_path)
    pack = repo / "examples" / "petcore-mods" / "reminder.todo"
    (pack / "host" / "__pycache__").mkdir(exist_ok=True)
    (pack / "host" / "__pycache__" / "stale.cpython-312.pyc").write_bytes(b"junk")
    (pack / "host" / "legacy.pyc").write_bytes(b"junk")
    (pack / ".trusted").write_text("", "utf-8")
    (pack / "notes.txt").write_text("scratch", "utf-8")
    (pack / "install.json").write_text("{}", "utf-8")
    (pack / "data").mkdir()
    (pack / "data" / "todo.json").write_text("{}", "utf-8")
    (pack / "resources").mkdir()
    (pack / "resources" / "chime.txt").write_text("ding", "utf-8")

    manifest = build_candidates(repo, tmp_path / "out", packs=("reminder.todo",))
    captured = capsys.readouterr().out
    artifact = _by_id(manifest)["reminder.todo"]

    archive = tmp_path / "out" / artifact["file"]
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()

    assert "mod.json" in names
    assert "resources/chime.txt" in names
    assert "host/__init__.py" in names
    for name in names:
        assert "__pycache__" not in name
        assert not name.endswith(".pyc")
        assert not PurePosixPath(name).name.startswith(".")
        assert name == "mod.json" or name.startswith(("host/", "resources/")), name
    assert ".trusted" not in names
    assert "notes.txt" not in names
    assert "install.json" not in names
    assert "data/todo.json" not in names

    assert artifact["excluded_unknown"] == ["notes.txt"]
    assert ".trusted" in artifact["excluded_blocked"]
    assert "install.json" in artifact["excluded_blocked"]
    assert "data/todo.json" in artifact["excluded_blocked"]
    assert "host/legacy.pyc" in artifact["excluded_generated"]
    assert "unknown" in captured.lower()
    assert "notes.txt" in captured


def test_strict_mode_rejects_unknown_files(tmp_path: Path) -> None:
    repo = _copy_pack(tmp_path)
    pack = repo / "examples" / "petcore-mods" / "reminder.todo"
    (pack / "notes.txt").write_text("scratch", "utf-8")

    with pytest.raises(BuildError):
        build_candidates(repo, tmp_path / "out", packs=("reminder.todo",), strict=True)
    # 失败不得留下半成品 ZIP 或清单
    out = tmp_path / "out"
    assert not list(out.glob("*.zip")) if out.exists() else True
    assert not (out / "candidate-manifest.json").exists()


def test_missing_pack_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(BuildError):
        build_candidates(REPO_ROOT, tmp_path / "out", packs=("not.a.pack",))


def test_output_dir_inside_pack_is_rejected(tmp_path: Path) -> None:
    repo = _copy_pack(tmp_path)
    pack = repo / "examples" / "petcore-mods" / "reminder.todo"
    with pytest.raises(BuildError):
        build_candidates(repo, pack / "dist", packs=("reminder.todo",))


# --------------------------------------------------------------------------- #
# 3. 清单 <-> ZIP
# --------------------------------------------------------------------------- #


def test_manifest_matches_archive_contents(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    for item in _artifacts(manifest):
        archive = tmp_path / "out" / item["file"]
        assert archive.name == item["file"]
        assert item["size"] == archive.stat().st_size
        assert item["sha256"] == _sha256(archive)
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            raw = json.loads(zf.read("mod.json").decode("utf-8"))
        assert item["files"] == names
        for key in ("id", "version", "kind", "api_version", "core_requires", "entrypoint"):
            assert item[key] == raw[key], f"{item['id']}: {key} 与 mod.json 不一致"


def test_zip_paths_are_relative_posix(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    for item in _artifacts(manifest):
        with zipfile.ZipFile(tmp_path / "out" / item["file"]) as zf:
            names = zf.namelist()
        assert names
        for name in names:
            assert not name.startswith("/")
            assert "\\" not in name
            assert ".." not in name.split("/")
            assert not name.startswith("~")
            assert not (len(name) > 1 and name[1] == ":"), f"绝对路径: {name}"
            assert all(part and part not in (".", "..") for part in name.split("/"))


def test_candidate_manifest_is_portable_and_versioned(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    text = manifest.read_text("utf-8")
    data = json.loads(text)

    assert data["schema_version"] == 1
    assert data["status"] == "pending-publication"
    assert data["generated_by"] == "scripts/build_petcore_extensions.py"
    assert data["api_version"] == "1"
    assert data["core_version"]
    assert "index" not in text.lower() or "index_url" not in text
    assert "raw.githubusercontent.com" not in text
    assert str(tmp_path) not in text
    assert str(REPO_ROOT) not in text
    assert "://" not in text

    for item in data["artifacts"]:
        for key in (
            "id",
            "version",
            "kind",
            "size",
            "sha256",
            "files",
            "core_requires",
            "api_version",
            "entrypoint",
        ):
            assert key in item
        assert item["files"] == sorted(item["files"])


# --------------------------------------------------------------------------- #
# 4. 独立校验器
# --------------------------------------------------------------------------- #


def test_verifier_accepts_clean_build(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    result = _run_verifier(manifest)
    assert result.returncode == 0, result.stderr
    for pack_id in CANONICAL_IDS:
        assert pack_id in result.stdout
    assert "verified 4/4" in result.stdout


def test_verifier_rejects_byte_appended_archive(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    artifact = _by_id(manifest)["reminder.todo"]
    archive = tmp_path / "out" / artifact["file"]
    archive.write_bytes(archive.read_bytes() + b"\x00")

    result = _run_verifier(manifest)
    assert result.returncode != 0
    assert "reminder.todo" in result.stderr
    assert "size" in result.stderr.lower() or "sha256" in result.stderr.lower()


def test_verifier_rejects_manifest_sha_edit(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    data = json.loads(manifest.read_text("utf-8"))
    data["artifacts"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data, indent=2), "utf-8")

    result = _run_verifier(manifest)
    assert result.returncode != 0
    assert "sha256" in result.stderr.lower()


def test_verifier_rejects_trusted_marker_injected_into_zip(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    artifact = _by_id(manifest)["reminder.todo"]
    archive = tmp_path / "out" / artifact["file"]

    # 注入 .trusted 后把 size/sha/files 都改「对」，只有成员白名单能拒绝它。
    with zipfile.ZipFile(archive) as zf:
        members = [(info.filename, zf.read(info.filename)) for info in zf.infolist()]
    members.append((".trusted", b""))
    members.sort(key=lambda item: item[0])
    buffer = archive.with_suffix(".tmp")
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ZIP_EXTERNAL_ATTR
            zf.writestr(info, payload)
    buffer.replace(archive)

    data = json.loads(manifest.read_text("utf-8"))
    for item in data["artifacts"]:
        if item["id"] != artifact["id"]:
            continue
        item["size"] = archive.stat().st_size
        item["sha256"] = _sha256(archive)
        item["files"] = [name for name, _ in members]
    manifest.write_text(json.dumps(data, indent=2), "utf-8")

    result = _run_verifier(manifest)
    assert result.returncode != 0
    assert ".trusted" in result.stderr


# --------------------------------------------------------------------------- #
# 5. 目标覆盖与索引
# --------------------------------------------------------------------------- #


def test_build_refuses_overwrite_of_different_archive(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    artifact = _by_id(manifest)["fun.divination"]
    archive = tmp_path / "out" / artifact["file"]
    archive.write_bytes(b"not really a zip")

    with pytest.raises(BuildError):
        build_candidates(REPO_ROOT, tmp_path / "out")

    rebuilt = build_candidates(REPO_ROOT, tmp_path / "out", force=True)
    assert _by_id(rebuilt)["fun.divination"]["sha256"] == artifact["sha256"]
    assert archive.stat().st_size == artifact["size"]


def test_build_index_pending_and_local(tmp_path: Path) -> None:
    manifest = build_candidates(REPO_ROOT, tmp_path / "out")
    pending = build_index(manifest)
    assert pending["schema_version"] == 1
    assert {pkg["id"] for pkg in pending["packages"]} == set(CANONICAL_IDS)
    for pkg in pending["packages"]:
        assert pkg["blocked"] is True
        assert "待发布" in pkg["blocked_reason"]
        assert pkg["certified"] is False
        assert pkg["platforms"] == []
        version = pkg["versions"][0]
        assert version["urls"][0].startswith("https://")
        assert version["size"] > 0
        assert len(version["sha256"]) == 64
        assert "released_at" not in version

    published = build_index(manifest, state="published")
    for pkg in published["packages"]:
        assert pkg["blocked"] is False
        assert pkg["blocked_reason"] == ""
        assert pkg["versions"][0]["urls"][0].startswith("https://")

    local = build_index(manifest, local=True)
    for pkg in local["packages"]:
        assert pkg["blocked"] is False
        assert pkg["versions"][0]["urls"][0].startswith("file://")
        artifact = _by_id(manifest)[pkg["id"]]
        assert pkg["versions"][0]["sha256"] == artifact["sha256"]
        assert pkg["versions"][0]["size"] == artifact["size"]


def test_cli_build_and_verify_single_pack(tmp_path: Path) -> None:
    out = tmp_path / "cli-out"
    build = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--repo-root",
            str(REPO_ROOT),
            "--out",
            str(out),
            "--packs",
            "voice.chime",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    manifest = out / "candidate-manifest.json"
    assert manifest.is_file()

    verify = _run_verifier(manifest, "--allow-subset")
    assert verify.returncode == 0, verify.stderr

    # 默认要求四包齐全：单包清单在默认模式下必须被拒绝。
    strict = _run_verifier(manifest)
    assert strict.returncode != 0
