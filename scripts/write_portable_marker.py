# -*- coding: utf-8 -*-
"""把 canonical ``portable.json`` 写进便携 zip（或目录）。

构建脚本 ``scripts/build_onedir.ps1`` 在 ``Compress-Archive`` 之后调用本脚本，
让 924MB 的绿色包不必为了一个 48 字节的标记先落盘再压缩：zip 里已有的条目
原样保留，只在根目录追加标记。

用法::

    python scripts/write_portable_marker.py --zip dist-onedir/x-portable.zip
    python scripts/write_portable_marker.py --dir dist-onedir/x

标记内容唯一来源是 :func:`pet.runtime_layout.canonical_marker_text`，写入端与
读取端不会漂移。目标已有同名条目时：内容相同视为幂等成功，不同则报错退出
（静默覆盖会把旧包的标记语义改掉，构建应当先重打 zip）。
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.runtime_layout import PORTABLE_MARKER, canonical_marker_text  # noqa: E402


def _write_dir(directory: Path) -> int:
    if not directory.is_dir():
        print(f"not a directory: {directory}", file=sys.stderr)
        return 2
    marker = directory / PORTABLE_MARKER
    marker.write_text(canonical_marker_text() + "\n", encoding="utf-8")
    print(f"wrote {marker}")
    return 0


def _write_zip(archive_path: Path) -> int:
    if not archive_path.is_file():
        print(f"not a zip file: {archive_path}", file=sys.stderr)
        return 2
    text = canonical_marker_text() + "\n"
    with zipfile.ZipFile(archive_path, "a") as archive:
        if PORTABLE_MARKER in archive.namelist():
            existing = archive.read(PORTABLE_MARKER).decode("utf-8", errors="replace")
            if existing == text:
                print(f"{archive_path}: {PORTABLE_MARKER} already canonical")
                return 0
            print(
                f"{archive_path}: {PORTABLE_MARKER} exists with different content; "
                "rebuild the zip instead of overwriting it",
                file=sys.stderr,
            )
            return 3
        archive.writestr(PORTABLE_MARKER, text)
    print(f"{archive_path}: wrote {PORTABLE_MARKER}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--zip", type=Path, help="portable zip to append the marker to")
    target.add_argument("--dir", type=Path, help="already-unpacked app directory")
    args = parser.parse_args(argv)
    if args.zip is not None:
        return _write_zip(args.zip)
    return _write_dir(args.dir)


if __name__ == "__main__":
    raise SystemExit(main())
