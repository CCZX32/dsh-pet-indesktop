from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .character_pack import build_character_pack
from ..mods.install import install
from ..mods.manifest import is_valid_id


def _extract_character_zip(source: Path, destination: Path) -> Path:
    """Extract a local character ZIP without allowing path traversal or links."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"无法读取角色 ZIP：{exc}") from exc
    root = destination.resolve()
    with archive:
        for info in archive.infolist():
            name = str(info.filename or "")
            if not name:
                continue
            windows = PureWindowsPath(name)
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if windows.is_absolute() or windows.drive or name.startswith(("/", "\\")) or ".." in parts:
                raise ValueError(f"角色 ZIP 包含不安全路径：{name}")
            target = destination.joinpath(*parts)
            resolved = target.resolve()
            if root not in resolved.parents and resolved != root:
                raise ValueError(f"角色 ZIP 路径越界：{name}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"角色 ZIP 不允许符号链接：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
    # 常见导出格式把全部内容包在一个目录里；规范化到真正的角色根。
    if not (destination / "videos").is_dir() and not (destination / "manifest.json").is_file():
        children = [item for item in destination.iterdir() if item.is_dir()]
        if len(children) == 1:
            return children[0]
    return destination


def install_character_source(
    source: Path,
    root: Path,
    *,
    character_id: str | None = None,
    name: str | None = None,
) -> tuple[bool, str, str | None]:
    """Validate, build and atomically install a local character directory or ZIP.

    Existing character ids are never overwritten by settings import.  The
    generic mod installer keeps the same no-force boundary used by extensions.
    """
    source = Path(source)
    root = Path(root)
    requested = str(character_id or (source.stem if source.suffix.lower() == ".zip" else source.name)).strip()
    if not is_valid_id(f"character.{requested}"):
        return False, f"invalid character id: {requested!r}", None
    if not source.is_file() and not source.is_dir():
        return False, f"source does not exist: {source}", None

    import_root = root / ".character-import"
    import_root.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="character.", dir=str(import_root)))
    source_root = source
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            source_root = _extract_character_zip(source, temp_root / "source")
        elif not source.is_dir():
            return False, "角色导入仅支持目录或 ZIP 文件", None
        target = temp_root / f"character.{requested}"
        ok, message = build_character_pack(
            source_root, target, character_id=requested, name=name, link=False
        )
        if not ok:
            return False, message, None
        ok, message = install(target, root, force=False)
        return ok, message, f"character.{requested}" if ok else None
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return False, f"导入失败：{type(exc).__name__}: {exc}", None
    finally:
        try:
            shutil.rmtree(temp_root)
        except OSError:
            # The install is already committed or rejected; leave a precise
            # diagnostic rather than deleting an unrelated user directory.
            pass
        try:
            import_root.rmdir()
        except OSError:
            pass
