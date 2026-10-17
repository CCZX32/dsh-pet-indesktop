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

from . import __version__
from . import catalog as pet_catalog
from . import mod_manifest
from .feature_state_io import StateError, safe_path
from .mod_manifest import ManifestIssue, is_safe_package_id
from .mod_transactions import JournalError, ModJournal, TRANSACTIONS_DIRNAME

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
    and refusing them here would hide them from the MOD center. The rule itself
    lives in :mod:`pet.mod_manifest` so the strict import gate and the legacy
    listing path cannot drift apart.
    """
    return is_safe_package_id(value)


class ModError(RuntimeError):
    """A resource MOD operation was refused; the message is user-facing."""

    def __init__(self, message: str, *, issues: Iterable[ManifestIssue] = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)


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
    digest: str = ""

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
    diagnostic: tuple[ManifestIssue, ...] = ()


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
    digest: str = ""


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


def _issue_message(issues: Iterable[ManifestIssue]) -> str:
    messages = [issue.message for issue in issues]
    return "；".join(messages) if messages else "角色资源包不符合清单契约"


def _read_package(root: Path, *, character_id: str | None = None,
                  deep: bool = True, strict: bool = False) -> _CharacterPackage:
    """Validate one character package directory, or refuse it with a reason.

    ``deep=False`` 是列表浅读：符号链接/可执行文件扫描只看顶层与 ``videos/`` 子树，
    不递归整包——``frameseq/`` 里可能有数万个帧文件（本机 25530 个），全树 rglob
    实测要 4.5–5.4 秒，会让设置窗打开慢十倍。安装/启用/回滚仍走 deep=True 的全量校验。

    ``strict=True`` 只给**导入/托管包**用：清单必须满足
    :func:`pet.mod_manifest.validate_resource_package` 的完整契约，版本不合法会被
    拒绝而不是回落 ``0.0.0``。手工放进角色根、没有清单的目录继续走宽松路径。
    """
    if not root.is_dir():
        raise ModError("无效的角色资源包：不是目录")
    if strict:
        manifest_obj, issues, digest = mod_manifest.validate_resource_package(
            root,
            core_version=__version__,
            platform_name=mod_manifest.current_platform(),
        )
        if manifest_obj is None or issues:
            raise ModError(_issue_message(issues), issues=issues)
        if len(manifest_obj.characters) != 1:
            raise ModError(
                "一个角色资源包只能声明一个角色",
                issues=(ManifestIssue("characters_count", "一个角色资源包只能声明一个角色"),),
            )
        declared_id = manifest_obj.characters[0]
        resolved_id = character_id or declared_id
        if resolved_id != declared_id:
            raise ModError(
                "角色包目录与清单声明的角色不一致",
                issues=(ManifestIssue("character_id_mismatch", "角色包 id 与清单声明不一致"),),
            )
        videos = _video_files(root)
        return _CharacterPackage(
            character_id=resolved_id,
            root=root,
            version=manifest_obj.version,
            display_name=manifest_obj.name,
            description=manifest_obj.description,
            digest=digest or "",
        )
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
        self.journal = ModJournal(self.staging_root)
        #: 恢复不了的日志不会被猜着处理；破坏性操作据此 fail-closed。
        self.recovery_diagnostics: list[str] = []
        self.recover_pending_operations()

    # ------------------------------------------------------------ recovery

    def recover_pending_operations(self) -> None:
        """把上次进程留下的目录搬移日志收敛到一致状态。

        规则（与 :mod:`pet.mod_transactions` 的阶段一一对应）：

        * ``prepared``：还没搬任何东西；删掉本次的 incoming，保留目标。
        * ``version_removed``：旧版已进保留区、目标缺位；把保留版搬回目标。
        * ``swapped``：新版已落位；自检通过则补提交，失败则换回保留版。
        * ``committed``：只清日志。
        * ``remove/prepared``：还没删；清日志。``remove/deleted``：把仍存在的目标再删一次。

        任何路径越界、两边都在/都不在、内容校验失败都**不猜**：保留日志、写入
        ``recovery_diagnostics``，并在下一次破坏性操作前如实拒绝。
        """
        self.recovery_diagnostics = []
        try:
            records = self.journal.records()
        except (JournalError, OSError, StateError) as exc:
            self.recovery_diagnostics.append(str(exc))
            return
        for record in records:
            try:
                self._recover_record(record)
            except (OSError, ValueError, StateError, ModError, JournalError) as exc:
                self.recovery_diagnostics.append(f"{record.operation_id}: {exc}")
        if not self.recovery_diagnostics:
            self._prune_staging_root()

    def _prune_staging_root(self) -> None:
        """Remove the empty journal/staging roots so a clean install leaves no debris."""
        for path in (self.staging_root / TRANSACTIONS_DIRNAME, self.staging_root):
            try:
                path.rmdir()
            except OSError:
                pass

    def _recover_record(self, record) -> None:
        if record.kind == "remove":
            self._recover_remove(record)
            return
        target = self._bounded_path(record.target)
        retained = None if record.retained is None else self._bounded_path(record.retained)
        incoming = None if record.incoming is None else self._bounded_path(record.incoming)
        if record.phase == "prepared":
            if incoming is not None and incoming.exists():
                shutil.rmtree(incoming, ignore_errors=True)
            if target.exists():
                self.journal.finish(record)
                return
            if retained is not None and retained.exists():
                self._restore(retained, target)
                self.journal.finish(record)
                return
            raise ModError("事务准备阶段的目标与保留版本都不在，无法判定")
        if record.phase == "version_removed":
            if target.exists():
                # New content already landed but the phase update was lost; the
                # swapped branch below re-checks it rather than trusting it.
                pass
            elif retained is not None and retained.exists():
                self._restore(retained, target)
                self.journal.finish(record)
                return
            else:
                raise ModError("旧版已移走但目标与保留版本都不在")
            record = self.journal.advance(record, "swapped")
        if record.phase in {"swapped", "committed"}:
            if record.phase == "swapped" and target.exists():
                try:
                    _read_package(target, character_id=record.character_id, strict=True)
                except (ModError, OSError):
                    if retained is not None and retained.exists():
                        shutil.rmtree(target, ignore_errors=True)
                        self._restore(retained, target)
                        self.journal.finish(record)
                        return
                    raise
            self.journal.finish(record)

    def _recover_remove(self, record) -> None:
        targets = [self._bounded_path(item) for item in record.targets]
        if record.phase == "prepared":
            # Deletion had not started (or was not recorded): leave the files.
            self.journal.finish(record)
            return
        for target in targets:
            if target.exists():
                shutil.rmtree(target)
        self.journal.finish(record)

    def _bounded_path(self, value: str) -> Path:
        path = Path(value)
        if not _contains(self.data_root, path):
            raise ModError("事务日志含越界路径")
        safe_path(path)
        return path

    def _restore(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)

    def _ensure_no_unresolved_operations(self) -> None:
        self.recover_pending_operations()
        if self.recovery_diagnostics:
            raise ModError(
                "上一次安装/删除没有收尾，需要先处理：" + "；".join(self.recovery_diagnostics[:3])
            )

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
        self._ensure_no_unresolved_operations()
        root, temporary = self._materialize(Path(source))
        try:
            package = _read_package(root, strict=True)
            owner = package.character_id
            if expected_id is not None and owner != expected_id:
                raise ModError("更新文件不是同一个角色包")
            old = next((row for row in self._managed_rows() if row.id == owner), None)
            if old is not None and old.version == package.version:
                # Same version is an idempotent re-import only when the bytes are
                # the same; silently replacing it would change package identity
                # behind the retained-version bookkeeping.
                existing = _read_package(old.path, character_id=owner, strict=True)
                if existing.digest and package.digest and existing.digest != package.digest:
                    raise ModError(
                        "同版本但内容不同：请提高版本号后再导入",
                        issues=(ManifestIssue("same_version_different_content", "同版本内容不同"),),
                    )
                return self._entry(owner)
            if old is not None and not self.prepare_removal(old):
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
        record = None
        try:
            _copy_tree(root, staged)
            if old is not None and old.version != package.version:
                retained = self.retained_root / package.character_id / old.version
                if not _contains(self.data_root, retained):
                    raise ModError("保留版本边界无效")
                retained.parent.mkdir(parents=True, exist_ok=True)
            record = self.journal.begin(
                kind="install",
                character_id=package.character_id,
                target=target,
                retained=retained,
                incoming=staged,
                from_version="" if old is None else old.version,
                to_version=package.version,
            )
            if old is not None:
                # The target must be free before the rename below, otherwise an
                # interrupted publish could leave a half tree behind.
                if old.version != package.version:
                    if retained is not None and retained.exists():
                        shutil.rmtree(retained)
                    os.replace(old.path, retained)
                else:
                    shutil.rmtree(old.path)
                record = self.journal.advance(record, "version_removed")
            target_root.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            record = self.journal.advance(record, "swapped")
            self._self_check(target, package.character_id, expected_digest=package.digest)
            record = self.journal.advance(record, "committed")
            self.journal.finish(record)
        except (OSError, ModError, StateError, ValueError) as exc:
            _LOG.warning("MOD install failed for %s: %s", package.character_id, exc)
            self._recover_after_failed_publish(record, target, retained, old)
            issues = getattr(exc, "issues", ())
            raise ModError(
                "导入未完成：请检查文件占用或目录内容后重试",
                issues=issues,
            ) from None
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._prune_staging_root()

    def _recover_after_failed_publish(self, record, target: Path, retained: Path | None, old: ModEntry | None) -> None:
        """Best-effort local rollback; leave an unprovable state to the journal."""
        try:
            if record is None:
                return
            if retained is not None and retained.exists():
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                self._restore(retained, target)
            elif old is not None and not target.exists() and old.path.exists():
                # The old copy never moved; nothing to restore.
                return
            elif old is None and target.exists() and record.phase in {"swapped", "version_removed"}:
                shutil.rmtree(target, ignore_errors=True)
            self.journal.finish(record)
        except (OSError, ValueError, StateError, JournalError):
            _LOG.exception("MOD install rollback left a pending journal: %s", getattr(record, "operation_id", ""))

    def _self_check(self, target: Path, character_id: str, *, expected_digest: str = "") -> _CharacterPackage:
        """Re-read the landed package; a failed check never leaves it active."""
        package = _read_package(target, character_id=character_id, strict=True)
        if expected_digest and package.digest and package.digest != expected_digest:
            raise ModError(
                "激活后内容摘要不一致",
                issues=(ManifestIssue("content_hash_mismatch", "激活后内容摘要与导入时不一致"),),
            )
        return package

    # --------------------------------------------------------------- state

    def set_enabled(self, package_id: str, enabled: bool) -> ModOutcome:
        self._ensure_no_unresolved_operations()
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
        self._ensure_no_unresolved_operations()
        entry = self._entry(package_id)
        if not self.prepare_removal(entry):
            return ModOutcome(False, "无法释放正在使用的角色；请先自然退出相关桌宠", True)
        try:
            # All boundaries are checked before changing state or deleting files.
            targets = self._removal_targets(entry)
            for target in targets:
                safe_path(target)
            record = self.journal.begin(
                kind="remove",
                character_id=entry.character_id,
                target=entry.path,
                from_version=entry.version,
                to_version="",
                targets=targets,
            )
            # "deleted" means deletion started: recovery retries every target,
            # which is safe because rmtree of a missing path is never attempted.
            record = self.journal.advance(record, "deleted")
            for target in targets:
                if target.exists():
                    shutil.rmtree(target)
            self._prune_empty_roots()
            record = self.journal.advance(record, "committed")
            self.journal.finish(record)
        except (OSError, ValueError, ModError, StateError, JournalError):
            return ModOutcome(False, "删除未完成：请检查文件占用或目录内容；未删除部分已保留")
        self._prune_staging_root()
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

    def activate(self, package_id: str, version: str) -> ModOutcome:
        """Switch to any retained version (the directory-layout equivalent of
        upstream's ``activate(plugin_id, version)``)."""
        self._ensure_no_unresolved_operations()
        entry = self._entry(package_id)
        if entry.version == version:
            return ModOutcome(True, "已经在该版本")
        target = self.retained_root / entry.character_id / version
        if not target.is_dir():
            return ModOutcome(False, "没有这个保留版本")
        try:
            package = _read_package(target, character_id=entry.character_id, strict=True)
        except (ModError, OSError) as exc:
            return ModOutcome(False, "保留版本校验失败，未切换", diagnostic=getattr(exc, "issues", ()))
        if not self.prepare_removal(entry):
            return ModOutcome(False, "请自然退出使用该角色的桌宠后重试", True)
        try:
            self._swap_in(entry, target, expected_digest=package.digest)
        except (OSError, ValueError, ModError, StateError, JournalError) as exc:
            return ModOutcome(False, "切换版本未完成：原版本已保留", diagnostic=getattr(exc, "issues", ()))
        return ModOutcome(True, f"已切换到 {version}")

    def rollback(self, package_id: str) -> ModOutcome:
        self._ensure_no_unresolved_operations()
        entry = self._entry(package_id)
        previous = self._retained_versions(entry.character_id)
        if not previous:
            return ModOutcome(False, "没有可回滚版本，或文件仍被占用")
        if not self.prepare_removal(entry):
            return ModOutcome(False, "请自然退出使用该角色的桌宠后重试", True)
        version, target = previous[0]
        try:
            package = _read_package(target, character_id=entry.character_id, strict=True)
            self._swap_in(entry, target, expected_digest=package.digest)
        except (OSError, ValueError, ModError, StateError, JournalError) as exc:
            return ModOutcome(False, "没有可回滚版本，或文件仍被占用", diagnostic=getattr(exc, "issues", ()))
        return ModOutcome(True, f"已恢复上一版（{version}）")

    def _retained_versions(self, character_id: str) -> list[tuple[str, Path]]:
        parent = self.retained_root / character_id
        if not parent.is_dir():
            return []
        found: list[tuple[str, Path]] = []
        for version_dir in parent.iterdir():
            if not version_dir.is_dir():
                continue
            try:
                package = _read_package(version_dir, deep=False)
            except (ModError, OSError):
                continue
            if package.version == version_dir.name:
                found.append((package.version, version_dir))
        found.sort(key=lambda item: _version_key(item[0]), reverse=True)
        return found

    def retained_versions(self, package_id: str) -> list[str]:
        """Retained versions other than the active one (UI/controller seam)."""
        entry = self._entry(package_id)
        return [version for version, _path in self._retained_versions(entry.character_id) if version != entry.version]

    def _swap_in(self, entry: ModEntry, target: Path, *, expected_digest: str = "") -> None:
        target_root = self.live_root if entry.enabled else self.disabled_root
        resolved = target_root / entry.character_id
        if not _contains(self.data_root, resolved):
            raise ModError("回滚边界无效")
        stash = self.retained_root / entry.character_id / entry.version
        if not _contains(self.data_root, stash):
            raise ModError("回滚边界无效")
        stash.parent.mkdir(parents=True, exist_ok=True)
        if stash.exists():
            shutil.rmtree(stash)
        safe_path(entry.path)
        record = self.journal.begin(
            kind="activate",
            character_id=entry.character_id,
            target=resolved,
            retained=stash,
            incoming=target,
            from_version=entry.version,
            to_version=target.name,
        )
        try:
            os.replace(entry.path, stash)
            record = self.journal.advance(record, "version_removed")
            target_root.mkdir(parents=True, exist_ok=True)
            os.replace(target, resolved)
            record = self.journal.advance(record, "swapped")
            self._self_check(resolved, entry.character_id, expected_digest=expected_digest)
            record = self.journal.advance(record, "committed")
            self.journal.finish(record)
            self._prune_staging_root()
        except (OSError, ValueError, ModError, StateError, JournalError):
            try:
                if stash.exists():
                    if resolved.exists():
                        shutil.rmtree(resolved, ignore_errors=True)
                    os.replace(stash, resolved)
                self.journal.finish(record)
            except (OSError, ValueError, StateError, JournalError):
                _LOG.exception("MOD version switch left a pending journal: %s", record.operation_id)
            raise
