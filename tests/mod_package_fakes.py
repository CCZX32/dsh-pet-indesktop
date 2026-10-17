# -*- coding: utf-8 -*-
"""完整资源包测试夹具：资源硬门的严格清单需要这些字段，避免各文件各写一份。"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def resource_manifest(
    character_id: str = "demo",
    *,
    version: str = "1.0.0",
    name: str | None = None,
    description: str = "",
    extra: dict | None = None,
) -> dict:
    data = {
        "id": character_id,
        "name": name or character_id.title(),
        "description": description,
        "version": version,
        "kind": "content",
        "api_version": "1",
        "core_requires": ">=4.2.5,<6.0.0",
        "platforms": ["windows", "macos", "linux"],
        "dependencies": [],
        "capabilities": ["character", "animation"],
        "entrypoint": None,
        "content": {"characters": [character_id]},
        "integrity": {"sha256": None, "signature": None},
    }
    data.update(extra or {})
    return data


def write_package(
    root: Path,
    *,
    character_id: str = "demo",
    version: str = "1.0.0",
    name: str | None = None,
    description: str = "",
    extra: dict | None = None,
    video: bytes = b"test-video",
    directory: str = "package",
) -> Path:
    package = root / directory
    videos = package / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    (videos / "idle.webm").write_bytes(video)
    manifest = resource_manifest(character_id, version=version, name=name, description=description, extra=extra)
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return package


def zip_package(source: Path, target: Path) -> Path:
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return target
