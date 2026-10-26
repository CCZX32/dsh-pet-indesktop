"""扩展重载与卸载的卫生（审计 AUD-14 / AUD-21 / AUD-22）。"""

from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

from petcore.mods.feature import FeatureManager, import_entrypoint


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def _write_mod(root: Path, owner: str = "demo.owner") -> Path:
    pack = root / owner
    (pack / "host").mkdir(parents=True)
    (pack / "mod.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": owner,
                "kind": "feature",
                "name": owner,
                "version": "1.0.0",
                "entrypoint": "host/__init__.py:create_host",
            }
        ),
        encoding="utf-8",
    )
    return pack


def test_reimport_reads_new_submodule_code(tmp_path: Path) -> None:
    pack = _write_mod(tmp_path)
    (pack / "host" / "__init__.py").write_text(
        "from .runtime import VERSION\n\ndef create_host(ctx=None):\n    return VERSION\n",
        encoding="utf-8",
    )
    (pack / "host" / "runtime.py").write_text("VERSION = 'v1'\n", encoding="utf-8")
    assert import_entrypoint(pack, "host/__init__.py:create_host", "demo.owner")() == "v1"

    # 换成不同长度的内容：同秒同长度的重写会命中 `.pyc` 的 mtime+size 校验。
    (pack / "host" / "runtime.py").write_text("VERSION = 'v2-updated'\n", encoding="utf-8")
    # 没有清 sys.modules 时这里仍是 v1——正是 AUD-14 的现场。
    assert import_entrypoint(pack, "host/__init__.py:create_host", "demo.owner")() == "v1"

    from petcore.ui.app import CoreHost

    CoreHost._drop_modules_under(pack)  # noqa: SLF001 - 卸载/重载复用的清理入口
    assert import_entrypoint(pack, "host/__init__.py:create_host", "demo.owner")() == "v2-updated"


def test_drop_modules_only_touches_the_given_tree(tmp_path: Path) -> None:
    from petcore.ui.app import CoreHost

    pack = tmp_path / "mods" / "demo"
    pack.mkdir(parents=True)
    inside = types.ModuleType("demo_inside")
    inside.__file__ = str(pack / "host" / "runtime.py")
    outside = types.ModuleType("demo_outside")
    outside.__file__ = str(tmp_path / "other" / "runtime.py")
    sys.modules["demo_inside"] = inside
    sys.modules["demo_outside"] = outside
    try:
        CoreHost._drop_modules_under(pack)  # noqa: SLF001
        assert "demo_inside" not in sys.modules
        assert "demo_outside" in sys.modules
    finally:
        sys.modules.pop("demo_inside", None)
        sys.modules.pop("demo_outside", None)


def test_system_exit_in_a_mod_becomes_a_diagnostic(tmp_path: Path) -> None:
    pack = _write_mod(tmp_path, "evil.exit")
    (pack / "host" / "__init__.py").write_text(
        "import sys\n\nsys.exit(3)\n", encoding="utf-8"
    )
    manager = FeatureManager(object())
    diagnostics = manager.load(
        pack=pack, owner="evil.exit", entrypoint="host/__init__.py:create_host", config={}
    )
    assert diagnostics and "SystemExit" in diagnostics[0]
    assert manager.features == {}


def test_keyboard_interrupt_still_propagates(tmp_path: Path) -> None:
    pack = _write_mod(tmp_path, "intr")
    (pack / "host" / "__init__.py").write_text(
        "raise KeyboardInterrupt()\n", encoding="utf-8"
    )
    manager = FeatureManager(object())
    with pytest.raises(KeyboardInterrupt):
        manager.load(pack=pack, owner="intr", entrypoint="host/__init__.py:create_host", config={})


def test_scheduler_cancel_owner_stops_timers(app) -> None:
    from petcore.ui.ports import QtScheduler

    scheduler = QtScheduler()
    fired: list[int] = []
    scheduler.call_every(10, lambda: fired.append(1), owner="demo")
    scheduler.call_every(10, lambda: fired.append(2), owner="other")
    app.processEvents()  # schedule 也走 QueuedConnection
    assert len(scheduler._bridge._timers) == 2  # noqa: SLF001
    scheduler.cancel_owner("demo")
    app.processEvents()  # stop 走 QueuedConnection：不泵事件不会生效
    assert len(scheduler._bridge._timers) == 1  # noqa: SLF001
    remaining = list(scheduler._bridge._timers)  # noqa: SLF001
    scheduler.cancel(remaining[0])
    app.processEvents()


def test_on_tick_returns_a_disposer(app) -> None:
    from petcore.ui.ports import InteractionAdapter

    adapter = InteractionAdapter(object())
    ticks: list[float] = []
    dispose = adapter.on_tick("demo", lambda dt: ticks.append(dt), 10)
    assert callable(dispose)
    dispose()
    app.processEvents()
    assert adapter._timers == {}  # noqa: SLF001
    assert not adapter._scheduler._bridge._timers  # noqa: SLF001


def test_zip_install_does_not_leave_a_trust_marker(tmp_path: Path) -> None:
    from petcore.mods.install import install

    root = tmp_path / "data"
    root.mkdir()
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            "mod.json",
            json.dumps(
                {
                    "schema": 1,
                    "id": "demo.feature",
                    "kind": "feature",
                    "name": "demo",
                    "version": "1.0.0",
                    "entrypoint": "host/__init__.py:create_host",
                }
            ),
        )
        handle.writestr("host/__init__.py", "def create_host(ctx=None):\n    return None\n")
        handle.writestr(".trusted", "")
    ok, message = install(archive, root)
    assert ok, message
    assert not (root / "mods" / "demo.feature" / ".trusted").exists()
