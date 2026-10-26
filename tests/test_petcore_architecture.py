"""结构守卫：分层、零 Qt 边界、联网库出口与 mod 端口纪律。

**为什么用 AST 而不是 grep**：字符串扫描既漏（换行/别名/相对 import）又误报
（注释里提到库名）。历史版本只收绝对 import，而本仓库 94% 的 import 是相对形式
（`from ..ui import x`），于是「engine 不许碰 ui」这类断言永远绿（审计 AUD-36）。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "petcore"
EXAMPLES = ROOT / "examples" / "petcore-mods"

QT_ROOTS = ("PySide6", "PyQt5", "PyQt6", "shiboken6")
NETWORK_ROOTS = {"urllib", "http", "socket", "requests", "aiohttp", "httpx"}


def _modules() -> list[Path]:
    return sorted(path for path in PKG.rglob("*.py") if "__pycache__" not in path.parts)


def _absolute(name: str, level: int, path: Path) -> str:
    """把相对 import 还原成绝对名；不在 `petcore/` 下的（如示例 mod）返回空串。"""
    if not level:
        return name
    try:
        parts = list(path.relative_to(PKG).with_suffix("").parts)
    except ValueError:
        # 示例 mod 的相对 import 指向它自己的包，与 core 边界无关。
        return ""
    package = parts[:-1]
    drop = level - 1
    if drop:
        package = package[:-drop] if drop <= len(package) else []
    return ".".join(["petcore", *package, name]) if name else ".".join(["petcore", *package])


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(_absolute(node.module or "", int(node.level or 0), path))
    return {name for name in names if name}


def _area_files(area: str) -> list[Path]:
    return sorted((PKG / area).rglob("*.py"))


# ---------------------------------------------------------------- 零 Qt 边界


def test_engine_is_qt_free() -> None:
    for path in _area_files("engine"):
        imports = _imports(path)
        assert not any(name.startswith(QT_ROOTS) for name in imports), f"{path} must stay Qt-free: {imports}"


def test_island_speech_chat_are_qt_free() -> None:
    """岛的判定、语音服务、会话存储都要能在无 GUI 的 worker 里用。"""
    for area in ("island", "speech", "chat"):
        for path in _area_files(area):
            imports = _imports(path)
            assert not any(name.startswith(QT_ROOTS) for name in imports), f"{path} must stay Qt-free: {imports}"


def test_platform_probes_are_qt_free() -> None:
    """探针（GPU/FPS/系统/网络/前台抓样）零 Qt：只在 ui 侧接线。

    `screenshot/screens/win/hotkeys/session/image_hash` 属于文档明确的 core Qt 侧
    （抓屏、DPI、热键、会话），不在此规则内。
    """
    probes = (
        "gpu.py",
        "gpu_monitor.py",
        "fps.py",
        "fps_permission.py",
        "sysmon.py",
        "netmon.py",
        "sampling.py",
        "foreground.py",
    )
    for name in probes:
        path = PKG / "platform" / name
        assert path.is_file(), name
        imports = _imports(path)
        assert not any(item.startswith(QT_ROOTS) for item in imports), f"{name} must stay Qt-free: {imports}"


# ---------------------------------------------------------------- 分层


def test_engine_only_depends_on_stdlib_and_contracts() -> None:
    """engine 是纯逻辑层：只能依赖标准库与契约，不许反向依赖任何业务/UI 层。"""
    allowed_prefixes = ("petcore.engine", "petcore.contracts")
    offenders: list[str] = []
    for path in _area_files("engine"):
        for name in _imports(path):
            if not name.startswith("petcore"):
                continue
            if any(name == prefix or name.startswith(prefix + ".") for prefix in allowed_prefixes):
                continue
            offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {name}")
    assert not offenders, offenders


def test_contracts_are_stdlib_plus_contracts() -> None:
    """contracts 是 mod 面向的公共面：只用标准库与自身，绝不依赖 engine/ui。"""
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
    for path in _area_files("contracts"):
        for name in _imports(path):
            if name == "petcore" or name.startswith("petcore.contracts"):
                continue
            root = name.split(".")[0]
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
    """联网库只允许出现在 core 的统一出口包里。"""
    allowed = ("net/", "api/", "account/")
    offenders: list[str] = []
    for path in _modules():
        relative = path.relative_to(PKG).as_posix()
        if relative.startswith(allowed):
            continue
        for name in _imports(path):
            if name.split(".")[0] in NETWORK_ROOTS:
                offenders.append(f"{relative} -> {name}")
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


# ---------------------------------------------------------------- mod 端口纪律


def test_mods_use_ports_not_core_transport() -> None:
    """扩展（内置 + 示例）只能拿端口：不许 import core 的联网/UI/平台实现。"""
    blocked = (
        "petcore.net",
        "petcore.api",
        "petcore.account",
        "petcore.platform",
    )
    offenders: list[str] = []
    for root in (PKG / "builtin", EXAMPLES):
        assert root.is_dir(), root
        for path in sorted(root.rglob("*.py")):
            for name in _imports(path):
                if name == "petcore.ui" or name.startswith("petcore.ui."):
                    # 受信 UI 是设置页（`settings_page.py` 与内嵌在 factory 里的设置类）；
                    # 运行时代码（runtime/tailer/protocol…）一律不许直接 import ui。
                    if path.name == "settings_page.py" or name.startswith("petcore.ui.settings"):
                        continue
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {name}")
                    continue
                if any(name == item or name.startswith(item + ".") for item in blocked):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {name}")
    assert not offenders, offenders
