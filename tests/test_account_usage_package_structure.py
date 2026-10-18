# -*- coding: utf-8 -*-
"""账户用量包的结构守卫：host-only、目录名与 owner 后缀一致、不碰内置业务模块。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "features" / "account-usage"
OWNER = "official.account-usage"


def test_mod_json_declares_the_host_only_contract():
    mod = json.loads((PACKAGE / "mod.json").read_text("utf-8-sig"))
    assert mod["id"] == OWNER
    assert mod["execution_kind"] == "host-only"
    assert mod["factory"] == "account-usage/v1"
    assert mod["version"] == "1.0.0"
    assert mod["name"] and mod["description"]


def test_package_directory_matches_the_owner_suffix():
    assert PACKAGE.name == OWNER.rsplit(".", 1)[-1]
    assert (PACKAGE / "host" / "factory.py").is_file()
    assert not (PACKAGE / "worker-src").exists()
    assert not (PACKAGE / "common").exists()


def test_host_face_has_every_module_the_manifest_factory_reaches():
    host = PACKAGE / "host"
    for name in ("__init__.py", "factory.py", "contributions.py", "contribution_settings.py", "runtime_mount.py", "config.py", "balance.py"):
        assert (host / name).is_file(), name


def test_package_never_imports_core_business_modules():
    forbidden = ("pet.balance", "pet.chat", "pet.app", "pet.dynamic_island", "pet.config")
    for path in (PACKAGE / "host").rglob("*.py"):
        text = path.read_text("utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} imports {needle}"
