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


def _pwsh() -> str | None:
    import shutil

    return shutil.which("pwsh")


def test_dry_run_resolves_relative_output_root_under_the_repo() -> None:
    """相对路径必须相对仓库根解析（AUD-37）：`GetFullPath` 用的是进程 CWD。"""
    import subprocess
    from pathlib import Path

    pwsh = _pwsh()
    if pwsh is None:
        import pytest

        pytest.skip("pwsh 不可用")
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_petcore.ps1"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-DryRun", "-OutputRoot", "rel-candidate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    repo = str(Path(__file__).resolve().parents[1])
    dist_line = next(line for line in result.stdout.splitlines() if line.startswith("dist:"))
    assert "rel-candidate" in dist_line
    assert repo.lower() in dist_line.lower()


def test_dry_run_rejects_the_repository_root_even_with_a_trailing_separator() -> None:
    import subprocess
    from pathlib import Path

    pwsh = _pwsh()
    if pwsh is None:
        import pytest

        pytest.skip("pwsh 不可用")
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_petcore.ps1"
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-DryRun", "-OutputRoot", f"{repo}\\"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode != 0
    assert "must not be the repository root" in (result.stdout + result.stderr)


def test_smoke_consumes_check_json_and_requires_strict_mode() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "scripts" / "build_petcore.ps1").read_text(encoding="utf-8")
    assert "--check --strict" in text
    assert "ConvertFrom-Json" in text
    assert "menu_template" in text


def test_smoke_waits_for_the_windowed_exe() -> None:
    """``-Windowed`` 产物是 GUI 子系统：``& $exe`` 立刻返回，必须 Start-Process -Wait。

    实测（本机 2026-10-26）``& $exe --check --strict --out …`` 52ms 就返回、
    ``$LASTEXITCODE`` 为空、``check.json`` 尚未落盘，冒烟步骤随后抛「路径不存在」，
    整个构建在 dist 已生成的情况下失败。这条断言把「必须等待」钉在脚本里。
    """
    text = _text()
    assert "Start-Process -FilePath $exe" in text
    assert "-Wait -PassThru" in text
    assert "& $exe --check" not in text
