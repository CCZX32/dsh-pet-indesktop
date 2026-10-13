# -*- coding: utf-8 -*-
"""D3 材料：把仓库里的示例功能包复制成一份**可改**的源码树再打包。

不是替身包：改的只有 ``mod.json`` 的 id/version/name 与 ``host/factory.py`` 里那一行
``OWNER``，打包走 ``scripts.build_mod_example.build_example``——真 manifest、真
SHA-256 清单、真 ZIP，所以路由/验签/指纹/事务全链真跑。

``rearchive(built)`` 是给"打包后动过字节"的用例用的：重新按当前目录生成 ZIP，好让
清单里的摘要与压缩包里的字节真的对不上（而不是只改目录）。
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mods" / "hello-local"
DEFAULT_OWNER = "demo.hello-local"
_FACTORY_OWNER_LINE = 'OWNER = "demo.hello-local"'


def source_tree(destination: Path | str, *, owner: str = DEFAULT_OWNER, version: str = "1.0.0", name: str | None = None) -> Path:
    """示例包的源码树副本（``mod.json`` + ``host/``），owner/版本可改。"""
    tree = Path(destination)
    shutil.copytree(EXAMPLE, tree)
    path = tree / "mod.json"
    values = json.loads(path.read_text("utf-8"))
    values["id"] = owner
    values["version"] = version
    if name is not None:
        values["name"] = name
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", "utf-8")
    factory = tree / "host" / "factory.py"
    factory.write_text(factory.read_text("utf-8").replace(_FACTORY_OWNER_LINE, f'OWNER = "{owner}"'), "utf-8")
    return tree


def build_tree(tree: Path | str, output: Path | str) -> tuple[Path, Path]:
    """返回 ``(构建目录, ZIP)``——两个都是 ``scripts.build_mod_example`` 的真产物。"""
    from scripts.build_mod_example import build_example

    built = build_example(Path(tree), Path(output))
    return built, built.with_suffix(".zip")


def build(destination: Path | str, **kwargs) -> tuple[Path, Path]:
    """``source_tree`` + ``build_tree`` 的合并形态（多数用例只要这一句）。"""
    destination = Path(destination)
    return build_tree(source_tree(destination / "src", **kwargs), destination / "built")


def rearchive(built: Path | str) -> Path:
    """按构建目录**当前**的字节重做 ZIP（动过 payload 之后再压缩，摘要才对不上）。"""
    built = Path(built)
    target = built.with_suffix(".zip")
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(built.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(built).as_posix())
    return target
