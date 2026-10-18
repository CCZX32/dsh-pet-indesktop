# -*- coding: utf-8 -*-
"""把仓库里的官方账户用量包源码树打成可安装功能包（目录 + 同名 ZIP）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import __version__  # noqa: E402
from pet.feature_policy import API_VERSION, official_package_verifier  # noqa: E402
from pet.feature_state_io import safe_path  # noqa: E402
from pet.official_features import ACCOUNT_USAGE_FEATURE_ID, OFFICIAL_FEATURES, official_feature  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "features" / "account-usage"
OWNER = ACCOUNT_USAGE_FEATURE_ID


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(source: Path, output: Path) -> Path:
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix(".zip").exists():
        raise ValueError(f"package output exists: {output}")
    mod = json.loads((source / "mod.json").read_text("utf-8-sig"))
    registration = official_feature(OWNER)
    if mod.get("id") != OWNER or mod.get("execution_kind") != registration.execution_kind:
        raise ValueError("mod.json 不是官方账户用量包（id/execution_kind 不符）")
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
        "id": OWNER,
        "name": mod.get("name", "账户用量"),
        "description": mod.get("description", ""),
        "version": str(mod["version"]),
        "api_version": API_VERSION,
        "core_requires": f">={__version__},<6.0.0",
        "platforms": [sys.platform],
        "capabilities": sorted(OFFICIAL_FEATURES[OWNER].capabilities),
        "factory": registration.factory,
        "execution_kind": registration.execution_kind,
        # host-only 的清单必须带 worker 键，值恒为 null。
        "worker": None,
        "files": files,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", "utf-8")
    official_package_verifier(OWNER).verify(output)
    with zipfile.ZipFile(output.with_suffix(".zip"), "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包官方账户用量功能包（源码态）")
    parser.add_argument("output", type=Path, help="输出目录（同名 ZIP 一并产出）")
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args(argv)
    try:
        result = build_package(args.source, args.output)
    except (ValueError, OSError) as error:
        print(f"打不了包：{error}", file=sys.stderr)
        return 2
    print(f"created: {result}\nZIP: {result.with_suffix('.zip')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
