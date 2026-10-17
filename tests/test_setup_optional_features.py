# -*- coding: utf-8 -*-
"""5A Setup 选装结构：官方包 Task / Excludes / 首启回执在 .iss 里真的接线。

本机没有 ISCC，无法编译安装包；这里用结构判据守住“脚本已接线”，避免把
“没编译”误读成“没做”，也避免以后有人把选装项删掉而没人发现。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "packaging" / "dsh-pet.iss"


def _text() -> str:
    return ISS.read_text(encoding="utf-8")


def test_the_installer_is_utf8_without_bom():
    raw = ISS.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "Inno 按 ANSI 读取，不能带 BOM"
    raw.decode("utf-8")


def test_official_packages_are_optional_tasks():
    text = _text()
    assert 'Name: "official_ai_chat"' in text
    assert 'Name: "official_screen"' in text
    assert text.count('GroupDescription: "Official feature packages:"') == 2
    assert "Flags: unchecked" in text


def test_the_base_files_entry_excludes_the_optional_packages():
    text = _text()
    base = next(line for line in text.splitlines() if line.startswith('Source: "{#MyAppDir}\\*"'))
    assert "features\\ai-chat\\*" in base
    assert "features\\screen-understanding\\*" in base


def test_each_optional_package_has_its_own_task_scoped_source():
    text = _text()
    assert 'DestDir: "{app}\\features\\ai-chat"; Tasks: official_ai_chat' in text
    assert 'DestDir: "{app}\\features\\screen-understanding"; Tasks: official_screen' in text
    assert text.count("skipifsourcedoesntexist") >= 2


def test_the_installer_writes_a_startup_receipt():
    text = _text()
    assert "procedure CurStepChanged(CurStep: TSetupStep)" in text
    assert "ssPostInstall" in text
    assert "startup-receipt.json" in text
    assert "dsh-pet-startup-receipt/v1" in text
    assert "IsTaskSelected('official_ai_chat')" in text
    assert "IsTaskSelected('official_screen')" in text
