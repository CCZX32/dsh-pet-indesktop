# -*- coding: utf-8 -*-
"""通用 host-only 官方包构建器：源码树 ``mod.json`` + ``host/`` → 包目录 + ZIP。

后续官方包只需一行 ``build_host_package(SOURCE, output, OWNER)``，不再各抄一份
清单组装逻辑。验签仍走官方闭集策略（能力上限 = 该 owner 的登记）。
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import __version__  # noqa: E402
from pet.feature_policy import API_VERSION, official_package_verifier  # noqa: E402
from pet.feature_state_io import safe_path  # noqa: E402
from pet.official_features import OFFICIAL_FEATURES, official_feature  # noqa: E402


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_host_package(source: Path, output: Path, owner: str) -> Path:
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix(".zip").exists():
        raise ValueError(f"package output exists: {output}")
    mod = json.loads((source / "mod.json").read_text("utf-8-sig"))
    registration = official_feature(owner)
    if mod.get("id") != owner or mod.get("execution_kind") != registration.execution_kind:
        raise ValueError(f"mod.json 不是官方 host-only 包（{owner}）")
    output.mkdir(parents=True)
    files: dict[str, dict] = {}

    def copy_tree(root: Path, prefix: str) -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.name.startswith("."):
                continue
            relative = prefix + "/" + path.relative_to(root).as_posix()
            data = path.read_bytes()
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[relative] = {"sha256": _digest(data), "size": len(data)}

    copy_tree(source / "host", "host")
    manifest = {
        "format_version": 2,
        "key_id": "local-user",
        "id": owner,
        "name": mod.get("name", owner),
        "description": mod.get("description", ""),
        "version": str(mod["version"]),
        "api_version": API_VERSION,
        "core_requires": f">={__version__},<6.0.0",
        "platforms": [sys.platform],
        "capabilities": sorted(OFFICIAL_FEATURES[owner].capabilities),
        "factory": registration.factory,
        "execution_kind": registration.execution_kind,
        "worker": None,
        "files": files,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", "utf-8")
    official_package_verifier(owner).verify(output)
    with zipfile.ZipFile(output.with_suffix(".zip"), "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    return output
