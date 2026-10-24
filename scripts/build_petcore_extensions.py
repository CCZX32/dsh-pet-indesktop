# -*- coding: utf-8 -*-
"""T05：可复现的 petcore 候选扩展 ZIP 构建器。

把 ``examples/petcore-mods/<id>/`` 打包成 ``<out>/<id>-<version>.zip`` 并写出
``<out>/candidate-manifest.json``（构建证据，不是市场索引）。

设计约束（`docs/PETCORE-MOD-FORMAT.md` §18、分发计划 §7）：

* **白名单**：只收 ``mod.json``、``host/**/*.py``、``resources/**``；``__pycache__``、
  ``*.pyc``、隐藏文件（含 ``.trusted`` / ``.git*`` / ``.DS_Store``）、安装器状态
  （``install.json`` / ``mods-state.json``）、个人数据目录（``data/`` 等）与未知文件
  一律不打包，并且**逐类计数打印**，不静默吞掉；``--strict`` 把未知文件升级为失败。
* **可复现**：条目按名称升序，``date_time`` 固定 ``(1980, 1, 1, 0, 0, 0)``，
  ``create_system=3`` + ``external_attr=0o644<<16``，``ZIP_DEFLATED`` 固定等级。
  不读环境变量、不写时间戳/绝对路径，因此同源码重复构建字节一致。
  **跨 zlib 版本不承诺逐字节相同**（同一 zlib 下可复现）。
* **不联网、不改源码、不自动安装**；输出目录不得位于输入包内部。
* 目标 ZIP 已存在且内容不同 → 拒绝覆盖（``--force`` 才覆盖）；内容相同 → 复用。
* 每包压缩体积必须 ≤ 市场契约的 64 MiB 上限（``MARKET_ARCHIVE_LIMITS``）。

用法：

    python scripts/build_petcore_extensions.py \
        [--repo-root .] [--output dist-extensions] [--packs id,id] \
        [--force] [--strict] [--write-index PATH] [--local-index]

退出码：0 = 全部构建成功；1 = 构建失败（stderr 给原因）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from petcore import __version__ as CORE_VERSION  # noqa: E402
from petcore.contracts.archive import MARKET_ARCHIVE_LIMITS  # noqa: E402
from petcore.mods.manifest import API_VERSION, load_manifest  # noqa: E402

PACKS_SUBDIR = Path("examples") / "petcore-mods"
DEFAULT_OUTPUT_DIR = "dist-extensions"
CANDIDATE_MANIFEST_NAME = "candidate-manifest.json"
CANDIDATE_SCHEMA = 1
STATUS_PENDING = "pending-publication"
GENERATED_BY = "scripts/build_petcore_extensions.py"
CANONICAL_PACK_IDS = (
    "fun.divination",
    "fun.festival",
    "reminder.todo",
    "voice.chime",
)

# 固定元数据：改任何一个都必须当作格式迁移，并同步 verifier 与测试。
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_EXTERNAL_ATTR = 0o644 << 16
ZIP_COMPRESS_LEVEL = 9

RELEASE_REPO = "MerZlin/dsh-pet-indesktop"
RELEASE_TAG = "petcore-extensions-v0.2.0-rc1"
BLOCKED_REASON = "待发布：候选产物尚未公开"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_INCLUDE_ROOT_FILES = frozenset({"mod.json"})
_BLOCKED_ROOT_NAMES = frozenset({"install.json", "mods-state.json"})
_BLOCKED_ROOT_SUFFIXES = frozenset({".log", ".db", ".sqlite", ".sqlite3"})
_PERSONAL_DIRS = frozenset({"data", "feature-data", "logs", "cache", "market"})
_GENERATED_SUFFIXES = frozenset({".pyc", ".pyo"})
_EXCLUDED_KINDS = ("blocked", "generated", "unknown")


class BuildError(RuntimeError):
    """构建期可诊断失败（参数/白名单/覆盖冲突/归档自检）。"""


# --------------------------------------------------------------------------- #
# 白名单
# --------------------------------------------------------------------------- #


def _classify(rel: PurePosixPath) -> tuple[str, str]:
    """把包内相对路径分成 include / blocked / generated / unknown。"""
    parts = rel.parts
    if any(part.startswith(".") for part in parts):
        return "blocked", "hidden file or trust marker"
    if "__pycache__" in parts:
        return "generated", "bytecode cache"
    if rel.suffix.lower() in _GENERATED_SUFFIXES:
        return "generated", "compiled bytecode"
    if len(parts) == 1:
        if rel.name in _INCLUDE_ROOT_FILES:
            return "include", ""
        if rel.name in _BLOCKED_ROOT_NAMES:
            return "blocked", "installer state"
        if rel.suffix.lower() in _BLOCKED_ROOT_SUFFIXES:
            return "blocked", "personal data"
        return "unknown", "not in whitelist"
    if parts[0] in _PERSONAL_DIRS:
        return "blocked", "personal data"
    if parts[0] == "host" and rel.suffix == ".py":
        return "include", ""
    if parts[0] == "resources":
        return "include", ""
    return "unknown", "not in whitelist"


def _relative_posix(base: Path, path: Path) -> str:
    return PurePosixPath(path.relative_to(base).as_posix()).as_posix()


def _collect_entries(
    pack_dir: Path, pack_id: str, *, strict: bool
) -> tuple[list[tuple[str, bytes]], dict[str, list[str]]]:
    """按白名单读取包内容；返回 (条目列表, 各类排除清单)。"""
    resolved_pack = pack_dir.resolve()
    entries: list[tuple[str, bytes]] = []
    excluded: dict[str, list[str]] = {kind: [] for kind in _EXCLUDED_KINDS}

    for dirpath, dirnames, filenames in os.walk(pack_dir, followlinks=False):
        base = Path(dirpath)
        for name in sorted(dirnames):
            candidate = base / name
            if candidate.is_symlink():
                raise BuildError(
                    f"{pack_id}: symlink directory not allowed: "
                    f"{_relative_posix(pack_dir, candidate)}"
                )
        for name in sorted(filenames):
            path = base / name
            rel = PurePosixPath(_relative_posix(pack_dir, path))
            if path.is_symlink():
                raise BuildError(f"{pack_id}: symlink not allowed: {rel.as_posix()}")
            kind, _reason = _classify(rel)
            if kind != "include":
                excluded[kind].append(rel.as_posix())
                continue
            resolved = path.resolve()
            if resolved != resolved_pack and resolved_pack not in resolved.parents:
                raise BuildError(f"{pack_id}: path escapes pack: {rel.as_posix()}")
            try:
                entries.append((rel.as_posix(), path.read_bytes()))
            except OSError as exc:
                raise BuildError(f"{pack_id}: cannot read {rel.as_posix()}: {exc}") from exc

    entries.sort(key=lambda item: item[0])
    for kind in _EXCLUDED_KINDS:
        excluded[kind].sort()

    if strict and excluded["unknown"]:
        raise BuildError(
            f"{pack_id}: {len(excluded['unknown'])} file(s) outside the packaging "
            f"whitelist: {', '.join(excluded['unknown'])}"
        )
    if not entries:
        raise BuildError(f"{pack_id}: nothing to package")
    return entries, excluded


# --------------------------------------------------------------------------- #
# 确定性 ZIP
# --------------------------------------------------------------------------- #


def _write_zip(path: Path, entries: Sequence[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=ZIP_COMPRESS_LEVEL,
    ) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = ZIP_EXTERNAL_ATTR
            info.internal_attr = 0
            zf.writestr(info, payload)


def _member_name_problem(name: str) -> str | None:
    if not name:
        return "empty entry name"
    if "\\" in name:
        return f"entry is not a POSIX path: {name}"
    if name.startswith("/") or name.startswith("~"):
        return f"absolute entry path: {name}"
    if re.match(r"^[A-Za-z]:", name):
        return f"drive-letter entry path: {name}"
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return f"unsafe entry path: {name}"
    return None


def _selfcheck_archive(
    archive: Path, pack_id: str, entries: Sequence[tuple[str, bytes]]
) -> None:
    """写完立刻回读：条目集合与内容必须与来源一致，路径必须安全。"""
    expected = [name for name, _payload in entries]
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if names != expected:
                raise BuildError(
                    f"{pack_id}: archive entries changed after write "
                    f"(got {len(names)}, expected {len(expected)})"
                )
            for name, payload in entries:
                if zf.read(name) != payload:
                    raise BuildError(f"{pack_id}: archive content mismatch: {name}")
    except zipfile.BadZipFile as exc:
        raise BuildError(f"{pack_id}: produced archive is unreadable: {exc}") from exc
    for name in expected:
        problem = _member_name_problem(name)
        if problem is not None:
            raise BuildError(f"{pack_id}: {problem}")


def _install_archive(
    staged: Path, destination: Path, pack_id: str, *, force: bool
) -> tuple[int, str]:
    data = staged.read_bytes()
    size = len(data)
    digest = hashlib.sha256(data).hexdigest()
    if size > MARKET_ARCHIVE_LIMITS.compressed_bytes:
        raise BuildError(
            f"{pack_id}: archive is {size} bytes, over the "
            f"{MARKET_ARCHIVE_LIMITS.compressed_bytes} byte market budget"
        )
    if destination.exists():
        existing = destination.read_bytes()
        if hashlib.sha256(existing).hexdigest() == digest:
            return size, digest
        if not force:
            raise BuildError(
                f"{pack_id}: {destination.name} already exists with different "
                f"content ({len(existing)} bytes); rerun with --force to replace"
            )
    os.replace(staged, destination)
    return size, digest


# --------------------------------------------------------------------------- #
# 单个包
# --------------------------------------------------------------------------- #


def _build_one(
    packs_dir: Path,
    pack_id: str,
    output_dir: Path,
    *,
    force: bool,
    strict: bool,
) -> dict:
    if _ID_RE.match(pack_id) is None:
        raise BuildError(f"invalid pack id: {pack_id!r}")
    pack_dir = packs_dir / pack_id
    if not pack_dir.is_dir():
        raise BuildError(f"pack directory not found: {pack_dir}")
    if output_dir == pack_dir.resolve() or pack_dir.resolve() in output_dir.parents:
        raise BuildError(
            f"{pack_id}: output directory must not live inside the pack: {output_dir}"
        )

    manifest, diagnostics = load_manifest(pack_dir)
    if manifest is None:
        raise BuildError(
            f"{pack_id}: mod.json is not a valid pack manifest: {'; '.join(diagnostics)}"
        )

    entries, excluded = _collect_entries(pack_dir, pack_id, strict=strict)
    archive_name = f"{manifest.id}-{manifest.version}.zip"
    destination = output_dir / archive_name
    staged = destination.with_name(destination.name + ".part")

    try:
        _write_zip(staged, entries)
        _selfcheck_archive(staged, pack_id, entries)
        size, digest = _install_archive(staged, destination, pack_id, force=force)
    finally:
        if staged.exists():
            staged.unlink()

    unknown = excluded["unknown"]
    print(
        f"[build] {manifest.id} {manifest.version} -> {archive_name} "
        f"({len(entries)} files, {size} bytes, sha256 {digest[:12]})"
    )
    print(
        f"[build] {manifest.id} excluded: blocked={len(excluded['blocked'])} "
        f"generated={len(excluded['generated'])} unknown={len(unknown)}"
    )
    if unknown:
        print(
            f"[build] warning: {manifest.id} unknown files not packaged "
            f"({len(unknown)}): {', '.join(unknown)}"
        )

    return {
        "id": manifest.id,
        "version": manifest.version,
        "kind": manifest.kind,
        "file": archive_name,
        "size": size,
        "sha256": digest,
        "files": [name for name, _payload in entries],
        "core_requires": manifest.core_requires,
        "api_version": manifest.api_version,
        "entrypoint": manifest.entrypoint,
        "name": manifest.name,
        "name_zh": manifest.name_zh,
        "author": manifest.author,
        "execution": manifest.execution,
        "capabilities": list(manifest.capabilities),
        "excluded_blocked": excluded["blocked"],
        "excluded_generated": excluded["generated"],
        "excluded_unknown": unknown,
    }


# --------------------------------------------------------------------------- #
# 公共接口
# --------------------------------------------------------------------------- #


def _normalize_packs(packs: Iterable[str] | None) -> list[str]:
    ids = list(CANONICAL_PACK_IDS) if packs is None else list(packs)
    if not ids:
        raise BuildError("no packs requested")
    seen: set[str] = set()
    for pack_id in ids:
        if _ID_RE.match(pack_id) is None:
            raise BuildError(f"invalid pack id: {pack_id!r}")
        if pack_id in seen:
            raise BuildError(f"duplicate pack id: {pack_id!r}")
        seen.add(pack_id)
    return sorted(seen)


def build_candidates(
    repo_root: Path,
    output_dir: Path,
    *,
    packs: Iterable[str] | None = None,
    force: bool = False,
    strict: bool = False,
) -> Path:
    """构建候选 ZIP 与 ``candidate-manifest.json``；返回清单路径。"""
    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    packs_dir = repo_root / PACKS_SUBDIR
    if not packs_dir.is_dir():
        raise BuildError(f"packs directory not found: {packs_dir}")

    pack_ids = _normalize_packs(packs)
    for pack_id in pack_ids:
        pack_dir = (packs_dir / pack_id).resolve()
        if not pack_dir.is_dir():
            raise BuildError(f"pack directory not found: {pack_dir}")
        if output_dir == pack_dir or pack_dir in output_dir.parents:
            raise BuildError(
                f"{pack_id}: output directory must not live inside the pack: "
                f"{output_dir}"
            )
    output_dir.mkdir(parents=True, exist_ok=True)

    records = [
        _build_one(packs_dir, pack_id, output_dir, force=force, strict=strict)
        for pack_id in pack_ids
    ]
    records.sort(key=lambda item: item["id"])

    document = {
        "schema_version": CANDIDATE_SCHEMA,
        "status": STATUS_PENDING,
        "generated_by": GENERATED_BY,
        "core_version": CORE_VERSION,
        "api_version": API_VERSION,
        "artifacts": records,
    }
    manifest_path = output_dir / CANDIDATE_MANIFEST_NAME
    staged = manifest_path.with_name(manifest_path.name + ".part")
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        staged.write_text(text, "utf-8", newline="\n")
        os.replace(staged, manifest_path)
    finally:
        if staged.exists():
            staged.unlink()

    print(f"[build] {len(records)} pack(s) -> {manifest_path}")
    return manifest_path


def release_artifact_url(file_name: str) -> str:
    """候选产物的拟定 Release 地址（不请求、不代表已发布）。"""
    return (
        f"https://github.com/{RELEASE_REPO}/releases/download/"
        f"{RELEASE_TAG}/{file_name}"
    )


def _load_verifier():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib

    return importlib.import_module("verify_petcore_extensions")


def build_index(
    candidate_manifest: Path,
    *,
    local: bool = False,
    state: str = "candidate",
) -> dict:
    """由候选清单生成 schema_version=1 的市场字典。

    ``candidate`` 是默认状态：使用拟定 Release URL，但所有包保持 blocked。
    ``published`` 只在调用方明确确认资产已上传后解除 blocked。
    ``local=True`` 仅用于本机离线验收，使用候选 ZIP 的 ``file://`` 地址。
    先跑独立校验器，清单/ZIP 不一致直接失败。
    """
    state = str(state).strip().lower()
    if state not in {"candidate", "published"}:
        raise BuildError("index state must be candidate or published")
    candidate_manifest = Path(candidate_manifest).resolve()
    problems, _artifacts = _load_verifier().verify_candidate_manifest(candidate_manifest)
    if problems:
        raise BuildError(
            "candidate manifest failed verification: " + "; ".join(problems[:5])
        )
    data = json.loads(candidate_manifest.read_text("utf-8"))

    packages = []
    for item in sorted(data["artifacts"], key=lambda record: record["id"]):
        archive = candidate_manifest.parent / item["file"]
        if local:
            urls = [archive.as_uri()]
        else:
            urls = [release_artifact_url(item["file"])]
        packages.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "name": item.get("name", ""),
                "name_zh": item.get("name_zh", ""),
                "author": item.get("author", ""),
                "latest": item["version"],
                "api_version": item["api_version"],
                "core_requires": item["core_requires"],
                "execution": item.get("execution", "host-only"),
                "capabilities": list(item.get("capabilities", [])),
                "platforms": [],
                "certified": False,
                "blocked": not local and state != "published",
                "blocked_reason": ""
                if local or state == "published"
                else BLOCKED_REASON,
                "screenshots": [],
                "versions": [
                    {
                        "version": item["version"],
                        "size": item["size"],
                        "sha256": item["sha256"],
                        "urls": urls,
                    }
                ],
            }
        )
    return {"schema_version": 1, "packages": packages}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build reproducible petcore extension candidate ZIPs."
    )
    parser.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--output",
        "--out",
        dest="output",
        default=None,
        help=f"output directory (default: <repo-root>/{DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--packs",
        default=None,
        help="comma separated pack ids (default: all four canonical example packs)",
    )
    parser.add_argument("--force", action="store_true", help="replace differing archives")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when a pack contains files outside the packaging whitelist",
    )
    parser.add_argument(
        "--write-index",
        default=None,
        help="also write a market index dict (schema_version 1) to this path",
    )
    parser.add_argument(
        "--local-index",
        action="store_true",
        help="with --write-index: emit file:// candidate URLs instead of release URLs",
    )
    parser.add_argument(
        "--index-state",
        choices=("candidate", "published"),
        default="candidate",
        help="index status; candidate is blocked by default, published requires explicit confirmation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(args.repo_root)
    output_dir = (
        Path(args.output) if args.output else repo_root / DEFAULT_OUTPUT_DIR
    )
    packs = None
    if args.packs:
        packs = [item.strip() for item in args.packs.split(",") if item.strip()]
    try:
        manifest_path = build_candidates(
            repo_root,
            output_dir,
            packs=packs,
            force=args.force,
            strict=args.strict,
        )
        if args.write_index:
            index = build_index(
                manifest_path, local=args.local_index, state=args.index_state
            )
            target = Path(args.write_index)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                "utf-8",
                newline="\n",
            )
            print(f"[build] market index -> {target}")
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
