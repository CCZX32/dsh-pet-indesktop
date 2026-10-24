from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterator

from .manifest import MOD_FILE, is_valid_id, load_manifest, path_within

INSTALL_FILE = "install.json"
INSTALL_SCHEMA = 1
_CHUNK = 1024 * 1024


class InstallError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _digest_tree(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        files[path.relative_to(root).as_posix()] = _sha256(path)
    return files


def _chmod_retry(func, target, exc) -> None:
    # Only retry the Windows read-only case. Preserve other errors and never
    # report success when the retry also fails (e.g. a locked installed file).
    if not isinstance(exc, PermissionError):
        raise exc
    os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
    func(target)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    if path.is_dir():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_chmod_retry)
        else:
            shutil.rmtree(path, onerror=lambda fn, name, info: _chmod_retry(fn, name, info[1]))
        if path.exists() or path.is_symlink():
            raise OSError(f"cleanup incomplete: {path}")


def _copy_pack(source: Path, target: Path) -> None:
    root = source.resolve()
    target.mkdir(parents=True)
    visited: set[Path] = {root}
    stack: list[tuple[Path, Path]] = [(root, target)]
    while stack:
        current, out_dir = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise InstallError(f"cannot read {current}: {exc}") from exc
        for entry in entries:
            source_path = Path(entry.path)
            dest_path = out_dir / entry.name
            if entry.is_symlink():
                try:
                    resolved = source_path.resolve()
                except OSError as exc:
                    raise InstallError(f"cannot resolve symlink {entry.name}: {exc}") from exc
                if not path_within(root, resolved):
                    raise InstallError(f"symlink escapes pack: {entry.name}")
                if resolved.is_dir():
                    if resolved in visited:
                        continue
                    visited.add(resolved)
                    dest_path.mkdir(parents=True, exist_ok=True)
                    stack.append((resolved, dest_path))
                elif resolved.is_file():
                    shutil.copy2(resolved, dest_path)
                else:
                    raise InstallError(f"broken symlink: {entry.name}")
            elif entry.is_dir(follow_symlinks=False):
                dest_path.mkdir(parents=True, exist_ok=True)
                stack.append((source_path, dest_path))
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(source_path, dest_path)


def _extract_zip(archive: Path, dest: Path) -> None:
    try:
        handle = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError(f"cannot read archive: {exc}") from exc
    dest_root = dest.resolve()
    with handle:
        for info in handle.infolist():
            name = info.filename
            if not name:
                continue
            windows = PureWindowsPath(name)
            if windows.is_absolute() or windows.drive or name.startswith(("/", "\\")):
                raise InstallError(f"unsafe zip entry: {name}")
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if ".." in parts:
                raise InstallError(f"unsafe zip entry: {name}")
            if info.is_dir():
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise InstallError(f"symlink entry rejected: {name}")
            target = dest.joinpath(*parts)
            try:
                resolved = target.resolve()
            except OSError as exc:
                raise InstallError(f"unsafe zip entry: {name}: {exc}") from exc
            if not path_within(dest_root, resolved):
                raise InstallError(f"unsafe zip entry: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with handle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            except OSError as exc:
                raise InstallError(f"cannot extract {name}: {exc}") from exc


def _archive_root(dest: Path) -> Path:
    if (dest / MOD_FILE).is_file():
        return dest
    try:
        candidates = [
            child for child in dest.iterdir() if child.is_dir() and (child / MOD_FILE).is_file()
        ]
    except OSError as exc:
        raise InstallError(f"cannot inspect archive: {exc}") from exc
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise InstallError(f"{MOD_FILE} not found in archive")
    raise InstallError(f"multiple {MOD_FILE} roots found in archive")


@contextmanager
def _source_pack(source: Path, work_root: Path | None = None) -> Iterator[Path]:
    source = Path(source)
    if source.is_dir():
        yield source
        return
    if not source.is_file():
        raise InstallError(f"source not found: {source}")
    if source.suffix.lower() != ".zip":
        raise InstallError(f"unsupported source: {source} (expected directory or .zip)")
    if work_root is not None:
        work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".unpack-", dir=str(work_root) if work_root is not None else None
    ) as tmp:
        dest = Path(tmp)
        _extract_zip(source, dest)
        yield _archive_root(dest)


