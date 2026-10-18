# -*- coding: utf-8 -*-
"""把仓库里的官方日常台词包源码树打成可安装功能包（目录 + 同名 ZIP）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.official_features import PERSONA_PHRASES_FEATURE_ID  # noqa: E402
from scripts.build_host_package import build_host_package  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "features" / "persona-phrases"
OWNER = PERSONA_PHRASES_FEATURE_ID


def build_package(source: Path, output: Path) -> Path:
    return build_host_package(source, output, OWNER)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包官方日常台词功能包（源码态）")
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
