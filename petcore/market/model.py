"""市场索引模型：纯解析与状态判断，不做网络、不碰文件。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .. import __version__ as CORE_VERSION
from ..mods.feature import CORE_FEATURE_IDS
from ..mods.manifest import (
    API_VERSION,
    KINDS,
    is_valid_id,
    parse_version,
    requirement_valid,
    version_satisfies,
)

SCHEMA_VERSION = 1

STATE_AVAILABLE = "available"
STATE_INSTALLED = "installed"
STATE_UPDATE = "update-available"
STATE_INCOMPATIBLE = "incompatible"
STATE_UNSUPPORTED = "unsupported"
STATE_BLOCKED = "blocked"
STATE_SUPERSEDED = "superseded"

STATE_LABELS = {
    STATE_AVAILABLE: "未安装",
    STATE_INSTALLED: "已安装",
    STATE_UPDATE: "可更新",
    STATE_INCOMPATIBLE: "不兼容",
    STATE_UNSUPPORTED: "当前平台不支持",
    STATE_BLOCKED: "已被阻止",
    STATE_SUPERSEDED: "已被替代",
}

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PLATFORM_ALIASES = {
    "windows": "win32",
    "win": "win32",
    "win32": "win32",
    "macos": "darwin",
    "mac": "darwin",
    "osx": "darwin",
    "darwin": "darwin",
    "linux": "linux",
}
_URL_PREFIXES = ("https://", "http://", "file://")

KNOWN_VERSION_FIELDS = frozenset(
    {"version", "released_at", "size", "sha256", "urls", "changelog", "yanked"}
)
KNOWN_PACKAGE_FIELDS = frozenset(
    {
        "id",
        "kind",
        "name",
        "name_zh",
        "summary_zh",
        "summary",
        "author",
        "homepage",
        "categories",
        "latest",
        "api_version",
        "core_requires",
        "execution",
        "capabilities",
        "platforms",
        "certified",
        "blocked",
        "blocked_reason",
        "superseded_by",
        "screenshots",
        "versions",
    }
)
KNOWN_INDEX_FIELDS = frozenset({"schema_version", "generated_at", "packages"})


@dataclass(frozen=True, slots=True)
class MarketVersion:
    version: str
    size: int
    sha256: str
    urls: tuple[str, ...]
    released_at: str = ""
    changelog: str = ""
    yanked: bool = False


@dataclass(frozen=True, slots=True)
class MarketPackage:
    id: str
    kind: str
    name: str
    version: str  # 索引声明的 latest
    versions: tuple[MarketVersion, ...]
    name_zh: str = ""
    summary: str = ""
    author: str = ""
    homepage: str = ""
    categories: tuple[str, ...] = ()
    api_version: str = API_VERSION
    core_requires: str = ""
    execution: str = "host-only"
    capabilities: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    certified: bool = False
    blocked: bool = False
    blocked_reason: str = ""
    superseded_by: str | None = None
    screenshots: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return self.name_zh or self.name or self.id


@dataclass(frozen=True, slots=True)
class MarketIndex:
    packages: tuple[MarketPackage, ...]
    generated_at: str = ""
    diagnostics: tuple[str, ...] = ()

    def by_id(self, mod_id: str) -> MarketPackage | None:
        for package in self.packages:
            if package.id == mod_id:
                return package
        return None


@dataclass(frozen=True, slots=True)
class PackageState:
    state: str
    reason: str = ""
    installed: str = ""
    latest: str = ""
    superseded_by: str | None = None

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    @property
    def installable(self) -> bool:
        return self.state in (STATE_AVAILABLE, STATE_UPDATE)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _string_tuple(value: Any, *, lower: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        text = item.strip()
        values.append(text.lower() if lower else text)
    return tuple(dict.fromkeys(values))


def normalize_platform(value: str) -> str:
    text = str(value or "").strip().lower()
    return _PLATFORM_ALIASES.get(text, text)


def _parse_version_entry(raw: Any, context: str) -> tuple[MarketVersion | None, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    if not isinstance(raw, Mapping):
        return None, [f"{context}: version entry must be an object"]
    for key in raw:
        if key not in KNOWN_VERSION_FIELDS:
            warnings.append(f"{context}: unknown field {key!r}")

    version = raw.get("version")
    if not isinstance(version, str) or parse_version(version) is None:
        return None, [*warnings, f"{context}: version must be X.Y.Z"]

    size = raw.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        errors.append(f"{context}: size must be a positive integer")

    sha256 = raw.get("sha256")
    if not isinstance(sha256, str) or _SHA256_RE.match(sha256) is None:
        errors.append(f"{context}: sha256 must be 64 hex characters")

    urls: list[str] = []
    raw_urls = raw.get("urls")
    if not isinstance(raw_urls, list):
        errors.append(f"{context}: urls must be a list")
    else:
        for item in raw_urls:
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{context}: invalid url {item!r}")
                continue
            if not item.strip().lower().startswith(_URL_PREFIXES):
                errors.append(f"{context}: unsupported url scheme {item!r}")
                continue
            urls.append(item.strip())
        if not urls:
            errors.append(f"{context}: at least one url is required")

    if errors:
        return None, [*warnings, *errors]

    return (
        MarketVersion(
            version=version,
            size=size,
            sha256=sha256.lower(),
            urls=tuple(urls),
            released_at=_text(raw.get("released_at")),
            changelog=_text(raw.get("changelog")),
            yanked=_bool(raw.get("yanked")),
        ),
        warnings,
    )


def _parse_package(raw: Any) -> tuple[MarketPackage | None, list[str]]:
    problems: list[str] = []
    if not isinstance(raw, Mapping):
        return None, ["package entry must be an object"]

    for key in raw:
        if key not in KNOWN_PACKAGE_FIELDS:
            problems.append(f"{raw.get('id', '?')}: unknown field {key!r}")

    mod_id = raw.get("id")
    if not isinstance(mod_id, str) or not is_valid_id(mod_id):
        return None, [*problems, f"invalid id: {mod_id!r}"]
    if mod_id in CORE_FEATURE_IDS:
        return None, [*problems, f"{mod_id}: reserved id (Core feature)"]

    context = mod_id
    kind = raw.get("kind")
    if kind not in KINDS:
        return None, [*problems, f"{context}: kind must be one of {sorted(KINDS)}"]

    name = _text(raw.get("name")) or mod_id
    name_zh = _text(raw.get("name_zh"))
    latest = raw.get("latest")
    if not isinstance(latest, str) or parse_version(latest) is None:
        return None, [*problems, f"{context}: latest must be X.Y.Z"]

    core_requires = raw.get("core_requires", "")
    if not isinstance(core_requires, str):
        problems.append(f"{context}: core_requires must be a string")
        core_requires = ""
    elif not requirement_valid(core_requires):
        problems.append(f"{context}: malformed core_requires {core_requires!r}")

    api_version = raw.get("api_version", API_VERSION)
    if not isinstance(api_version, str) or not api_version:
        problems.append(f"{context}: api_version must be a string")
        api_version = ""

    execution = raw.get("execution", "host-only")
    if not isinstance(execution, str) or execution not in ("host-only", "worker"):
        problems.append(f"{context}: execution must be host-only or worker")
        execution = "host-only"

    platforms: tuple[str, ...] = ()
    raw_platforms = raw.get("platforms")
    if raw_platforms is not None:
        if not isinstance(raw_platforms, list):
            problems.append(f"{context}: platforms must be a list")
        else:
            platforms = tuple(
                dict.fromkeys(
                    normalize_platform(item)
                    for item in raw_platforms
                    if isinstance(item, str) and item.strip()
                )
            )

    superseded_by = raw.get("superseded_by")
    if superseded_by is not None:
        if not isinstance(superseded_by, str) or not is_valid_id(superseded_by):
            problems.append(f"{context}: superseded_by must be a mod id")
            superseded_by = None

    versions: list[MarketVersion] = []
    raw_versions = raw.get("versions")
    if not isinstance(raw_versions, list):
        return None, [*problems, f"{context}: versions must be a list"]
    for index, item in enumerate(raw_versions):
        version_entry, version_problems = _parse_version_entry(
            item, f"{context}.versions[{index}]"
        )
        problems.extend(version_problems)
        if version_entry is not None:
            versions.append(version_entry)

    versions.sort(key=lambda item: parse_version(item.version) or (0, 0, 0), reverse=True)
    if not any(item.version == latest and not item.yanked for item in versions):
        declared = {
            item.get("version") for item in raw_versions if isinstance(item, Mapping)
        }
        yanked = any(
            isinstance(item, Mapping)
            and item.get("version") == latest
            and item.get("yanked") is True
            for item in raw_versions
        )
        if yanked:
            return None, [*problems, f"{context}: latest {latest} is yanked"]
        if latest not in declared:
            return None, [*problems, f"{context}: latest {latest} is missing"]
        # 版本条目存在但字段不合法：保留包（UI 显示「没有可安装版本」），诊断说明原因。
        problems.append(f"{context}: latest {latest} is not installable")

    package = MarketPackage(
        id=mod_id,
        kind=kind,
        name=name,
        version=latest,
        versions=tuple(versions),
        name_zh=name_zh,
        summary=_text(raw.get("summary_zh")) or _text(raw.get("summary")),
        author=_text(raw.get("author")),
        homepage=_text(raw.get("homepage")),
        categories=_string_tuple(raw.get("categories"), lower=True),
        api_version=api_version,
        core_requires=core_requires,
        execution=execution,
        capabilities=_string_tuple(raw.get("capabilities")),
        platforms=platforms,
        certified=_bool(raw.get("certified")),
        blocked=_bool(raw.get("blocked")),
        blocked_reason=_text(raw.get("blocked_reason")),
        superseded_by=superseded_by,
        screenshots=_string_tuple(raw.get("screenshots")),
    )
    return package, problems


def _parse_mapping(raw: Mapping[str, Any]) -> tuple[MarketIndex | None, list[str]]:
    problems: list[str] = []
    for key in raw:
        if key not in KNOWN_INDEX_FIELDS:
            problems.append(f"index: unknown field {key!r}")

    schema = raw.get("schema_version")
    if schema != SCHEMA_VERSION:
        return None, [*problems, f"schema_version must be {SCHEMA_VERSION}, got {schema!r}"]

    raw_packages = raw.get("packages")
    if not isinstance(raw_packages, list):
        return None, [*problems, "index: packages must be a list"]

    packages: list[MarketPackage] = []
    seen: set[str] = set()
    for item in raw_packages:
        package, package_problems = _parse_package(item)
        problems.extend(package_problems)
        if package is None:
            continue
        if package.id in seen:
            problems.append(f"{package.id}: duplicate package entry")
            continue
        seen.add(package.id)
        packages.append(package)

    packages.sort(key=lambda item: item.id)
    index = MarketIndex(
        packages=tuple(packages),
        generated_at=_text(raw.get("generated_at")),
        diagnostics=tuple(problems),
    )
    return index, problems


def parse_index(raw: Any) -> tuple[MarketIndex | None, list[str]]:
    if not isinstance(raw, Mapping):
        return None, ["index: top level must be an object"]
    try:
        return _parse_mapping(raw)
    except Exception as exc:  # noqa: BLE001 - 坏索引只许变成诊断
        return None, [f"index: {type(exc).__name__}: {exc}"]


def parse_index_text(text: str) -> tuple[MarketIndex | None, list[str]]:
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        return None, [f"index: invalid JSON: {exc}"]
    return parse_index(raw)


def latest_version(package: MarketPackage | None) -> MarketVersion | None:
    if package is None:
        return None
    for version in package.versions:
        if version.version == package.version and not version.yanked:
            return version
    return None


def version_entry(package: MarketPackage, version: str) -> MarketVersion | None:
    for item in package.versions:
        if item.version == version:
            return item
    return None


def platform_supported(
    package: MarketPackage | None, platform: str, *, default: bool = True
) -> bool:
    if package is None:
        return False
    if not package.platforms:
        return default
    return normalize_platform(platform) in package.platforms


def core_compatible(package: MarketPackage | None, core_version: str = CORE_VERSION) -> bool:
    if package is None:
        return False
    if not package.core_requires:
        return True
    return version_satisfies(package.core_requires, core_version)


def package_state(
    package: MarketPackage | None,
    *,
    installed_version: str | None,
    core_version: str = CORE_VERSION,
    platform: str,
    api_version: str = API_VERSION,
    blocked: bool = False,
    blocked_reason: str = "",
    superseded_by: str | None = None,
) -> PackageState:
    installed = installed_version or ""
    latest = package.version if package is not None else ""

    if package is None:
        return PackageState(STATE_INCOMPATIBLE, "索引中没有这个包", installed=installed)

    blocked = blocked or package.blocked
    if blocked:
        reason = blocked_reason or package.blocked_reason or "作者或索引维护者已阻止该版本"
        return PackageState(STATE_BLOCKED, reason, installed=installed, latest=latest)

    superseded = superseded_by or package.superseded_by
    if superseded:
        return PackageState(
            STATE_SUPERSEDED,
            f"已由 {superseded} 替代",
            installed=installed,
            latest=latest,
            superseded_by=superseded,
        )

    if package.api_version and package.api_version != api_version:
        return PackageState(
            STATE_INCOMPATIBLE,
            f"需要扩展 API {package.api_version}，当前为 {api_version}",
            installed=installed,
            latest=latest,
        )

    if not platform_supported(package, platform):
        return PackageState(
            STATE_UNSUPPORTED,
            f"当前平台（{normalize_platform(platform)}）不在支持列表内",
            installed=installed,
            latest=latest,
        )

    if not core_compatible(package, core_version):
        return PackageState(
            STATE_INCOMPATIBLE,
            f"需要 Core {package.core_requires}，当前为 {core_version}",
            installed=installed,
            latest=latest,
        )

    if latest_version(package) is None:
        return PackageState(STATE_INCOMPATIBLE, "没有可安装的版本", installed=installed)

    if installed:
        current = parse_version(installed)
        target = parse_version(latest)
        if current is not None and target is not None and current < target:
            return PackageState(STATE_UPDATE, installed=installed, latest=latest)
        return PackageState(STATE_INSTALLED, installed=installed, latest=latest)

    return PackageState(STATE_AVAILABLE, installed="", latest=latest)


def normalize_index_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.lower().startswith(("https://", "http://", "file://")):
        return ""
    return text
