# -*- coding: utf-8 -*-
"""T05：petcore 候选扩展包的独立校验器。

**独立性是硬要求**：本文件不 import ``scripts/build_petcore_extensions.py``，
也不 import 构建器内部函数；它自己重新解包每个 ZIP、重新计算 size/sha256、
自己解析 ``mod.json`` 并逐字段对照 ``candidate-manifest.json``。构建器有 bug
时（比如少打一个文件、清单抄错摘要、把 ``.trusted`` 打进去）必须由这里抓出来。

校验内容：

1. 清单根字段：格式版本、状态、生成者、Core/API 版本；不含本机绝对路径/URL。
2. 每个 artifact：必需字段齐全、id/version 合法且唯一、四包齐全（``--allow-subset``
   可放宽为只要求非空）。
3. 归档文件存在、大小与 SHA-256 与清单一致（重新读盘计算）。
4. 条目名全是相对 POSIX 路径：无 ``/`` 前缀、无反斜杠、无盘符、无 ``..``/``.``。
5. 成员白名单：只有 ``mod.json``、``host/**/*.py``、``resources/**``；显式拒绝
   ``.trusted``、``__pycache__``、``*.pyc``、隐藏文件。
6. ZIP 内 ``mod.json`` 的 id/version/kind/api_version/core_requires/entrypoint
   与清单逐字段一致，entrypoint 目标确实在包内。
7. ``files[]`` 与实际条目集合完全一致（顺序也一致：升序）。

用法：

    python scripts/verify_petcore_extensions.py \
        --candidate-manifest dist-extensions/candidate-manifest.json [--allow-subset]

退出码：0 = 全部通过；1 = 发现不一致；2 = 用法/清单不可读。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Sequence

CANDIDATE_SCHEMA = 1
STATUS_PENDING = "pending-publication"
GENERATED_BY = "scripts/build_petcore_extensions.py"
REQUIRED_PACK_IDS = (
    "fun.divination",
    "fun.festival",
    "reminder.todo",
    "voice.chime",
)
REQUIRED_KEYS = (
    "id",
    "version",
    "kind",
    "size",
    "sha256",
    "files",
    "core_requires",
    "api_version",
    "entrypoint",
)
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_URL_RE = re.compile(r"^(https?|ftp|file)://", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|\\\\|/|~)")


# --------------------------------------------------------------------------- #
# 纯检查
# --------------------------------------------------------------------------- #


def _entry_name_problem(name: str) -> str | None:
    if not name:
        return "empty entry name"
    if name.endswith("/"):
        return f"directory entry not allowed: {name}"
    if "\\" in name:
        return f"entry is not a POSIX path: {name}"
    if name.startswith("/") or name.startswith("~"):
        return f"absolute entry path: {name}"
    if _ABS_PATH_RE.match(name):
        return f"absolute entry path: {name}"
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return f"unsafe entry path: {name}"
    return None


def _entry_policy_problem(name: str) -> str | None:
    parts = name.split("/")
    if any(part == ".trusted" for part in parts):
        return f"archive must not carry a .trusted marker: {name}"
    if any(part.startswith(".") for part in parts):
        return f"hidden file not allowed in a package: {name}"
    if "__pycache__" in parts:
        return f"bytecode cache not allowed in a package: {name}"
    if name.lower().endswith((".pyc", ".pyo")):
        return f"compiled bytecode not allowed in a package: {name}"
    if name == "mod.json":
        return None
    if parts[0] == "host" and len(parts) > 1 and name.endswith(".py"):
        return None
    if parts[0] == "resources" and len(parts) > 1:
        return None
    return f"member outside the packaging whitelist: {name}"


def _portability_problems(value: Any, trail: str) -> list[str]:
    problems: list[str] = []
    if isinstance(value, str):
        if _ABS_PATH_RE.match(value):
            problems.append(f"{trail}: absolute path is not portable: {value}")
        elif _URL_RE.match(value):
            problems.append(f"{trail}: candidate manifest must not carry URLs: {value}")
    elif isinstance(value, dict):
        for key, item in value.items():
            problems.extend(_portability_problems(item, f"{trail}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(_portability_problems(item, f"{trail}[{index}]"))
    return problems


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# 单个 artifact
# --------------------------------------------------------------------------- #


def _verify_archive(
    record: dict, manifest_dir: Path, problems: list[str]
) -> None:
    pack_id = record.get("id") if isinstance(record.get("id"), str) else "?"

    def fail(message: str) -> None:
        problems.append(f"{pack_id}: {message}")

    for key in REQUIRED_KEYS:
        if key not in record:
            fail(f"candidate manifest is missing '{key}'")
    if any(key not in record for key in REQUIRED_KEYS):
        return

    if not isinstance(pack_id, str) or _ID_RE.match(pack_id) is None:
        fail(f"invalid id: {record.get('id')!r}")
    version = record.get("version")
    if not isinstance(version, str) or _VERSION_RE.match(version) is None:
        fail(f"invalid version: {version!r}")
    if record.get("kind") not in ("feature", "content"):
        fail(f"invalid kind: {record.get('kind')!r}")
    if record.get("api_version") != "1":
        fail(f"unexpected api_version: {record.get('api_version')!r}")
    core_requires = record.get("core_requires")
    if not isinstance(core_requires, str):
        fail("core_requires must be a string")

    file_name = record.get("file")
    if file_name is None:
        fail("candidate manifest is missing 'file'")
        return
    if (
        not isinstance(file_name, str)
        or "/" in file_name
        or "\\" in file_name
        or file_name in ("", ".", "..")
    ):
        fail(f"archive name must be a bare file name: {file_name!r}")
        return

    archive = manifest_dir / file_name
    if not archive.is_file():
        fail(f"archive not found: {file_name}")
        return
    data = archive.read_bytes()
    if len(data) > MAX_ARCHIVE_BYTES:
        fail(f"archive is {len(data)} bytes, over the market budget")

    size = record.get("size")
    if not isinstance(size, int) or isinstance(size, bool):
        fail("size must be an integer")
    elif size != len(data):
        fail(f"size mismatch: manifest={size} actual={len(data)}")

    digest = record.get("sha256")
    actual_digest = _sha256(data)
    if not isinstance(digest, str) or _SHA_RE.match(digest) is None:
        fail(f"sha256 must be 64 lowercase hex characters, got {digest!r}")
    elif digest != actual_digest:
        fail(f"sha256 mismatch: manifest={digest} actual={actual_digest}")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            bad = zf.testzip()
            if bad is not None:
                fail(f"corrupt archive member: {bad}")
                return
            names = zf.namelist()
            payloads = {name: zf.read(name) for name in names}
    except (zipfile.BadZipFile, OSError) as exc:
        fail(f"cannot open archive: {exc}")
        return

    if len(names) != len(set(names)):
        fail("archive contains duplicate entry names")
    for name in names:
        problem = _entry_name_problem(name) or _entry_policy_problem(name)
        if problem is not None:
            fail(problem)

    listed = record.get("files")
    if not isinstance(listed, list) or any(not isinstance(n, str) for n in listed):
        fail("files must be a list of strings")
    else:
        if listed != sorted(listed):
            fail("files must be sorted ascending")
        if listed != names:
            missing = sorted(set(listed) - set(names))
            extra = sorted(set(names) - set(listed))
            fail(
                "files do not match archive members "
                f"(missing={missing[:5]}, extra={extra[:5]})"
            )

    if "mod.json" not in payloads:
        fail("archive has no root mod.json")
        return
    try:
        raw = json.loads(payloads["mod.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"mod.json inside archive is unreadable: {exc}")
        return
    if not isinstance(raw, dict):
        fail("mod.json inside archive must be an object")
        return

    for key in ("id", "version", "kind", "api_version", "core_requires", "entrypoint"):
        if raw.get(key) != record.get(key):
            fail(
                f"{key} mismatch between mod.json and candidate manifest: "
                f"mod.json={raw.get(key)!r} manifest={record.get(key)!r}"
            )

    entrypoint = record.get("entrypoint")
    if isinstance(entrypoint, str) and entrypoint:
        target = entrypoint.split(":", 1)[0].strip()
        if target not in payloads:
            fail(f"entrypoint target is not packaged: {target}")


# --------------------------------------------------------------------------- #
# 清单
# --------------------------------------------------------------------------- #


def verify_candidate_manifest(
    manifest_path: Path, *, require_all: bool = True
) -> tuple[list[str], list[dict]]:
    """校验候选清单与其 ZIP；返回 (problems, artifacts)。problems 为空即通过。"""
    manifest_path = Path(manifest_path)
    problems: list[str] = []
    try:
        text = manifest_path.read_text("utf-8")
    except OSError as exc:
        return [f"cannot read candidate manifest {manifest_path}: {exc}"], []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"candidate manifest is not valid JSON: {exc}"], []
    if not isinstance(data, dict):
        return ["candidate manifest must be a JSON object"], []

    if data.get("schema_version") != CANDIDATE_SCHEMA:
        problems.append(
            f"schema_version must be {CANDIDATE_SCHEMA}, "
            f"got {data.get('schema_version')!r}"
        )
    if data.get("status") != STATUS_PENDING:
        problems.append(
            f"status must be {STATUS_PENDING!r}, got {data.get('status')!r}"
        )
    if data.get("generated_by") != GENERATED_BY:
        problems.append(
            f"generated_by must be {GENERATED_BY!r}, got {data.get('generated_by')!r}"
        )
    if not isinstance(data.get("core_version"), str) or not data.get("core_version"):
        problems.append("core_version must be a non-empty string")
    if data.get("api_version") != "1":
        problems.append(f"api_version must be '1', got {data.get('api_version')!r}")

    problems.extend(_portability_problems(data, "manifest"))

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return [*problems, "artifacts must be a non-empty list"], []

    seen: set[str] = set()
    manifest_dir = manifest_path.parent
    for record in artifacts:
        if not isinstance(record, dict):
            problems.append("artifact entries must be JSON objects")
            continue
        pack_id = record.get("id")
        if isinstance(pack_id, str):
            if pack_id in seen:
                problems.append(f"{pack_id}: duplicate artifact id")
            seen.add(pack_id)
        _verify_archive(record, manifest_dir, problems)

    if require_all:
        missing = [pack_id for pack_id in REQUIRED_PACK_IDS if pack_id not in seen]
        if missing:
            problems.append(f"candidate manifest is missing packs: {', '.join(missing)}")
        unexpected = sorted(seen - set(REQUIRED_PACK_IDS))
        if unexpected:
            problems.append(f"unexpected packs: {', '.join(unexpected)}")

    return problems, [record for record in artifacts if isinstance(record, dict)]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify petcore extension candidate archives and manifest."
    )
    parser.add_argument(
        "--candidate-manifest", required=True, help="path to candidate-manifest.json"
    )
    parser.add_argument(
        "--allow-subset",
        action="store_true",
        help="do not require the four canonical packs to be present",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    manifest_path = Path(args.candidate_manifest)
    if not manifest_path.is_file():
        print(f"error: candidate manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    problems, artifacts = verify_candidate_manifest(
        manifest_path, require_all=not args.allow_subset
    )
    for record in artifacts:
        print(
            f"[verify] {record.get('id')} {record.get('version')} "
            f"({len(record.get('files') or [])} files, {record.get('size')} bytes)"
        )
    if problems:
        for problem in problems:
            print(f"[verify] {problem}", file=sys.stderr)
        print(f"[verify] failed with {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"[verify] verified {len(artifacts)}/{len(artifacts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
