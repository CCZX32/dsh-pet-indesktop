# -*- coding: utf-8 -*-
"""构建门：官方功能包在冻结产物里必须真的能过装前预检。

2026-10-18 实测：`pet.mod_api` 只被功能包 host 导入，Core 没有静态引用，
PyInstaller 漏收后 `--feature-package-probe` 对所有官方包统一 `import_failed`，
Setup 回执/MOD 中心的安装全部被拒。这里锁两件事：

1. 构建脚本显式 hidden-import 公共 MOD API；
2. 构建脚本在复制 features 后，用**构建产物 exe** 逐包跑一次 probe 门。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_onedir.ps1"
VERIFIER = ROOT / "scripts" / "verify_frozen_mod_api.py"


def _build_text() -> str:
    return BUILD.read_text(encoding="utf-8-sig")


def test_the_bundle_hidden_imports_the_public_mod_api():
    text = _build_text()
    assert "'--hidden-import', 'pet.mod_api'" in text
    assert "'--hidden-import', 'pet.mod_api.v1'" in text


def test_the_build_runs_the_frozen_probe_over_bundled_packages():
    text = _build_text()
    assert "verify_frozen_mod_api.py" in text
    assert "--features $featuresDir" in text
    assert "frozen probe rejected a bundled package" in text


def test_the_frozen_probe_verifier_exists_and_pins_the_exit_code_contract():
    text = VERIFIER.read_text(encoding="utf-8")
    assert "return 1" in text
    assert "probe rejected" in text
    assert '"ai-chat"' in text and '"screen-understanding"' in text
