# -*- coding: utf-8 -*-
"""把仓库里的官方识屏包源码树打成可安装功能包（目录 + 同名 ZIP）。

与 ``build_mod_example`` 的三处差异（都是官方包的形态决定的）：

* 源码树是 ``mod.json`` + ``host/`` + ``common/`` + ``worker-src/``：``common/``
  是宿主代码的一部分（验签链对 ``host/`` 与 ``common/`` 的 ``.py`` 都抓字节）；
* Worker 是**源码态入口脚本**（``worker-src/`` → ``worker/``），不是冻结 exe——
  子进程引导靠 ``DSH_PET_CORE_ROOT`` 自举（见 ``worker-src/entry.py``）；
* 自检用官方验签策略（``official_package_verifier``：能力上限 = 官方登记闭集），
  本地包的 ``build_example`` 自检链装不了它（能力上限不同）。

冻结打包（随发行版携带预构建包）属剩余面，本脚本只覆盖源码态。
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
from pet.official_features import OFFICIAL_FEATURES  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "features" / "screen-understanding"
OWNER = "official.screen-understanding"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(source: Path, output: Path, *, worker_exe: Path | None = None) -> Path:
    """组装官方识屏包：host/ + common/ + worker-src/→worker/ + manifest.json + ZIP.

    ``worker_exe`` 非 None 时把冻结 Worker 复制为 ``worker/entry.exe``（POSIX 为
    ``worker/entry``）并作为清单里的 ``worker.path``；不传则保持源码态
    ``worker/entry.py``。
    """
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix(".zip").exists():
        raise ValueError(f"package output exists: {output}")
    mod = json.loads((source / "mod.json").read_text("utf-8-sig"))
    if mod.get("id") != OWNER or mod.get("execution_kind") != "host-worker":
        raise ValueError("mod.json 不是官方识屏包（id/execution_kind 不符）")
    output.mkdir(parents=True)
    files: dict[str, dict] = {}

    def copy_tree(root: Path, prefix: str, *, python_only: bool = True) -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if python_only and path.suffix != ".py":
                continue
            relative = prefix + "/" + path.relative_to(root).as_posix()
            data = path.read_bytes()
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[relative] = {"sha256": _digest(data), "size": len(data)}

    copy_tree(source / "host", "host")
    copy_tree(source / "common", "common")
    copy_tree(source / "worker-src", "worker")
    worker_path = "worker/entry.py"
    if worker_exe is not None:
        frozen = Path(worker_exe).resolve(strict=True)
        if not frozen.is_file():
            raise ValueError(f"worker executable is not a file: {worker_exe}")
        name = "entry.exe" if sys.platform == "win32" else "entry"
        target = output / "worker" / name
        data = frozen.read_bytes()
        target.write_bytes(data)
        files[f"worker/{name}"] = {"sha256": _digest(data), "size": len(data)}
        worker_path = f"worker/{name}"
    manifest = {
        "format_version": 2,
        "key_id": "local-user",
        "id": OWNER,
        "name": mod.get("name", "识屏"),
        "description": mod.get("description", ""),
        "version": str(mod["version"]),
        "api_version": API_VERSION,
        "core_requires": f">={__version__},<6.0.0",
        "platforms": [sys.platform],
        "capabilities": sorted(OFFICIAL_FEATURES[OWNER].capabilities),
        "factory": "screen-understanding/v1",
        "execution_kind": "host-worker",
        "worker": {"path": worker_path, "args": []},
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
    parser = argparse.ArgumentParser(description="打包官方识屏功能包（源码态）")
    parser.add_argument("output", type=Path, help="输出目录（同名 ZIP 一并产出）")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--worker-exe", type=Path, default=None, help="冻结 Worker 可执行文件（4B-5）")
    args = parser.parse_args(argv)
    try:
        result = build_package(args.source, args.output, worker_exe=args.worker_exe)
    except (ValueError, OSError) as error:
        print(f"打不了包：{error}", file=sys.stderr)
        return 2
    print(f"created: {result}\nZIP: {result.with_suffix('.zip')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
