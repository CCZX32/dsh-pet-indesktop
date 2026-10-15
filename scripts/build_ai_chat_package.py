# -*- coding: utf-8 -*-
"""把仓库里的官方 AI 对话包源码树打成可安装功能包（目录 + 同名 ZIP）。

与 ``build_screen_package`` 的关系：同一道门、同一套清单与验签，差异只有两处
（都是包形态决定的）：

* 源码树是 ``mod.json`` + ``host/``，**没有** ``common/`` 与 ``worker-src/``——
  聊天包是 ``host-only``（无独立 Worker，也不允许有），所以 manifest 里不带
  ``worker`` 段，执行位置恒为进程内；
* 自检仍用官方验签策略（``official_package_verifier``：能力上限 = 官方登记闭集）。

冻结打包（随发行版携带预构建包）与 Setup 选装属剩余面，本脚本只覆盖源码态。
"""

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
from pet.official_features import AI_FEATURE_ID, OFFICIAL_FEATURES  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "features" / "ai-chat"
OWNER = AI_FEATURE_ID


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(source: Path, output: Path) -> Path:
    """组装官方 AI 对话包：``host/`` + manifest.json + ZIP。

    ``host/`` 里的 ``.py`` 与 ``.qss`` 都进包（``legacy_styles.qss`` /
    ``modern_styles.qss`` 是聊天窗的样式表，缺了界面就散架），所以这里按
    "非 ``__pycache__``、非点文件"收，而不是像识屏包那样只收 ``.py``。
    """
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix(".zip").exists():
        raise ValueError(f"package output exists: {output}")
    mod = json.loads((source / "mod.json").read_text("utf-8-sig"))
    if mod.get("id") != OWNER or mod.get("execution_kind") != "host-only":
        raise ValueError("mod.json 不是官方 AI 对话包（id/execution_kind 不符）")
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
        "name": mod.get("name", "AI 对话"),
        "description": mod.get("description", ""),
        "version": str(mod["version"]),
        "api_version": API_VERSION,
        "core_requires": f">={__version__},<6.0.0",
        "platforms": [sys.platform],
        "capabilities": sorted(OFFICIAL_FEATURES[OWNER].capabilities),
        "factory": "ai-chat/v1",
        "execution_kind": "host-only",
        # host-only 的清单**必须**带 worker 键，值恒为 null（声明"我没有 Worker"）；
        # 少了这个键验签层直接判 ``invalid manifest fields``。
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
    parser = argparse.ArgumentParser(description="打包官方 AI 对话功能包（源码态）")
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
