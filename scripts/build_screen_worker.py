# -*- coding: utf-8 -*-
"""把官方识屏包的 Worker 入口冻成一个独立 exe（4B-5 真实构建片）。

源码态的包内 Worker 是 ``worker/entry.py``（靠 ``DSH_PET_CORE_ROOT`` 自举）；冻结
产品里没有可用的 Python 解释器，``pet.plugins.worker_launch.worker_command`` 在
``sys.frozen`` 下把 ``worker.path`` 当**可执行文件**起，所以包必须携带一个真 exe。

本脚本只产出一个单文件 exe；包清单里的 ``worker.path`` / ``files`` 由
``build_screen_package.py --worker-exe`` 更新（摘要/大小一并重算）。

用法：
    python scripts/build_screen_worker.py <输出目录>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "features" / "screen-understanding" / "worker-src" / "entry.py"

#: Worker 在运行期才 import 的 Core 模块（PyInstaller 的静态分析对惰性 import 不可靠）。
HIDDEN_IMPORTS = (
    "pet.workers.lease_bootstrap",
    "pet.workers.proactive_screen_worker",
    "pet.workers.protocol",
    "pet.vision",
    "pet.http_compat",
    "pet.image_hash",
    "pet.workers.worker_diagnostics",
)


def build_worker(output: Path) -> Path:
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "build"
    spec = output / "spec"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "entry",
        "--distpath",
        str(output),
        "--workpath",
        str(work),
        "--specpath",
        str(spec),
        "--paths",
        str(ROOT),
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "shiboken6",
    ]
    for module in HIDDEN_IMPORTS:
        command.extend(["--hidden-import", module])
    command.append(str(ENTRY))
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller worker build failed: {result.returncode}")
    exe = output / ("entry.exe" if sys.platform == "win32" else "entry")
    if not exe.is_file():
        raise SystemExit(f"worker executable missing after build: {exe}")
    return exe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冻结官方识屏包的 Worker 入口")
    parser.add_argument("output", type=Path, help="输出目录（产出 entry / entry.exe）")
    args = parser.parse_args(argv)
    exe = build_worker(args.output)
    print(f"worker: {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
