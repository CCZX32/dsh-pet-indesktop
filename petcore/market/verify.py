"""artifact 与包内 manifest 的交叉校验。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..mods.manifest import ModManifest, load_manifest
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
    manifest: ModManifest, package: MarketPackage, version: MarketVersion
) -> None:
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
