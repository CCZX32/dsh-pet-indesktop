# -*- coding: utf-8 -*-
"""5A Setup 选装结构：官方包 Task / Excludes / 首启回执在 .iss 里真的接线。

结构判据守住“脚本已接线”，避免以后有人把选装项删掉而没人发现；安装/卸载/
首启回执的真实验收由本机 Inno Setup 编译产物另行覆盖（见 PR 报告）。
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
    assert 'Name: "official_account_usage"' in text
    assert 'Name: "official_music"' in text
    assert 'Name: "official_voice_chime"' in text
    assert 'Name: "official_persona_phrases"' in text
    assert 'Name: "official_quick_launch"' in text
    assert text.count('GroupDescription: "Official feature packages:"') == 7
    assert "Flags: unchecked" in text


def test_the_base_files_entry_excludes_the_optional_packages():
    text = _text()
    base = next(line for line in text.splitlines() if line.startswith('Source: "{#MyAppDir}\\*"'))
    assert "features\\ai-chat\\*" in base
    assert "features\\screen-understanding\\*" in base
    assert "features\\account-usage\\*" in base
    assert "features\\music\\*" in base
    assert "features\\voice-chime\\*" in base
    assert "features\\persona-phrases\\*" in base
    assert "features\\quick-launch\\*" in base
    # 安装态绝不能继承便携标记：构建树里若残留 portable.json，装出来的应用会
    # 把数据写进安装目录而不是 %APPDATA%，用户与支持人员都看不出区别。
    assert "portable.json" in base


def test_each_optional_package_has_its_own_task_scoped_source():
    text = _text()
    assert 'DestDir: "{app}\\features\\ai-chat"; Tasks: official_ai_chat' in text
    assert 'DestDir: "{app}\\features\\screen-understanding"; Tasks: official_screen' in text
    assert 'DestDir: "{app}\\features\\account-usage"; Tasks: official_account_usage' in text
    assert 'DestDir: "{app}\\features\\music"; Tasks: official_music' in text
    assert 'DestDir: "{app}\\features\\voice-chime"; Tasks: official_voice_chime' in text
    assert 'DestDir: "{app}\\features\\persona-phrases"; Tasks: official_persona_phrases' in text
    assert 'DestDir: "{app}\\features\\quick-launch"; Tasks: official_quick_launch' in text
    assert text.count("skipifsourcedoesntexist") >= 7


def test_silent_installs_do_not_launch_the_app():
    text = _text()
    run_entry = next(line for line in text.splitlines() if line.startswith("Filename: \"{app}\\{#MyAppExeName}\""))
    assert "postinstall" in run_entry
    assert "skipifsilent" in run_entry


def test_unselected_tasks_leave_no_empty_feature_directories():
    text = _text()
    assert "RemoveDir(ExpandConstant('{app}\\features\\ai-chat'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\screen-understanding'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\account-usage'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\music'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\voice-chime'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\persona-phrases'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features\\quick-launch'))" in text
    assert "RemoveDir(ExpandConstant('{app}\\features'))" in text


def test_the_startup_receipt_is_removed_on_uninstall():
    text = _text()
    section = text.split("\n[UninstallDelete]", 1)[1].split("\n[Code]", 1)[0]
    assert 'Name: "{app}\\startup-receipt.json"' in section
    # 只删自有回执：不许恢复 `_MEI*` 这类按名字通配删除。
    assert "_MEI" not in section


def test_the_receipt_reports_what_is_actually_on_disk():
    """升级会保留上一版装下的包文件；回执不能只按本次勾选写 false。"""
    text = _text()
    assert "FileExists(ExpandConstant('{app}\\features\\ai-chat\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\screen-understanding\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\account-usage\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\music\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\voice-chime\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\persona-phrases\\manifest.json'))" in text
    assert "FileExists(ExpandConstant('{app}\\features\\quick-launch\\manifest.json'))" in text


def test_the_installer_writes_a_startup_receipt():
    text = _text()
    assert "procedure CurStepChanged(CurStep: TSetupStep)" in text
    assert "ssPostInstall" in text
    assert "startup-receipt.json" in text
    assert "dsh-pet-startup-receipt/v1" in text
    assert "WizardIsTaskSelected('official_ai_chat')" in text
    assert "WizardIsTaskSelected('official_screen')" in text
