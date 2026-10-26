"""配置的扩展偏好区块与只读诊断（审计 AUD-07 / AUD-11 / AUD-12）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from petcore import paths
from petcore.config import DEFAULTS, Config, ScopedConfig


@pytest.fixture(autouse=True)
def _no_legacy_import(monkeypatch):
    """测试不读本机真实旧壳数据。"""
    monkeypatch.setattr(paths, "legacy_data_roots", lambda: ())


def test_unknown_key_round_trips_through_set_get(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    config.set("mymod.enabled", True)
    assert config.get("mymod.enabled") is True
    config.save()

    reloaded = Config.load(tmp_path)
    assert reloaded.get("mymod.enabled") is True
    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["extra"]["mymod.enabled"] is True


def test_top_level_keys_stay_within_defaults(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    config.set("mymod.enabled", True)
    config.save()
    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert set(payload) - {"extra"} <= set(DEFAULTS)


def test_scoped_config_writes_extension_keys_globally(tmp_path: Path) -> None:
    child_root = tmp_path / "child"
    child_root.mkdir()
    global_config = Config.load(tmp_path)
    child = Config.load(child_root, filename="config-pet-1.json")
    scoped = ScopedConfig(global_config, child)
    scoped.set("mymod.enabled", True)
    assert global_config.get("mymod.enabled") is True
    assert child.get("mymod.enabled") is None
    assert scoped.get("mymod.enabled") is True


def test_shared_runtime_keys_are_global(tmp_path: Path) -> None:
    """三个共享运行时键必须走全局，否则子宠设置页写了也没用（AUD-43）。"""
    child_root = tmp_path / "child"
    child_root.mkdir()
    global_config = Config.load(tmp_path)
    child = Config.load(child_root, filename="config-pet-1.json")
    scoped = ScopedConfig(global_config, child)
    for key in ("network_info_enabled", "memory_trim_enabled", "quiet_minutes_default"):
        scoped.set(key, False if key != "quiet_minutes_default" else 90)
        assert global_config.get(key) == (False if key != "quiet_minutes_default" else 90), key
        assert child.get(key) != (False if key != "quiet_minutes_default" else 90), key


@pytest.mark.parametrize(
    "key",
    ["BadKey", "…", "a" * 200, "", "mymod/x"],
)
def test_invalid_extra_keys_are_rejected(tmp_path: Path, key: str) -> None:
    config = Config.load(tmp_path)
    config.set(key, 1)
    assert config.get(key) is None


@pytest.mark.parametrize("value", ["sk-abcdefgh12345678", "Bearer abcdefgh12345678", "a" * 64])
def test_credential_like_values_are_rejected(tmp_path: Path, value: str) -> None:
    config = Config.load(tmp_path)
    config.set("mymod.secret", value)
    assert config.get("mymod.secret") is None


def test_oversized_extra_value_is_rejected(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    config.set("mymod.big", "x" * 5000)
    assert config.get("mymod.big") is None


def test_extra_total_budget_is_enforced(tmp_path: Path) -> None:
    config = Config.load(tmp_path)
    for index in range(40):
        config.set(f"mymod.key{index}", "y" * 2000)
    kept = config.get("extra")
    assert sum(len(value) for value in kept.values()) <= 65536


def test_child_seed_does_not_copy_extra(tmp_path: Path) -> None:
    """`extra` 是全局的：子宠档案里留一份只会让人以为它生效了。"""
    from petcore.ui.pet_manager import SEED_EXCLUDED_KEYS

    assert "extra" in SEED_EXCLUDED_KEYS
    assert {"active_pets", "positions", "menu_layout"} <= SEED_EXCLUDED_KEYS


def test_corrupt_config_is_quarantined_instead_of_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    config = Config.load(tmp_path)
    assert config.corrupt_backup
    backup = Path(config.corrupt_backup)
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "{broken"
    assert not path.exists()


def test_read_only_load_does_not_touch_the_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    config = Config.load(tmp_path, persist=False)
    assert config.corrupt_backup == ""
    assert path.read_text(encoding="utf-8") == "{broken"


def test_read_only_load_does_not_write_anything(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "config.json").write_text(json.dumps({"scale": 1.4}), encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()

    import petcore.config as config_module

    original = config_module.paths.legacy_data_roots
    config_module.paths.legacy_data_roots = lambda: (legacy,)
    try:
        config = Config.load(root, persist=False)
    finally:
        config_module.paths.legacy_data_roots = original

    assert config.get("scale") == pytest.approx(1.4)
    assert not (root / "config.json").exists()
    assert not (root / "migration-backup").exists()


def test_check_command_is_read_only(tmp_path: Path) -> None:
    """`petcore --check` 不许写 config.json / migration-backup（AUD-11）。"""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["APPDATA"] = str(tmp_path / "appdata")
    root = tmp_path / "root"
    root.mkdir()
    before = sorted(item.name for item in tmp_path.rglob("*"))
    result = subprocess.run(
        [sys.executable, "-m", "petcore", "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    created = sorted(item.name for item in tmp_path.rglob("*"))
    assert "config.json" not in created
    assert "migration-backup" not in created
    assert "config.json" not in [name for name in before if name == "config.json"]
