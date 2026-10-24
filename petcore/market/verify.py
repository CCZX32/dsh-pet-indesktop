"""artifact 与包内 manifest 的交叉校验。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import __version__ as CORE_VERSION
from ..contracts.capabilities import CAPABILITIES
from ..mods.manifest import ModManifest, load_manifest, version_satisfies
from .errors import IntegrityError, ManifestMismatch
from .model import MarketPackage, MarketVersion

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: Path, version: MarketVersion) -> str:
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IntegrityError(f"无法读取下载文件：{exc}") from exc
    if size != version.size:
        raise IntegrityError(f"大小不一致：期望 {version.size}，实际 {size}")
    digest = sha256_file(path)
    if digest != version.sha256:
        raise IntegrityError("SHA-256 与索引不一致")
    return digest


def read_pack_manifest(pack_dir: Path) -> ModManifest:
    manifest, problems = load_manifest(Path(pack_dir))
    if manifest is None:
        detail = "；".join(problems) or "无效的 mod.json"
        raise ManifestMismatch(f"包内 manifest 无效：{detail}")
    return manifest


def verify_manifest(
    manifest: ModManifest,
    package: MarketPackage,
    version: MarketVersion,
    *,
    core_version: str = CORE_VERSION,
) -> None:
    """索引与包内 manifest 的交叉校验（T04）。

    除了 id/kind/version，还核对能力越权、API 版本与 Core 兼容性：
    - 包内能力必须都是已知能力，且**不得超出**索引为该包声明的集合（防提权）；
    - 包内 `api_version` 必须与索引声明一致；
    - `manifest.core_requires` 必须满足当前 Core（索引侧已有一道，这里是纵深防御）。
    """
    checks = (
        ("id", manifest.id, package.id),
        ("kind", manifest.kind, package.kind),
        ("version", manifest.version, version.version),
    )
    for field, actual, expected in checks:
        if actual != expected:
            raise ManifestMismatch(
                f"包内 {field} 与索引不一致：索引为 {expected!r}，包内为 {actual!r}"
            )
    unknown = [item for item in manifest.capabilities if item not in CAPABILITIES]
    if unknown:
        raise ManifestMismatch(f"包内声明了未知能力：{', '.join(sorted(unknown))}")
    ungranted = [
        item for item in manifest.capabilities if item not in package.capabilities
    ]
    if ungranted:
        raise ManifestMismatch(
            f"包内声明了索引未授权的能力：{', '.join(sorted(ungranted))}"
        )
    if manifest.api_version != package.api_version:
        raise ManifestMismatch(
            f"包内 api_version 与索引不一致：索引为 {package.api_version!r}，包内为 {manifest.api_version!r}"
        )
    if manifest.core_requires and not version_satisfies(
        manifest.core_requires, core_version
    ):
        raise ManifestMismatch(
            f"包内 core_requires {manifest.core_requires} 不满足当前 Core {core_version}"
        )
