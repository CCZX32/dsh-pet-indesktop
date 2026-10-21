from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..log import get_logger
from . import state, trust
from .manifest import MOD_FILE, ModManifest, load_manifest, path_within

_logger = get_logger("mods.loader")


@dataclass(frozen=True, slots=True)
class LoadedMod:
    manifest: ModManifest
    enabled: bool
    path: Path

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def kind(self) -> str:
        return self.manifest.kind


@dataclass(frozen=True, slots=True)
class ContentEntry:
    kind: str
    id: str
    data: Any
    path: Path
    owner: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    mods: tuple[LoadedMod, ...]
    contents: tuple[ContentEntry, ...]
    diagnostics: tuple[str, ...]


def _extract_contents(mod: LoadedMod) -> tuple[list[ContentEntry], list[str]]:
    manifest = mod.manifest
    entries: list[ContentEntry] = []
    problems: list[str] = []

    if manifest.character is not None:
        character = manifest.character
        character_id = character.get("id")
        if not isinstance(character_id, str) or not character_id.strip():
            character_id = manifest.id
            if character_id.startswith("character.") and len(character_id) > len("character."):
                character_id = character_id[len("character."):]
        entries.append(
            ContentEntry(
                kind="character",
                id=character_id,
                data=dict(character),
                path=manifest.path,
                owner=manifest.id,
            )
        )

    blocks = (
        ("sound", manifest.sounds),
        ("theme", manifest.themes),
        ("phrases", manifest.phrases),
        ("seasonal", manifest.seasonal),
    )
    for kind, block in blocks:
        if block is None:
            continue
        for entry_id, data in block.items():
            if not isinstance(entry_id, str) or not entry_id.strip():
                problems.append(f"invalid {kind} id: {entry_id!r}")
                continue
            entries.append(
                ContentEntry(
                    kind=kind,
                    id=entry_id,
                    data=data,
                    path=manifest.path,
                    owner=manifest.id,
                )
            )
    return entries, problems


def load_mods(
    root: Path,
    extra: tuple[Path, ...] = (),
    *,
    allow_feature_mods: bool = False,
) -> LoadResult:
    root = Path(root)
    disabled = state.load_disabled(root)
    diagnostics: list[str] = []
    found: dict[str, LoadedMod] = {}

    for directory in paths.mods_dirs(root, tuple(extra)):
        if not directory.is_dir():
            continue
        try:
            children = sorted(
                (
                    child
                    for child in directory.iterdir()
                    if child.is_dir() and not child.name.startswith(".")
                ),
                key=lambda child: child.name,
            )
        except OSError as exc:
            diagnostics.append(f"{directory}: cannot scan mods directory: {exc}")
            continue
        for child in children:
            if not (child / MOD_FILE).is_file():
                continue
            try:
                manifest, problems = load_manifest(child)
            except Exception as exc:
                diagnostics.append(f"{child}: {type(exc).__name__}: {exc}")
                continue
            if manifest is None:
                diagnostics.extend(f"{child}: {problem}" for problem in problems)
                continue
            diagnostics.extend(f"{manifest.id}: {problem}" for problem in problems)
            previous = found.get(manifest.id)
            if previous is not None:
                diagnostics.append(
                    f"duplicate mod id {manifest.id!r}: {previous.path} overridden by {manifest.path}"
                )
            found[manifest.id] = LoadedMod(
                manifest=manifest,
                enabled=manifest.id not in disabled,
                path=manifest.path,
            )

    try:
        user_mods_roots = tuple(path.resolve() for path in paths.user_mods_dirs(root))
    except OSError:
        user_mods_roots = (root / "mods",)

    mods: list[LoadedMod] = []
    for mod in found.values():
        enabled = mod.enabled
        try:
            mod_path = mod.path.resolve()
        except OSError:
            mod_path = mod.path
        if mod.manifest.kind == "feature":
            in_user_mods = any(path_within(base, mod_path) for base in user_mods_roots)
            # 随安装包投放的官方扩展自带 `.trusted` 标记：逐包授权，与全局开关并存。
            trusted = in_user_mods and trust.is_trusted(mod.path)
            if not ((allow_feature_mods or trusted) and in_user_mods):
                diagnostics.append(f"{mod.manifest.id}: feature mods disabled")
                enabled = False
        mods.append(LoadedMod(manifest=mod.manifest, enabled=enabled, path=mod.path))
    mods.sort(key=lambda mod: (mod.manifest.id, str(mod.path)))

    contents: list[ContentEntry] = []
    for mod in mods:
        if not mod.enabled:
            continue
        try:
            entries, problems = _extract_contents(mod)
        except Exception as exc:
            diagnostics.append(f"{mod.manifest.id}: {type(exc).__name__}: {exc}")
            continue
        contents.extend(entries)
        diagnostics.extend(f"{mod.manifest.id}: {problem}" for problem in problems)
    contents.sort(key=lambda entry: (entry.kind, entry.id, entry.owner, str(entry.path)))

    if diagnostics:
        _logger.info("mod loading produced %d diagnostic(s)", len(diagnostics))

    return LoadResult(
        mods=tuple(mods),
        contents=tuple(contents),
        diagnostics=tuple(diagnostics),
    )