def _trash_path(mods_root: Path, mod_id: str) -> Path:
    index = 0
    while True:
        candidate = mods_root / f".trash-{mod_id}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _install_json(manifest_id: str, version: str, files: dict[str, str]) -> str:
    payload = {
        "schema": INSTALL_SCHEMA,
        "id": manifest_id,
        "version": version,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def open_pack(
    source: Path, work_root: Path | None = None
) -> Iterator[Path]:
    """公开的解包入口：目录原样返回，zip 解到临时目录（调用方负责生命周期）。"""
    return _source_pack(Path(source), work_root)


def install(source: Path, root: Path, *, force: bool = False) -> tuple[bool, str]:
    root = Path(root)
    mods_root = root / "mods"
    staging: Path | None = None
    cleanup_note = ""
    try:
        mods_root.mkdir(parents=True, exist_ok=True)
        with _source_pack(Path(source), mods_root) as pack:
            manifest, problems = load_manifest(pack)
            if manifest is None:
                return False, "; ".join(problems) or "invalid manifest"

            target = mods_root / manifest.id
            staging = mods_root / f".staging-{manifest.id}-{os.getpid()}"
            _remove_path(staging)
            _copy_pack(pack, staging)
            files = _digest_tree(staging)
            (staging / INSTALL_FILE).write_text(
                _install_json(manifest.id, manifest.version, files), encoding="utf-8"
            )

            if target.exists() or target.is_symlink():
                if not force:
                    _remove_path(staging)
                    staging = None
                    return False, f"already installed: {target} (use --force to replace)"
                trash = _trash_path(mods_root, manifest.id)
                os.replace(target, trash)
                try:
                    os.replace(staging, target)
                except OSError:
                    os.replace(trash, target)
                    raise
                staging = None
                try:
                    _remove_path(trash)
                except OSError as exc:
                    # Commit already succeeded. Keep the new installation and
                    # name the residual backup rather than invite a failed retry.
                    cleanup_note = f"; cleanup failed for {trash}: {exc}"
            else:
                os.replace(staging, target)
                staging = None

            suffix = f" ({len(problems)} warning(s))" if problems else ""
            return True, f"installed {manifest.id} {manifest.version} -> {target}{suffix}{cleanup_note}"
    except Exception as exc:
        if staging is not None:
            try:
                _remove_path(staging)
            except OSError as cleanup_exc:
                cleanup_note = f"; cleanup failed for {staging}: {cleanup_exc}"
        return False, f"install failed: {exc}{cleanup_note}"


def read_install_files(path: Path) -> dict[str, str] | None:
    """读 ``install.json`` 的逐文件摘要；缺失/损坏返回 None（安装器投放的包没有它）。"""
    try:
        raw = json.loads((Path(path) / INSTALL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict):
        return None
    return {
        str(name): str(digest)
        for name, digest in files.items()
        if isinstance(name, str) and name and not Path(name).is_absolute()
    }


def _is_generated(relative: str) -> bool:
    """运行时生成、卸载时可以一并删除的产物。"""
    parts = PurePosixPath(relative).parts
    return "__pycache__" in parts or relative.endswith(".pyc")


def _remove_listed(target: Path, files: dict[str, str]) -> tuple[int, int]:
    """按清单删除文件，返回 ``(已删除文件数, 未登记文件数)``。"""
    removed = 0
    for relative in sorted(files, key=lambda name: name.count("/"), reverse=True):
        candidate = target / relative
        if not path_within(target, candidate):
            continue
        try:
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    for path in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            try:
                path.rmdir()
            except OSError:
                continue
    known = set(files)
    leftovers = 0
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        if relative == INSTALL_FILE:
            continue
        if _is_generated(relative):
            try:
                path.unlink()
            except OSError:
                leftovers += 1
            continue
        if relative not in known:
            leftovers += 1
    return removed, leftovers


def remove_at(target: Path, *, root: Path | None = None) -> tuple[bool, str]:
    """卸载一个已安装的扩展包。

    * 用户导入的包按其 ``install.json`` 清单逐文件删除，未登记文件保留；
    * 安装器投放的包（无 ``install.json``）整目录删除，但仍做边界与 ``mod.json`` 校验；
    * 个人数据（``feature-data/<id>``、配置键、钥匙串）一律不动。
    """
    from . import state as mod_state

    target = Path(target)
    mod_id = target.name
    if not is_valid_id(mod_id):
        return False, f"invalid mod id: {mod_id!r}"
    mods_root = target.parent
    if not target.is_dir():
        return False, f"mod not installed: {target}"
    try:
        resolved_root = mods_root.resolve()
        resolved = target.resolve()
    except OSError as exc:
        return False, f"cannot resolve {target}: {exc}"
    if resolved.parent != resolved_root:
        return False, f"refusing to remove outside mods directory: {target}"
    if not (target / MOD_FILE).is_file():
        return False, f"not a mod pack: {target}"

    files = read_install_files(target)
    try:
        if files is None:
            _remove_path(target)
            leftovers = 0
        else:
            _removed, leftovers = _remove_listed(target, files)
            try:
                (target / INSTALL_FILE).unlink()
            except FileNotFoundError:
                pass
            try:
                target.rmdir()
            except OSError:
                pass
        if leftovers:
            message = f"removed {mod_id} ({leftovers} unrecognised file(s) kept in {target})"
        elif target.exists():
            message = f"removed {mod_id} (some files are still in use: {target})"
        else:
            message = f"removed {mod_id}"
    except OSError as exc:
        return False, f"remove failed: {exc}"

    state_root = Path(root) if root is not None else mods_root.parent
    try:
        mod_state.clear(state_root, mod_id)
    except OSError:
        pass
    return True, message


def remove(root: Path, mod_id: str) -> tuple[bool, str]:
    if not isinstance(mod_id, str) or not is_valid_id(mod_id):
        return False, f"invalid mod id: {mod_id!r}"
    mods_root = Path(root) / "mods"
    if not mods_root.is_dir():
        return False, f"no mods directory: {mods_root}"
    return remove_at(mods_root / mod_id, root=Path(root))


def validate(source: Path) -> list[str]:
    try:
        with _source_pack(Path(source)) as pack:
            _, problems = load_manifest(pack)
            return list(problems)
    except Exception as exc:
        return [str(exc) or type(exc).__name__]
