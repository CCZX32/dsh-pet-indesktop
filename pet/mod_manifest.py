# -*- coding: utf-8 -*-
"""资源包 manifest 的严格契约与内容校验。零 Qt。

本仓库的资源包布局是 ``characters/<id>/``（启用）与 ``mod-disabled/<id>/``（停用），
没有上游 ``content/characters/<id>/versions/<v>`` 那棵版本指针树；因此本模块只移植
**与指针无关**的那一半硬门：

* 清单字段的严格契约（``kind`` / ``api_version`` / ``core_requires`` / ``platforms`` /
  禁 ``entrypoint`` / 禁可执行文件 / 派生 cache 必须在包根之外）；
* 角色目录与视频素材的存在性、0 字节拒绝；
* 逻辑内容摘要（:mod:`pet.mod_hashing`），可与清单声明的 ``integrity.sha256`` 对账。

**只用于导入/托管包**。用户手工放进角色根、没有 manifest 的目录仍是"手动素材"，
由 :func:`pet.mod_management._read_package` 的浅读路径继续兼容——那份宽松不是漏洞，
而是文档写明的兼容来源（``docs/modding/CHARACTER-PACKS.md`` §三）。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mod_hashing import MANIFEST_FILENAME, content_sha256, iter_directory_files

SUPPORTED_PLATFORMS = frozenset({"windows", "macos", "linux"})

#: 资源包 id 与角色 id 共用一套目录安全规则：允许非 ASCII（手工角色目录常见中文），
#: 但拒绝路径分隔符、控制字符、Windows 设备名与末尾点。
_UNSAFE_ID_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
_DEVICE_ID = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.[^.]*)?\Z", re.IGNORECASE)
_VERSION_RE = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_CORE_CLAUSE_RE = re.compile(r"(<=|>=|==|<|>)(\d+\.\d+\.\d+)\Z")

MAX_ID_CHARS = 128
MAX_NAME_CHARS = 256
MAX_DESCRIPTION_CHARS = 4096

_EXECUTABLE_SUFFIXES = frozenset(
    {".py", ".pyw", ".pyc", ".pyd", ".dll", ".so", ".dylib", ".exe", ".bat", ".cmd", ".com", ".ps1", ".sh", ".js", ".vbs"}
)
_VIDEO_SUFFIXES = frozenset({".webm", ".gif"})

#: 派生 cache 只能写在包根之外：它一变就会改变包身份、也会被激活事务覆盖。
_DERIVED_CACHE_DIR_NAMES = frozenset(
    {".cache", "cache", "derived", "derived-cache", "frameseq", "index", "indexes", "thumbnail", "thumbnails"}
)


@dataclass(frozen=True)
class ManifestIssue:
    """一条可机器判定的清单/内容问题；``code`` 是闭集，``message`` 给用户看。"""

    code: str
    message: str


@dataclass(frozen=True)
class ResourceManifest:
    package_id: str
    name: str
    version: str
    kind: str
    api_version: str
    core_requires: str
    platforms: tuple[str, ...]
    dependencies: tuple[str, ...]
    capabilities: tuple[str, ...]
    characters: tuple[str, ...]
    integrity_sha256: str | None
    signature: str | None
    description: str = ""


def is_safe_package_id(value: object) -> bool:
    """一个角色包 id 会成为我们拥有的根目录下的一级目录名。"""
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS:
        return False
    if value in {".", ".."} or value != value.strip() or value.endswith("."):
        return False
    if _UNSAFE_ID_CHARS.search(value):
        return False
    return not _DEVICE_ID.fullmatch(value)


def current_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _semver(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def version_satisfies(version: str, requirement: str) -> bool:
    """``>=4.2.5,<6.0.0`` 这类核心版本区间；空串与 ``*`` 表示不设限。"""
    current = _semver(version)
    requirement = requirement.strip()
    if not requirement or requirement in {"*", ">=0"}:
        return True
    for raw in requirement.split(","):
        clause = raw.strip()
        match = _CORE_CLAUSE_RE.fullmatch(clause)
        if not match:
            raise ValueError(f"invalid core_requires clause: {clause}")
        operator, literal = match.groups()
        target = _semver(literal)
        if operator == ">=" and not current >= target:
            return False
        if operator == ">" and not current > target:
            return False
        if operator == "<=" and not current <= target:
            return False
        if operator == "<" and not current < target:
            return False
        if operator == "==" and not current == target:
            return False
    return True


def _require_object(raw: dict[str, Any], key: str, issues: list[ManifestIssue]) -> dict[str, Any] | None:
    value = raw.get(key)
    if not isinstance(value, dict):
        issues.append(ManifestIssue(f"{key}_invalid", f"{key} 必须是一个对象"))
        return None
    return value


def _require_text(raw: dict[str, Any], key: str, issues: list[ManifestIssue], *, limit: int | None = None) -> str | None:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(ManifestIssue(f"{key}_invalid", f"{key} 必须是非空字符串"))
        return None
    if limit is not None and len(value) > limit:
        issues.append(ManifestIssue(f"{key}_too_long", f"{key} 不能超过 {limit} 个字符"))
        return None
    return value


def _require_text_list(raw: dict[str, Any], key: str, issues: list[ManifestIssue]) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        issues.append(ManifestIssue(f"{key}_invalid", f"{key} 必须是字符串数组"))
        return ()
    return tuple(value)


def load_resource_manifest(root: Path) -> tuple[ResourceManifest | None, list[ManifestIssue]]:
    """读并校验包根的 ``manifest.json``；返回 ``(manifest, issues)``。"""
    root = Path(root)
    path = root / MANIFEST_FILENAME
    issues: list[ManifestIssue] = []
    if not path.is_file():
        return None, [ManifestIssue("manifest_missing", "角色包缺少 manifest.json")]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [ManifestIssue("manifest_invalid", f"manifest.json 无法解析：{exc}")]
    if not isinstance(raw, dict):
        return None, [ManifestIssue("manifest_not_object", "manifest.json 必须是一个对象")]

    package_id = _require_text(raw, "id", issues, limit=MAX_ID_CHARS)
    name = _require_text(raw, "name", issues, limit=MAX_NAME_CHARS)
    version = _require_text(raw, "version", issues)
    kind = _require_text(raw, "kind", issues)
    api_version = _require_text(raw, "api_version", issues)
    core_requires = _require_text(raw, "core_requires", issues)
    description = raw.get("description", "")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_CHARS or "\x00" in description:
        issues.append(ManifestIssue("description_invalid", "description 必须是纯文本且不超过 4096 个字符"))
    platforms = _require_text_list(raw, "platforms", issues)
    dependencies = _require_text_list(raw, "dependencies", issues)
    capabilities = _require_text_list(raw, "capabilities", issues)
    content = _require_object(raw, "content", issues)

    entrypoint = raw.get("entrypoint")
    if entrypoint is not None:
        issues.append(ManifestIssue("entrypoint_forbidden", "资源包不允许声明 entrypoint"))

    if package_id is not None and not is_safe_package_id(package_id):
        issues.append(ManifestIssue("id_invalid", "id 含不支持的字符或 Windows 设备名"))
    if version is not None and not _VERSION_RE.fullmatch(version):
        issues.append(ManifestIssue("version_invalid", "version 必须是语义化的 x.y.z"))
    if kind is not None and kind != "content":
        issues.append(ManifestIssue("kind_invalid", "kind 必须是 content"))
    if api_version is not None and api_version != "1":
        issues.append(ManifestIssue("api_version_invalid", "api_version 必须是 1"))
    if core_requires is not None:
        try:
            version_satisfies("0.0.0", core_requires)
        except ValueError as exc:
            issues.append(ManifestIssue("core_requires_invalid", str(exc)))
    for platform_name in platforms:
        if platform_name not in SUPPORTED_PLATFORMS:
            issues.append(ManifestIssue("platform_invalid", f"platforms 含不支持的平台：{platform_name}"))

    characters: tuple[str, ...] = ()
    if content is not None:
        raw_characters = content.get("characters")
        if not isinstance(raw_characters, list) or not raw_characters or not all(isinstance(item, str) for item in raw_characters):
            issues.append(ManifestIssue("characters_invalid", "content.characters 必须是非空字符串数组"))
        else:
            characters = tuple(raw_characters)
            for character_id in characters:
                if not is_safe_package_id(character_id):
                    issues.append(ManifestIssue("character_id_invalid", f"角色 id 含不支持的字符：{character_id!r}"))

    integrity = raw.get("integrity")
    integrity_sha256: str | None = None
    signature: str | None = None
    if integrity is not None:
        if not isinstance(integrity, dict):
            issues.append(ManifestIssue("integrity_invalid", "integrity 必须是一个对象"))
        else:
            raw_hash = integrity.get("sha256")
            raw_signature = integrity.get("signature")
            if raw_hash is not None and (not isinstance(raw_hash, str) or not _SHA256_RE.fullmatch(raw_hash)):
                issues.append(ManifestIssue("integrity_sha256_invalid", "integrity.sha256 必须是 64 位十六进制或 null"))
            elif isinstance(raw_hash, str):
                integrity_sha256 = raw_hash.lower()
            if raw_signature is not None and not isinstance(raw_signature, str):
                issues.append(ManifestIssue("integrity_signature_invalid", "integrity.signature 必须是字符串或 null"))
            elif isinstance(raw_signature, str):
                signature = raw_signature

    if issues:
        return None, issues
    assert package_id is not None and name is not None and version is not None
    assert kind is not None and api_version is not None and core_requires is not None
    return ResourceManifest(
        package_id=package_id,
        name=name,
        version=version,
        kind=kind,
        api_version=api_version,
        core_requires=core_requires,
        platforms=platforms,
        dependencies=dependencies,
        capabilities=capabilities,
        characters=characters,
        integrity_sha256=integrity_sha256,
        signature=signature,
        description=description,
    ), []


def _video_files(root: Path) -> list[Path]:
    videos = root / "videos"
    if not videos.is_dir():
        return []
    return [path for path in videos.rglob("*") if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES]


def _validate_content(root: Path, manifest: ResourceManifest, issues: list[ManifestIssue]) -> None:
    """角色目录与视频素材：包根本身是单角色，或多角色时在 ``characters/<id>/``。"""
    single_root = root / "videos"
    for character_id in manifest.characters:
        if character_id == manifest.package_id and single_root.is_dir():
            character_root = root
        else:
            character_root = root / "characters" / character_id
            if not character_root.is_dir():
                issues.append(ManifestIssue("character_missing", f"清单声明的角色目录不存在：{character_id}"))
                continue
        videos = _video_files(character_root)
        if not videos:
            issues.append(ManifestIssue("videos_missing", f"角色缺少 .webm/.gif 素材：{character_id}"))
            continue
        try:
            if any(path.stat().st_size == 0 for path in videos):
                issues.append(ManifestIssue("video_empty", f"角色素材含 0 字节文件：{character_id}"))
        except OSError as exc:
            issues.append(ManifestIssue("videos_unreadable", f"无法读取角色素材：{exc}"))


def validate_resource_package(
    root: Path,
    *,
    core_version: str,
    platform_name: str | None = None,
    declared_hash: str | None = None,
) -> tuple[ResourceManifest | None, list[ManifestIssue], str | None]:
    """严格校验一个待导入/已激活包；返回 ``(manifest, issues, digest)``。

    ``declared_hash`` 是调用方额外提供的期望摘要（例如更新请求）；包清单里的
    ``integrity.sha256`` 也参与对账。摘要只回答"内容有没有变"，不是发布者认证。
    """
    root = Path(root)
    issues: list[ManifestIssue] = []
    manifest, manifest_issues = load_resource_manifest(root)
    issues.extend(manifest_issues)
    if manifest is None:
        # Without a valid manifest this tree can never be installed; do not walk
        # tens of thousands of frames just to report that again per file.
        return None, issues, None

    try:
        reported_codes = {issue.code for issue in issues}
        for relative, path in iter_directory_files(root):
            if path.suffix.lower() in _EXECUTABLE_SUFFIXES and "executable_forbidden" not in reported_codes:
                issues.append(ManifestIssue("executable_forbidden", f"资源包内不允许可执行文件：{relative.as_posix()}"))
                reported_codes.add("executable_forbidden")
            if any(part.casefold() in _DERIVED_CACHE_DIR_NAMES for part in relative.parts[:-1]) and "derived_cache_inside" not in reported_codes:
                issues.append(ManifestIssue("derived_cache_inside", f"派生 cache 必须在包根之外：{relative.as_posix()}"))
                reported_codes.add("derived_cache_inside")
    except (OSError, ValueError) as exc:
        issues.append(ManifestIssue("tree_invalid", str(exc)))
        return None, issues, None

    requested_platform = platform_name or current_platform()
    if manifest.platforms and requested_platform not in manifest.platforms:
        issues.append(ManifestIssue("platform_unsupported", f"清单不支持当前平台：{requested_platform}"))
    try:
        if not version_satisfies(core_version, manifest.core_requires):
            issues.append(ManifestIssue("core_requires_unsatisfied", f"Core {core_version} 不满足 {manifest.core_requires}"))
    except ValueError as exc:
        issues.append(ManifestIssue("core_requires_invalid", str(exc)))

    _validate_content(root, manifest, issues)

    if issues:
        return None, issues, None

    digest: str | None = None
    expected = declared_hash or manifest.integrity_sha256
    try:
        digest = content_sha256(root)
    except (OSError, ValueError) as exc:
        issues.append(ManifestIssue("hash_unavailable", f"无法计算内容摘要：{exc}"))
    if expected is not None:
        if not _SHA256_RE.fullmatch(expected):
            issues.append(ManifestIssue("expected_hash_invalid", "期望的内容摘要必须是 64 位十六进制"))
        elif digest is not None and digest.lower() != expected.lower():
            issues.append(ManifestIssue("content_hash_mismatch", "内容摘要与清单/期望值不一致"))

    return (manifest if not issues else None), issues, digest


__all__ = [
    "MAX_ID_CHARS",
    "MAX_NAME_CHARS",
    "ManifestIssue",
    "ResourceManifest",
    "SUPPORTED_PLATFORMS",
    "current_platform",
    "is_safe_package_id",
    "load_resource_manifest",
    "validate_resource_package",
    "version_satisfies",
]
