# -*- coding: utf-8 -*-
"""Local package routing: bounded manifest evidence, no import or execution.

Ported from the DLC branch ``pet/local_package_intents.py``；本片只搬**路由那一半**
（:class:`LocalPackageRoute` + :func:`route_local_package`）——它只读有界清单元数据，
用来回答"这个包该交给哪个 owner"，绝不导入包代码、不建 Worker。

DLC 同文件的后半段（``LocalPackageIntent`` / ``attach_local_package_manager`` /
``create_local_package_dialog`` / ``run_local_packages``）是**已关闭的 Setup 适配层**，
依赖 GUI 管理面板与 ``FeatureManagementRuntime``。
**D2 片 2 起本仓库的等价物已经落地，但不在这条路上**：包声明路由由
``pet/settings_mod_domain.DialogModHost.feature_route`` 转给
``pet/feature_management.LocalFeatureRuntime.route``（读到 owner 就地为它建管理器），
导入动作仍由 ``ModCenterController`` 派给那个管理器——所以这里只保留只读路由那一半，
不搬 Setup 的对话框与批量安装器。

A user-selected directory or ZIP is routed only from bounded manifest metadata.
The target manager performs the full verifier, transaction, self-check and
startup work. Local activation is explicit user trust, not publisher
authentication or sandboxing.
"""

from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .plugins.package_trust import PackageVerificationError, read_manifest_registration

_ROUTE_MANIFEST_LIMIT = 2 * 1024 * 1024
_ROUTE_ENTRY_LIMIT = 16384
_ROUTE_PLATFORMS = frozenset({"win32", "linux", "darwin"})

__all__ = ["LocalPackageRoute", "route_local_package"]


@dataclass(frozen=True)
class LocalPackageRoute:
    """Bounded, non-executable routing evidence for a user-selected package.

    The route is deliberately weaker than :class:`VerifiedFeatureDescriptor`:
    it only tells the caller which generic feature registration should receive
    the package.  The selected source must still pass the full verifier before
    it can be staged, installed, imported, or started.
    """

    source: Path
    feature_id: str
    factory: str
    execution_kind: str
    format_version: int
    version: str
    api_version: str
    core_requires: str
    platforms: tuple[str, ...]
    capabilities: tuple[str, ...]
    manifest_digest: str
    manifest: Mapping

    @classmethod
    def from_manifest(cls, source: Path, raw: bytes) -> "LocalPackageRoute":
        try:
            registration, payload = read_manifest_registration(raw, max_bytes=_ROUTE_MANIFEST_LIMIT)
            version = payload["version"]
            api_version = payload["api_version"]
            core_requires = payload["core_requires"]
            platforms = payload["platforms"]
            capabilities = payload["capabilities"]
            if not isinstance(version, str) or not version:
                raise PackageVerificationError("invalid package version")
            if not isinstance(api_version, str) or not api_version or len(api_version) > 128:
                raise PackageVerificationError("invalid package API version")
            if not isinstance(core_requires, str) or not core_requires or len(core_requires) > 1024:
                raise PackageVerificationError("invalid Core version requirement")
            if (
                not isinstance(platforms, list)
                or not platforms
                or len(platforms) > len(_ROUTE_PLATFORMS)
                or len(platforms) != len(set(platforms))
                or any(platform not in _ROUTE_PLATFORMS for platform in platforms)
            ):
                raise PackageVerificationError("invalid package platforms")
            if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)):
                raise PackageVerificationError("invalid package capabilities")
            frozen_manifest = _freeze_manifest(payload)
            return cls(
                source=source,
                feature_id=registration.id,
                factory=registration.factory,
                execution_kind=registration.execution_kind,
                format_version=2 if "format_version" in payload else 1,
                version=version,
                api_version=api_version,
                core_requires=core_requires,
                platforms=tuple(platforms),
                capabilities=tuple(capabilities),
                manifest_digest=hashlib.sha256(raw).hexdigest(),
                manifest=frozen_manifest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PackageVerificationError):
                raise
            raise PackageVerificationError("local package route invalid") from exc


def _freeze_manifest(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_manifest(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_manifest(item) for item in value)
    return value


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise PackageVerificationError("manifest size limit")
    return raw


def _safe_archive_name(name: str) -> str:
    if not isinstance(name, str) or "\\" in name or "\x00" in name or len(name) > 512:
        raise PackageVerificationError("unsafe archive path")
    if PurePosixPath(name).is_absolute():
        raise PackageVerificationError("unsafe archive path")
    parts = name.rstrip("/").split("/")
    if not name or not parts or any(not part or part in {".", ".."} for part in parts):
        raise PackageVerificationError("unsafe archive path")
    return "/".join(parts)


def _read_zip_manifest(source: Path) -> bytes:
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= _ROUTE_ENTRY_LIMIT:
                raise PackageVerificationError("archive entry limit")
            names: dict[str, tuple[str, bool]] = {}
            manifest = None
            for member in members:
                name = _safe_archive_name(member.filename)
                mode = member.external_attr >> 16
                if member.flag_bits & 1 or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or member.external_attr & 0x400:
                    raise PackageVerificationError("unsafe archive member")
                folded = name.casefold()
                if folded in names:
                    raise PackageVerificationError("duplicate archive entry")
                is_dir = member.is_dir()
                names[folded] = name, is_dir
                if name == "manifest.json":
                    if is_dir or manifest is not None or member.file_size > _ROUTE_MANIFEST_LIMIT:
                        raise PackageVerificationError("invalid archive manifest")
                    manifest = member
            if manifest is None:
                raise PackageVerificationError("manifest missing")
            for name, _is_dir in names.values():
                parts = name.split("/")
                for index in range(1, len(parts)):
                    prefix = "/".join(parts[:index])
                    entry = names.get(prefix.casefold())
                    if entry is not None and (entry[0] != prefix or not entry[1]):
                        raise PackageVerificationError("archive path collision")
            raw = archive.read(manifest)
            if len(raw) > _ROUTE_MANIFEST_LIMIT:
                raise PackageVerificationError("manifest size limit")
            return raw
    except zipfile.BadZipFile as exc:
        raise PackageVerificationError("invalid local package archive") from exc


def route_local_package(source: Path | str) -> LocalPackageRoute:
    """Read a selected directory/ZIP manifest without importing or executing it."""

    try:
        path = Path(source).expanduser().resolve(strict=True)
        if path.is_dir():
            manifest = path / "manifest.json"
            if manifest.is_symlink() or not manifest.is_file():
                raise PackageVerificationError("manifest missing")
            raw = _read_bounded(manifest, _ROUTE_MANIFEST_LIMIT)
        elif path.is_file():
            raw = _read_zip_manifest(path)
        else:
            raise PackageVerificationError("local package source invalid")
        return LocalPackageRoute.from_manifest(path, raw)
    except PackageVerificationError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PackageVerificationError("local package route invalid") from exc
