# -*- coding: utf-8 -*-
"""资源包的逻辑内容哈希与安全相对路径。零 Qt。

与上游 DLC 分支 ``pet/content/hashing.py`` 同一套语义，按本仓库的资源包布局落地：

* **逻辑哈希**不只哈希文件内容，还把**相对路径**（UTF-8，8 字节长度前缀）混进摘要，
  因此"同一个目录"与"由它打成的 ZIP"得到同一个 digest；
* ``manifest.json`` 不参与摘要——它是清单本身，清单里再声明自己的哈希会形成自指；
* 目录遍历稳定排序、拒绝符号链接；ZIP 侧拒绝重复条目、符号链接与越界路径。

这份 digest 只回答"内容有没有变"，**不是**发布者签名：本仓库的信任口径仍是
「清单完整性 + 摘要校验 + 装前子进程预检」（见 ``docs/modding/PORT-STATUS.md`` §一）。
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

MANIFEST_FILENAME = "manifest.json"


def safe_relative_path(value: str) -> PurePosixPath:
    """返回安全的 POSIX 相对路径，拒绝绝对路径、盘符与路径穿越。"""
    raw = str(value).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"unsafe relative path: {value!r}")
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"unsafe relative path: {value!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe relative path: {value!r}")
    if len(path.parts) == 1 and ":" in path.parts[0]:
        raise ValueError(f"unsafe relative path: {value!r}")
    return path


def iter_directory_files(root: Path) -> Iterator[tuple[PurePosixPath, Path]]:
    """按相对路径稳定排序遍历目录；遇到符号链接立即拒绝。"""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed: {path}")
        if path.is_file():
            yield safe_relative_path(path.relative_to(root).as_posix()), path


def _update_hash(digest: Any, rel: PurePosixPath, read_chunks) -> None:
    if rel.as_posix() == MANIFEST_FILENAME:
        return
    encoded = rel.as_posix().encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    for chunk in read_chunks():
        digest.update(chunk)


def _read_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def sha256_directory(root: Path) -> str:
    """目录的逻辑 SHA-256（跳过 ``manifest.json``）。"""
    digest = hashlib.sha256()
    for rel, path in iter_directory_files(root):
        _update_hash(digest, rel, lambda candidate=path: _read_file_chunks(candidate))
    return digest.hexdigest()


def validate_zip_members(archive: zipfile.ZipFile) -> list[PurePosixPath]:
    """校验 ZIP 成员路径；返回排序后的成员表。"""
    members: list[PurePosixPath] = []
    seen: set[str] = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        rel = safe_relative_path(info.filename)
        key = rel.as_posix()
        if key in seen:
            raise ValueError(f"duplicate ZIP member: {key}")
        seen.add(key)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"symlink is not allowed: {key}")
        members.append(rel)
    return sorted(members, key=lambda item: item.as_posix())


def _zip_file_chunks(archive: zipfile.ZipFile, name: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with archive.open(name, "r") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def sha256_zip(path: Path) -> str:
    """ZIP 的逻辑 SHA-256；与同一内容目录的 digest 相同。"""
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        for rel in validate_zip_members(archive):
            _update_hash(digest, rel, lambda name=rel.as_posix(): _zip_file_chunks(archive, name))
    return digest.hexdigest()


def content_sha256(path: Path) -> str:
    """目录或 ZIP 的逻辑内容摘要；其他来源一律拒绝。"""
    path = Path(path)
    if path.is_dir():
        return sha256_directory(path)
    if path.is_file() and zipfile.is_zipfile(path):
        return sha256_zip(path)
    raise ValueError(f"unsupported content source: {path}")


__all__ = [
    "MANIFEST_FILENAME",
    "content_sha256",
    "iter_directory_files",
    "safe_relative_path",
    "sha256_directory",
    "sha256_zip",
    "validate_zip_members",
]
