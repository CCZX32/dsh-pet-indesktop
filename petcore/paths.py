from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_NAME = "dsh-pet-core"
LEGACY_APP_NAME = "dsh-pet-standalone"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """安装目录：冻结包 = exe 所在目录；源码树 = 仓库根。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return repo_root()


def install_mods_dir() -> Path | None:
    """安装器投放的扩展目录（仅在冻结包里存在）。源码树不参与，避免把
    `repo/mods` 误当成「安装器授信」目录。"""
    if not is_frozen():
        return None
    return install_root() / "mods"


def user_mods_dirs(root: Path) -> tuple[Path, ...]:
    """允许加载 feature 的两个根：用户数据目录 + 安装目录（冻结包）。"""
    candidates = [Path(root) / "mods"]
    install = install_mods_dir()
    if install is not None:
        candidates.append(install)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(candidate)
    return tuple(ordered)


def base_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home())
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".config"


_INSTANCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def normalize_instance(instance: str | None) -> str | None:
    if instance is None or not str(instance).strip():
        return None
    value = str(instance).strip()
    if not _INSTANCE_RE.match(value):
        raise ValueError("instance name must match [A-Za-z0-9_-]{1,32}")
    return value


def data_root(portable: bool = False, instance: str | None = None) -> Path:
    name = normalize_instance(instance)
    if portable:
        return repo_root() / (f"data-{name}" if name else "data")
    return base_dir() / (f"{APP_NAME}-{name}" if name else APP_NAME)


def config_path(root: Path) -> Path:
    return root / "config.json"


def pet_config_path(root: Path, slot: int) -> Path:
    return config_path(root) if int(slot) <= 0 else root / f"config-pet-{int(slot)}.json"


def builtin_features_dir() -> Path:
    return repo_root() / "petcore" / "builtin" / "features"


def mods_state_path(root: Path) -> Path:
    return root / "mods-state.json"


def logs_dir(root: Path) -> Path:
    return root / "logs"


def feature_data_dir(root: Path, owner: str) -> Path:
    return root / "feature-data" / owner


def mods_dirs(root: Path, extra: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    install = install_mods_dir()
    candidates = [
        root / "mods",
        *((install,) if install is not None else ()),
        repo_root() / "mods",
        *extra,
    ]
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(candidate)
    return tuple(ordered)


def legacy_characters_root() -> Path:
    override = os.environ.get("PETCORE_LEGACY_ASSETS")
    if override:
        return Path(override)
    return repo_root() / "assets" / "characters"


def legacy_asset_root() -> Path:
    return repo_root() / "assets"


def legacy_config_path() -> Path:
    return base_dir() / LEGACY_APP_NAME / "config.json"


def legacy_data_roots() -> tuple[Path, ...]:
    """Return old standalone data roots, including published variants."""
    base = base_dir()
    candidates = [base / LEGACY_APP_NAME]
    try:
        candidates.extend(sorted(base.glob(f"{LEGACY_APP_NAME}-*")))
    except OSError:
        pass
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        result.append(resolved)
    return tuple(result)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
