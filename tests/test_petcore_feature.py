from __future__ import annotations

import sys
from pathlib import Path

from petcore.contracts.host import HostPorts
from petcore.mods.feature import FeatureManager


class FakePresentation:
    def __init__(self):
        self.spoken: list[str] = []
        self.animations: list[str] = []

    def say(self, text: str, *, duration_ms: int = 4000) -> None:
        self.spoken.append(text)

    def play_animation(self, name: str) -> bool:
        self.animations.append(name)
        return True

    def notify(self, title: str, message: str) -> None:
        self.spoken.append(f"{title}:{message}")


def test_builtin_demo_exposes_menu_and_command() -> None:
    presentation = FakePresentation()
    manager = FeatureManager(HostPorts(presentation=presentation))
    diagnostics = manager.load_builtin_demo()
    assert diagnostics == []
    assert "core.feature-demo" in manager.features

    contributions = manager.menu_contributions()
    assert len(contributions) == 1
    owner, contribution = contributions[0]
    assert owner.owner == "core.feature-demo"
    assert contribution.kind == "menu"
    assert contribution.data["label"]

    command = manager.command("core.feature-demo", "hello")
    assert command is not None
    command()
    assert presentation.spoken
    manager.stop()
    assert manager.features == {}


def test_bad_entrypoint_is_a_diagnostic(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "factory.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    manager = FeatureManager(HostPorts())
    diagnostics = manager.load(pack=pack, owner="bad", entrypoint="factory.py:create_host")
    assert diagnostics
    assert "bad" not in manager.features


def test_package_entrypoint_resolves_relative_imports(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    host = pack / "host"
    host.mkdir(parents=True)
    (host / "runtime.py").write_text("VALUE = 7\n", encoding="utf-8")
    (host / "__init__.py").write_text(
        "from petcore.contracts.feature import FeatureDefinition\n"
        "from .runtime import VALUE\n"
        "\n"
        "\n"
        "def create_host(context):\n"
        "    return FeatureDefinition(owner=context.owner, metadata={'value': VALUE})\n",
        encoding="utf-8",
    )
    manager = FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=pack, owner="pkg-mod", entrypoint="host/__init__.py:create_host"
    )
    assert diagnostics == []
    assert "pkg-mod" in manager.features
    assert manager.features["pkg-mod"].definition.metadata["value"] == 7


def test_failing_package_entrypoint_leaves_no_sys_modules_entry(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    host = pack / "host"
    host.mkdir(parents=True)
    (host / "runtime.py").write_text("VALUE = 7\n", encoding="utf-8")
    (host / "__init__.py").write_text(
        "from .runtime import VALUE\n"
        "\n"
        "raise RuntimeError('boom')\n"
        "\n"
        "\n"
        "def create_host(context):\n"
        "    del context, VALUE\n",
        encoding="utf-8",
    )
    manager = FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=pack, owner="bad-pkg", entrypoint="host/__init__.py:create_host"
    )
    assert diagnostics
    assert "RuntimeError" in diagnostics[0]
    assert "bad-pkg" not in manager.features
    module_name = "petcore_feature_bad_pkg"
    assert not [
        name
        for name in sys.modules
        if name == module_name or name.startswith(module_name + ".")
    ]
