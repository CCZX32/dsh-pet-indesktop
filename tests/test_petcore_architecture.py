from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "petcore"


def _modules() -> list[Path]:
    return sorted(path for path in PKG.rglob("*.py") if "__pycache__" not in path.parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_engine_is_qt_free() -> None:
    for path in (PKG / "engine").rglob("*.py"):
        imports = _imports(path)
        assert not any(
            name.startswith(("PySide6", "PyQt5", "PyQt6", "shiboken6")) for name in imports
        ), f"{path} must stay Qt-free: {imports}"


def test_contracts_are_stdlib_only() -> None:
    allowed = {
        "dataclasses",
        "pathlib",
        "typing",
        "enum",
        "json",
        "collections",
        "abc",
        "__future__",
    }
    for path in (PKG / "contracts").rglob("*.py"):
        for name in _imports(path):
            root = name.split(".")[0]
            if root in {"petcore"} or name.startswith(".."):
                continue
            assert root in allowed, f"{path} imports {name}"


def test_pet_import_is_confined_to_media_and_legacy() -> None:
    offenders: list[str] = []
    for path in _modules():
        for name in _imports(path):
            if name == "pet" or name.startswith("pet."):
                relative = path.relative_to(PKG).as_posix()
                if relative.startswith("media/") or relative == "content/legacy.py":
                    continue
                offenders.append(f"{relative} -> {name}")
    assert not offenders, offenders


def test_no_network_stack_in_core() -> None:
    """联网库只允许出现在 core 的统一出口包里。

    `net/` 是唯一 HTTP 实现，`api/` 负责探测（要构造 Request/读 HTTPError），
    `account/` 预留给账户与额度。其余模块（尤其 `engine/`、`ui/`、`mods/`）
    一律不得直接 import 网络库。
    """
    forbidden = {"urllib", "http", "socket", "requests", "aiohttp", "httpx"}
    allowed = ("net/", "api/", "account/")
    offenders: list[str] = []
    for path in _modules():
        relative = path.relative_to(PKG).as_posix()
        if relative.startswith(allowed):
            continue
        for name in _imports(path):
            if name.split(".")[0] in forbidden:
                offenders.append(f"{relative} -> {name}")
    assert not offenders, offenders


def test_mods_do_not_import_core_network_or_api() -> None:
    """mod 只能拿 HostPorts，不许绕过端口直接 import core 的联网/API 实现。"""
    roots = [PKG / "builtin", ROOT / "examples" / "petcore-mods"]
    blocked = ("petcore.net", "petcore.api", "petcore.account")
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            for name in _imports(path):
                if any(name == item or name.startswith(item + ".") for item in blocked):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {name}")
    assert not offenders, offenders


def test_engine_public_modules_exist() -> None:
    for name in (
        "enums.py",
        "geometry.py",
        "catalog.py",
        "animation.py",
        "behavior.py",
        "motion.py",
        "pet_state.py",
    ):
        assert (PKG / "engine" / name).exists()
