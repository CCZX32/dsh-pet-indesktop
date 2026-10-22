from __future__ import annotations

import sys
from pathlib import Path

from petcore import paths
from petcore.mods.loader import load_mods


def _iss_text() -> str:
    return (Path(__file__).resolve().parent.parent / "packaging" / "petcore.iss").read_text(
        encoding="utf-8"
    )


def test_setup_carries_the_whale_icon() -> None:
    text = _iss_text()
    assert "SetupIconFile=..\\assets\\icon.ico" in text
    assert "UninstallDisplayIcon={app}\\dsh-pet-core.exe" in text


def test_setup_always_shows_the_directory_page_and_reuses_the_previous_path() -> None:
    text = _iss_text()
    assert "DisableDirPage=no" in text
    assert "UsePreviousAppDir=yes" in text
    assert "InstallLocation" in text
    assert "GetDefaultDir" in text
    assert "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" in text


def test_build_script_bundles_the_menu_templates() -> None:
    script = (Path(__file__).resolve().parent.parent / "scripts" / "build_petcore.ps1").read_text(
        encoding="utf-8"
    )
    assert "petcore/menu_templates;petcore/menu_templates" in script


def test_bundled_mods_install_under_the_app_directory() -> None:
    text = _iss_text()
    assert "{userappdata}" not in text
    assert text.count("{app}\\mods\\") >= 5
    for mod_id in (
        "fun.divination",
        "fun.festival",
        "reminder.todo",
        "voice.chime",
        "media.music",
        "ai.chat",
    ):
        assert f"{{app}}\\mods\\{mod_id}" in text


def test_official_feature_tasks_are_opt_in() -> None:
    """5 个官方扩展默认不勾选：不勾选就完全不写盘（用户口径）。"""
    lines = _iss_text().splitlines()
    task_lines = {
        mod_id: next(line for line in lines if f'Name: "mod_{suffix}"' in line)
        for mod_id, suffix in (
            ("fun.divination", "divination"),
            ("fun.festival", "festival"),
            ("reminder.todo", "todo"),
            ("voice.chime", "chime"),
            ("media.music", "music"),
            ("ai.chat", "aichat"),
        )
    }
    assert all("Flags: unchecked" in line for line in task_lines.values())


def test_install_mods_dir_is_only_used_when_frozen(tmp_path: Path, monkeypatch) -> None:
    assert paths.install_mods_dir() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "install" / "dsh-pet-core.exe"))
    assert paths.install_mods_dir() == tmp_path / "install" / "mods"
    dirs = paths.user_mods_dirs(tmp_path / "data")
    assert dirs == (tmp_path / "data" / "mods", tmp_path / "install" / "mods")
    assert tmp_path / "install" / "mods" in paths.mods_dirs(tmp_path / "data")


def test_trusted_install_mod_loads_without_the_global_switch(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    install = tmp_path / "install"
    monkeypatch.setattr(sys, "executable", str(install / "dsh-pet-core.exe"))
    pack = install / "mods" / "tool.bundled"
    pack.mkdir(parents=True)
    (pack / "mod.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "tool.bundled",
                "kind": "feature",
                "name": "Bundled tool",
                "name_zh": "随包工具",
                "version": "1.0.0",
                "api_version": "1",
                "execution": "host-only",
                "entrypoint": "host/factory.py:create_host",
            }
        ),
        encoding="utf-8",
    )
    (pack / ".trusted").write_text("", encoding="utf-8")

    root = tmp_path / "data"
    result = load_mods(root, allow_feature_mods=False)

    mod = next(item for item in result.mods if item.manifest.id == "tool.bundled")
    assert mod.enabled is True
    assert mod.manifest.name_zh == "随包工具"
