"""Small local MOD catalog adapters; package services remain the state owners.

Ported from the DLC branch `pet/mod_management.py`. The DLC version drove
`pet.content.ContentManager` — a ``content/characters/<id>/versions/<version>``
layout with ``active.json`` / ``previous.json`` pointers. This topology has no
``content/`` tree: a character package is the directory :mod:`pet.catalog`
resolves, i.e. ``<root>/<character_id>/`` holding ``videos/`` and an optional
``manifest.json``. The storage adapter below is written against those roots,
while the policy layer — in-use refusal, boundary checks, outcome wording —
stays the same.

Managed copies live under the data root:

``characters/<id>/``
    The live copy, i.e. the one :func:`pet.catalog.external_character_dirs`
    already scans when the data root is the application data directory.
``mod-disabled/<id>/``
    A stopped copy, deliberately outside every scanned root so "停用" means
    what it says without a second runtime gate.
``mod-versions/<id>/<version>/``
    Copies retained for :meth:`ResourceMods.rollback`.

Only managed copies are mutable; ``prepare_removal`` must release live readers
first. Without it, destructive resource operations are refused rather than
guessing that no pet uses the package.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from uuid import uuid4

from . import catalog as pet_catalog
from .feature_state_io import StateError, safe_path

_LOG = logging.getLogger(__name__)

KIND_RESOURCE = "角色资源"

LIVE_DIRNAME = "characters"
DISABLED_DIRNAME = "mod-disabled"
RETAINED_DIRNAME = "mod-versions"
STAGING_DIRNAME = "mod-staging"

MANIFEST_FILENAME = "manifest.json"

_UNSAFE_ID_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
_DEVICE_ID = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.[^.]*)?\Z", re.IGNORECASE)
_VERSION_RE = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z")
_DEFAULT_VERSION = "0.0.0"
_MAX_ID_CHARS = 128
_MAX_NAME_CHARS = 256
_MAX_DESCRIPTION_CHARS = 4096
_VIDEO_SUFFIXES = frozenset({".webm", ".gif"})
_EXECUTABLE_SUFFIXES = frozenset(
    {".py", ".pyw", ".pyc", ".pyd", ".dll", ".so", ".dylib", ".exe", ".bat", ".cmd", ".com", ".ps1", ".sh", ".js", ".vbs"}
)


def _is_safe_id(value: str) -> bool:
    """A character id becomes one directory name under a root we own.

    Deliberately permissive about non-ASCII: characters placed by hand already
    use folder names that :func:`pet.catalog.list_available_characters` accepts,
    and refusing them here would hide them from the MOD center.
    """
    if not value or len(value) > _MAX_ID_CHARS or value in {".", ".."}:
        return False
    if value != value.strip() or value.endswith("."):
        return False
    return not _UNSAFE_ID_CHARS.search(value) and not _DEVICE_ID.fullmatch(value)


class ModError(RuntimeError):
    """A resource MOD operation was refused; the message is user-facing."""


@dataclass(frozen=True)
class ModEntry:
    id: str
    kind: str
    name: str
    version: str
    description: str
    enabled: bool
    path: Path
    source: str = "installed"
    character_id: str = ""
    pending: str = ""

    @property
    def managed(self) -> bool:
        return self.source == "installed"

    @property
    def key(self) -> str:
        return self.kind + ":" + self.id


@dataclass(frozen=True)
class ModOutcome:
    success: bool
    message: str
    pending: bool = False


class ModSelection:
    """A changed visible scope invalidates selection, never hidden deletion."""
    def __init__(self):
        self.visible: set[str] = set()
        self.selected: set[str] = set()

    def set_visible(self, entries: Iterable[ModEntry]) -> None:
        self.visible = {entry.id for entry in entries}
        self.selected.clear()

    def select_all(self) -> None:
        self.selected = set(self.visible)


@dataclass(frozen=True)
class _CharacterPackage:
    character_id: str
    root: Path
    version: str
    display_name: str
    description: str


def _manifest_of(root: Path) -> dict:
    path = root / MANIFEST_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModError(f"角色包的 manifest.json 无法解析：{exc}") from None
    if not isinstance(data, dict):
        raise ModError("角色包的 manifest.json 必须是一个对象")
    return data


def _text_field(manifest: dict, key: str, limit: int) -> str:
    # Clamped rather than refused: the same reader also serves packages a user
    # placed by hand, and a long comment must not make one disappear from the list.
    value = manifest.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


def _video_files(root: Path) -> list[Path]:
    videos = root / "videos"
    if not videos.is_dir():
        return []
    return [path for path in videos.rglob("*") if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES]


def _read_package(root: Path, *, character_id: str | None = None,
                  deep: bool = True) -> _CharacterPackage:
    """Validate one character package directory, or refuse it with a reason.

    ``deep=False`` 是列表浅读：符号链接/可执行文件扫描只看顶层与 ``videos/`` 子树，
    不递归整包——``frameseq/`` 里可能有数万个帧文件（本机 25530 个），全树 rglob
    实测要 4.5–5.4 秒，会让设置窗打开慢十倍。安装/启用/回滚仍走 deep=True 的全量校验。
    """
    if not root.is_dir():
        raise ModError("无效的角色资源包：不是目录")
    if deep:
        scan = list(root.rglob("*"))
    else:
        scan = list(root.iterdir())
        videos_dir = root / "videos"
        if videos_dir.is_dir():
            scan.extend(videos_dir.rglob("*"))
    for path in scan:
        if path.is_symlink():
            raise ModError(f"角色包内不允许符号链接：{path.name}")
        if path.is_file() and path.suffix.lower() in _EXECUTABLE_SUFFIXES:
            raise ModError(f"角色包内不允许可执行文件：{path.name}")
    manifest = _manifest_of(root)
    resolved_id = character_id or _text_field(manifest, "id", _MAX_ID_CHARS) or root.name
    if not _is_safe_id(resolved_id):
        raise ModError("角色包标识含不支持的字符")
    videos = _video_files(root)
    if not videos:
        raise ModError("角色包缺少 videos 素材")
    if any(path.stat().st_size == 0 for path in videos):
        raise ModError("角色包内含空的素材文件")
    version = _text_field(manifest, "version", 64)
    if not _VERSION_RE.fullmatch(version):
        version = _DEFAULT_VERSION
    return _CharacterPackage(
        character_id=resolved_id,
        root=root,
        version=version,
        display_name=_text_field(manifest, "name", _MAX_NAME_CHARS) or resolved_id,
        description=_text_field(manifest, "description", _MAX_DESCRIPTION_CHARS),
    )


def _version_key(version: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = version.split(".")
        return int(major), int(minor), int(patch)
    except ValueError:
        return 0, 0, 0


def _contains(parent: Path, child: Path) -> bool:
    try:
        return child.is_relative_to(parent)
    except (OSError, ValueError):
        return False


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            raise ModError(f"角色包内不允许符号链接：{relative.as_posix()}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _extract_zip(source: Path, destination: Path) -> Path:
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or re.match(r"^[A-Za-z]:", name):
                raise ModError(f"压缩包内含越界路径：{info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ModError(f"压缩包内不允许符号链接：{info.filename}")
            if info.is_dir():
                continue
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source_handle, target.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
    return _package_root_within(destination)


def _package_root_within(directory: Path) -> Path:
    if (directory / "videos").is_dir() or (directory / MANIFEST_FILENAME).is_file():
        return directory
    children = [path for path in directory.iterdir() if path.is_dir()]
    if len(children) == 1:
        return children[0]
    return directory


class ResourceMods:
    """Only managed copies are mutable; callback must release live readers first.

    The application supplies cross-process preparation. Without it, destructive
    resource operations are refused rather than guessing that no pet uses it.
    """
    def __init__(
        self,
        data_root: Path,
        *,
        prepare_removal: Callable[[ModEntry], bool] | None = None,
        character_roots: Iterable[tuple[str, Path]] | None = None,
    ):
        self.data_root = Path(data_root).absolute()
        self.live_root = self.data_root / LIVE_DIRNAME
        self.disabled_root = self.data_root / DISABLED_DIRNAME
        self.retained_root = self.data_root / RETAINED_DIRNAME
        self.staging_root = self.data_root / STAGING_DIRNAME
        self.character_roots = self._roots(character_roots)
        self.prepare_removal = prepare_removal or (lambda _entry: False)

    def _roots(self, character_roots: Iterable[tuple[str, Path]] | None) -> list[tuple[str, Path]]:
        if character_roots is None:
            candidates: list[tuple[str, Path]] = [("builtin", pet_catalog.characters_dir())]
            candidates.extend(("external", Path(path)) for path in pet_catalog.external_character_dirs())
        else:
            candidates = [(source, Path(path)) for source, path in character_roots]
        # The managed root is scanned as a separate, mutable source: an override
        # must never be offered as an unmanaged copy of itself.
        managed = os.path.normcase(str(self.live_root))
        return [item for item in candidates if os.path.normcase(str(item[1])) != managed]

    # ------------------------------------------------------------- listing

    def entries(self, *, include_unmanaged: bool = True) -> list[ModEntry]:
        rows = self._managed_rows()
        if include_unmanaged:
            rows.extend(self._unmanaged_rows({row.id for row in rows}))
        return rows

    def _managed_rows(self) -> list[ModEntry]:
        rows: list[ModEntry] = []
        for enabled, root in ((True, self.live_root), (False, self.disabled_root)):
            if not root.is_dir():
                continue
            for character in sorted(root.iterdir()):
                try:
                    safe_path(character)
                except (OSError, ValueError, StateError):
                    continue
                if not character.is_dir():
                    continue
                try:
                    package = _read_package(character, character_id=character.name,
                                            deep=False)
                except (ModError, OSError) as exc:
                    _LOG.warning("MOD discovery skipped %s: %s", character, exc)
                    continue
                rows.append(
                    ModEntry(
                        package.character_id,
                        KIND_RESOURCE,
                        package.display_name,
                        package.version,
                        package.description,
                        enabled,
                        character,
                        source="installed",
                        character_id=package.character_id,
                    )
                )
        rows.sort(key=lambda row: row.id)
        return rows

    def _unmanaged_rows(self, managed_ids: set[str]) -> list[ModEntry]:
        rows: list[ModEntry] = []
        seen = set(managed_ids)
        for source, root in self.character_roots:
            if not root.is_dir():
                continue
            try:
                safe_path(root)
            except (OSError, ValueError, StateError):
                continue
            for character in sorted(root.iterdir()):
                if character.name in seen:
                    continue
                try:
                    safe_path(character)
                except (OSError, ValueError, StateError):
                    continue
                if not character.is_dir() or not _video_files(character):
                    continue
                try:
                    package = _read_package(character, character_id=character.name,
                                            deep=False)
                except (ModError, OSError) as exc:
                    _LOG.warning("MOD discovery skipped %s: %s", character, exc)
                    continue
                seen.add(package.character_id)
                rows.append(
                    ModEntry(
                        "resource:" + source + ":" + package.character_id,
                        KIND_RESOURCE,
                        package.display_name,
                        package.version,
                        package.description,
                        True,
                        character,
                        source=source,
                        character_id=package.character_id,
                    )
                )
        rows.sort(key=lambda row: row.id)
        return rows

    def _entry(self, package_id: str) -> ModEntry:
        entry = next((row for row in self.entries(include_unmanaged=False) if row.id == package_id), None)
        if entry is None:
            raise ModError("未找到已安装的角色包")
        return entry

    # --------------------------------------------------------- installation

    def install(self, source: Path, *, expected_id: str | None = None) -> ModEntry:
        root, temporary = self._materialize(Path(source))
        try:
            package = _read_package(root)
            owner = package.character_id
            if expected_id is not None and owner != expected_id:
                raise ModError("更新文件不是同一个角色包")
            old = next((row for row in self._managed_rows() if row.id == owner), None)
            if old is not None and old.version != package.version and not self.prepare_removal(old):
                raise ModError("角色仍在使用：请先自然退出使用该素材的桌宠后再更新")
            self._publish(package, root, old)
            return self._entry(owner)
        finally:
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)

    def _materialize(self, source: Path) -> tuple[Path, Path | None]:
        if source.is_dir():
            return source, None
        if source.is_file() and zipfile.is_zipfile(source):
            self.staging_root.mkdir(parents=True, exist_ok=True)
            destination = self.staging_root / uuid4().hex
            destination.mkdir()
            try:
                return _extract_zip(source, destination), destination
            except (OSError, ValueError, zipfile.BadZipFile, ModError) as exc:
                shutil.rmtree(destination, ignore_errors=True)
                raise ModError(f"导入失败：请选择完整的 MOD ZIP 或包目录。（{exc}）") from None
        raise ModError("导入失败：请选择完整的 MOD ZIP 或包目录")

    def _publish(self, package: _CharacterPackage, root: Path, old: ModEntry | None) -> None:
        target_root = self.live_root if old is not None and old.enabled else self.disabled_root
        target = target_root / package.character_id
        if not _contains(self.data_root, target):
            raise ModError("安装边界无效")
        work = self.staging_root / uuid4().hex
        staged = work / package.character_id
        self.staging_root.mkdir(parents=True, exist_ok=True)
        retained: Path | None = None
        try:
            _copy_tree(root, staged)
            if old is not None:
                # The target must be free before the rename below, otherwise an
                # interrupted publish could leave a half tree behind.
                if old.version != package.version:
                    retained = self.retained_root / package.character_id / old.version
                    retained.parent.mkdir(parents=True, exist_ok=True)
                    if retained.exists():
                        shutil.rmtree(retained)
                    os.replace(old.path, retained)
                else:
                    shutil.rmtree(old.path)
            target_root.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staged, target)
            except OSError:
                if retained is not None and retained.exists() and not old.path.exists():
                    old.path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(retained, old.path)
                raise
        except (OSError, ModError, StateError, ValueError) as exc:
            _LOG.warning("MOD install failed for %s: %s", package.character_id, exc)
            raise ModError("导入未完成：请检查文件占用或目录内容后重试") from None
        finally:
            shutil.rmtree(work, ignore_errors=True)
            try:
                self.staging_root.rmdir()
            except OSError:
                pass

    # --------------------------------------------------------------- state

    def set_enabled(self, package_id: str, enabled: bool) -> ModOutcome:
        entry = self._entry(package_id)
        if entry.enabled == enabled:
            return ModOutcome(True, "已启用" if enabled else "已停用")
        if not enabled and not self.prepare_removal(entry):
            return ModOutcome(False, "无法释放正在使用的角色；请先自然退出相关桌宠", True)
        try:
            self._relocate(entry, enabled)
        except (OSError, ValueError, ModError, StateError):
            return ModOutcome(False, "角色状态保存失败；文件未删除，请检查目录占用")
        return ModOutcome(True, "已启用，可点击“使用”换装" if enabled else "已停用")

    def _relocate(self, entry: ModEntry, enabled: bool) -> None:
        target_root = self.live_root if enabled else self.disabled_root
        target = target_root / entry.character_id
        if not _contains(self.data_root, target):
            raise ModError("状态边界无效")
        if target.exists():
            raise ModError("目标位置已存在同名角色包")
        safe_path(entry.path)
        target_root.mkdir(parents=True, exist_ok=True)
        os.replace(entry.path, target)

    # ------------------------------------------------------------- removal

    def remove(self, package_id: str) -> ModOutcome:
        entry = self._entry(package_id)
        if not self.prepare_removal(entry):
            return ModOutcome(False, "无法释放正在使用的角色；请先自然退出相关桌宠", True)
        try:
            # All boundaries are checked before changing state or deleting files.
            targets = self._removal_targets(entry)
            for target in targets:
                safe_path(target)
            for target in targets:
                shutil.rmtree(target)
            self._prune_empty_roots()
        except (OSError, ValueError, ModError, StateError):
            return ModOutcome(False, "删除未完成：请检查文件占用或目录内容；未删除部分已保留")
        return ModOutcome(True, "已删除安装副本；原始文件与个人数据保留")

    def _prune_empty_roots(self) -> None:
        for root in (self.live_root, self.disabled_root, self.retained_root):
            try:
                root.rmdir()
            except OSError:
                pass

    def _removal_targets(self, entry: ModEntry) -> list[Path]:
        targets: list[Path] = []
        for root in (self.live_root, self.disabled_root):
            candidate = root / entry.character_id
            if not _contains(self.data_root, candidate):
                raise ModError("删除边界无效")
            if candidate.exists():
                targets.append(candidate)
        retained_parent = self.retained_root / entry.character_id
        if not _contains(self.data_root, retained_parent):
            raise ModError("删除边界无效")
        if retained_parent.exists():
            for version_dir in sorted(retained_parent.iterdir()):
                if not version_dir.is_dir():
                    raise ModError("角色目录含未识别版本，保留文件")
                package = _read_package(version_dir)
                if package.version != version_dir.name:
                    raise ModError("角色目录含未识别版本，保留文件")
            targets.append(retained_parent)
        return targets

    # ------------------------------------------------------------ rollback

    def rollback(self, package_id: str) -> ModOutcome:
        entry = self._entry(package_id)
        if not self.prepare_removal(entry):
            return ModOutcome(False, "请自然退出使用该角色的桌宠后重试", True)
        previous = self._retained_versions(entry.character_id)
        if not previous:
            return ModOutcome(False, "没有可回滚版本，或文件仍被占用")
        _, target = previous[0]
        try:
            self._swap_in(entry, target)
        except (OSError, ValueError, ModError, StateError):
            return ModOutcome(False, "没有可回滚版本，或文件仍被占用")
        return ModOutcome(True, "已恢复上一版")

    def _retained_versions(self, character_id: str) -> list[tuple[str, Path]]:
        parent = self.retained_root / character_id
        if not parent.is_dir():
            return []
        found: list[tuple[str, Path]] = []
        for version_dir in parent.iterdir():
            if not version_dir.is_dir():
                continue
            try:
                package = _read_package(version_dir)
            except (ModError, OSError):
                continue
            if package.version == version_dir.name:
                found.append((package.version, version_dir))
        found.sort(key=lambda item: _version_key(item[0]), reverse=True)
        return found

    def _swap_in(self, entry: ModEntry, target: Path) -> None:
        target_root = self.live_root if entry.enabled else self.disabled_root
        resolved = target_root / entry.character_id
        if not _contains(self.data_root, resolved):
            raise ModError("回滚边界无效")
        stash = self.retained_root / entry.character_id / entry.version
        stash.parent.mkdir(parents=True, exist_ok=True)
        if stash.exists():
            shutil.rmtree(stash)
        safe_path(entry.path)
        os.replace(entry.path, stash)
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            os.replace(target, resolved)
        except OSError:
            os.replace(stash, entry.path)
            raise
