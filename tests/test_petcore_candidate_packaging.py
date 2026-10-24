"""T08：候选打包入口的契约（隔离输出、可指定解释器、不删未知目录）。

PowerShell 构建真正跑起来要 PyInstaller + Inno；这里用脚本文本锁定参数语义，
真实构建与签名结果写在交付报告里，不由单测冒充。
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_petcore.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_build_script_exposes_isolated_output_and_python_path():
    text = _text()

    assert "[string]$OutputRoot" in text
    assert "[string]$PythonPath" in text
    assert "$distRoot = if ($OutputRoot)" in text


def test_build_script_wires_dist_work_and_spec_paths():
    text = _text()

    for flag in ('"--distpath", $distRoot', '"--workpath", $workRoot', '"--specpath", $specRoot'):
        assert flag in text, flag
    assert "dsh-pet-core/dsh-pet-core.exe" in text
    assert 'Join-Path $distRoot "check.json"' in text


def test_installer_output_and_source_follow_the_output_root():
    text = _text()

    assert '"/DMySourceDist=$distRoot\\dsh-pet-core"' in text
    assert '"/DMyOutputDir=$distRoot"' in text
    assert 'Join-Path $distRoot "dsh-pet-core-setup.exe"' in text


def test_installer_script_accepts_source_and_output_overrides():
    iss = (Path(__file__).resolve().parents[1] / "packaging" / "petcore.iss").read_text(
        encoding="utf-8"
    )

    assert "#ifndef MySourceDist" in iss
    assert "#define MySourceDist" in iss
    assert "#ifndef MyOutputDir" in iss
    assert "OutputDir={#MyOutputDir}" in iss
    assert 'Source: "{#MySourceDist}\\*"' in iss


def test_output_root_guards_against_root_and_existing_installer():
    text = _text()

    assert "OutputRoot must not be the repository root" in text
    assert "OutputRoot already contains an installer" in text


def test_clean_switch_never_deletes_directories():
    text = _text()

    assert '"--clean"' in text
    for destructive in ("Remove-Item", "rd /s", "rmdir /s"):
        assert destructive not in text, destructive
