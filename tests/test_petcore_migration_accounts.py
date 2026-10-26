"""API 服务规格与系统钥匙串凭据迁移的测试。

真实用户目录与真实钥匙串一律不碰：旧数据在 ``tmp_path`` 里造，钥匙串用内存假后端。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from petcore import migration
from petcore.migration import accounts

SECRET = "sk-legacy-provider-0001"
LOCAL_SECRET = "sk-local-provider-0002"
SEARCH_SECRET = "search-secret-0003"
TTS_SECRET = "tts-secret-0004"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class FakeKeyring:
    """够用的内存钥匙串：只实现迁移用到的 get/set。"""

    def __init__(self, entries: dict[tuple[str, str], str] | None = None) -> None:
        self.entries: dict[tuple[str, str], str] = dict(entries or {})
        self.writes: list[tuple[str, str]] = []

    def get_password(self, service: str, account: str) -> str | None:
        return self.entries.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.entries[(service, account)] = value
        self.writes.append((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.entries.pop((service, account), None)


class BrokenKeyring:
    """后端坏了：任何调用都抛异常，且异常文本里带一段"密钥"防泄漏断言。"""

    def get_password(self, service: str, account: str) -> str | None:
        raise RuntimeError(f"backend down: {SECRET}")

    def set_password(self, service: str, account: str, value: str) -> None:
        raise RuntimeError(f"backend down: {value}")


def _ctx(tmp_path: Path, *, dry_run: bool = False):
    root = tmp_path / "new-root"
    legacy = tmp_path / "dsh-pet-standalone"
    legacy.mkdir(parents=True, exist_ok=True)
    return (
        migration.MigrationContext(
            root=root,
            legacy_roots=(legacy,),
            dry_run=dry_run,
            backup_root=root / migration.BACKUP_DIRNAME,
        ),
        root,
        legacy,
    )


def _legacy_chat() -> dict[str, Any]:
    return {
        "chat": {
            "enabled": True,
            "active_provider": "openai-main",
            "default_system_prompt": "旧提示词",
            "web_search": {
                "enabled": True,
                "engine": "bocha",
                "api_key_ref": "websearch/api",
            },
            "providers": {
                "openai-main": {
                    "name": "DeepSeek",
                    "base_url": "https://api.deepseek.com",
                    "chat_path": "/v1/chat/completions",
                    "model": "deepseek-chat",
                    "vision_model": "deepseek-vl",
                    "api_key_ref": "provider/openai-main",
                    "vision_api_key_ref": "provider/openai-main/vision",
                    "api_key": SECRET,
                    "timeout": 120.0,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "verify_ssl": True,
                },
                "My Local 测试": {
                    "name": "本地",
                    "base_url": "http://localhost:8000/v1",
                    "model": "local-model",
                    "api_key": LOCAL_SECRET,
                    "timeout": 5,
                    "verify_ssl": False,
                },
            },
        }
    }


def _details(entries: list[migration.MigrationEntry]) -> str:
    return " | ".join(entry.detail for entry in entries)


def test_api_providers_become_services_without_secrets(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(legacy / "config.json", _legacy_chat())

    entries = accounts.migrate_api(ctx)

    payload = _read_json(root / "api.json")
    assert payload["schema_version"] == 1
    assert payload["version"] == 1
    services = payload["services"]
    assert set(services) == {"openai-main", "my-local"}, "非法 service_id 要规整成安全 slug"

    main = services["openai-main"]
    assert main["name"] == "DeepSeek"
    assert main["base_url"] == "https://api.deepseek.com"
    assert main["chat_path"] == "/v1/chat/completions"
    assert main["model"] == "deepseek-chat"
    assert main["vision_model"] == "deepseek-vl"
    assert main["timeout"] == 120
    assert main["verify_ssl"] is True
    assert main["balance_protocol"] == "deepseek"

    local = services["my-local"]
    assert local["base_url"] == "http://localhost:8000/v1"
    assert local["timeout"] == 5
    assert local["verify_ssl"] is False
    # 旧壳 vision_same_as_chat 默认 True：空视觉模型等于「用聊天模型识屏」。
    assert local["vision_model"] == "local-model"

    text = (root / "api.json").read_text(encoding="utf-8")
    for literal in (SECRET, LOCAL_SECRET):
        assert literal not in text, "明文密钥不许落进 api.json"
    assert "api_key" not in text

    assert "id-normalized:My Local 测试->my-local" in _details(entries)
    assert "dropped:" in _details(entries)
    assert "temperature" in _details(entries) and "max_tokens" in _details(entries)
    assert "dropped:default_system_prompt,web_search" in _details(entries)

    assert _read_json(root / "config.json")["api_service_id"] == "openai-main"
    assert any(
        entry.detail == "api_service_id" and entry.status == migration.STATUS_MIGRATED
        for entry in entries
    )


def test_existing_service_id_is_not_overwritten(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(
        legacy / "config.json",
        {
            "chat": {
                "active_provider": "openai-main",
                "providers": {
                    "openai-main": {
                        "name": "DeepSeek",
                        "base_url": "https://api.deepseek.com",
                        "model": "legacy-model",
                        "api_key": SECRET,
                    }
                },
            }
        },
    )
    _write_json(
        root / "api.json",
        {
            "schema_version": 1,
            "version": 7,
            "services": {
                "openai-main": {
                    "name": "用户改过的名字",
                    "base_url": "https://api.deepseek.com",
                    "chat_path": "/v1/chat/completions",
                    "model": "kept-model",
                    "vision_model": "",
                    "verify_ssl": True,
                    "timeout": 30,
                    "balance_protocol": "none",
                }
            },
        },
    )

    entries = accounts.migrate_api(ctx)

    payload = _read_json(root / "api.json")
    assert payload["version"] == 7, "没有新增服务就不该动文件"
    assert payload["services"]["openai-main"]["model"] == "kept-model"
    assert payload["services"]["openai-main"]["name"] == "用户改过的名字"
    assert any(
        entry.status == migration.STATUS_ALREADY and entry.target.endswith("api.json")
        for entry in entries
    )


def test_missing_chat_is_reported_as_not_found(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(legacy / "config.json", {"character": "shenshen"})

    entries = accounts.migrate_api(ctx)

    assert [entry.status for entry in entries] == [migration.STATUS_NOT_FOUND]
    assert not (root / "api.json").exists()


def test_dry_run_writes_no_api_file(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path, dry_run=True)
    _write_json(legacy / "config.json", _legacy_chat())

    entries = accounts.migrate_api(ctx)

    assert any(entry.status == migration.STATUS_MIGRATED for entry in entries)
    assert not (root / "api.json").exists()
    assert not (root / "config.json").exists()


def test_credentials_move_to_new_keyring_names(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(legacy / "config.json", _legacy_chat())
    fake = FakeKeyring(
        {
            ("dsh-pet-standalone", "provider/openai-main"): SECRET,
            ("dsh-pet-standalone", "websearch/api"): SEARCH_SECRET,
            ("dsh-pet-standalone", "tts/mimo"): TTS_SECRET,
        }
    )

    entries = accounts.migrate_credentials(ctx, backend=fake)

    assert fake.entries[("dsh-pet-core", "core.api:openai-main")] == SECRET
    assert fake.entries[("dsh-pet-core", "core.websearch:bocha")] == SEARCH_SECRET
    assert fake.entries[("dsh-pet-core", "speech.mimo:api_key")] == TTS_SECRET
    # 旧条目保留，回滚只需丢掉新条目。
    assert fake.entries[("dsh-pet-standalone", "provider/openai-main")] == SECRET
    assert fake.entries[("dsh-pet-standalone", "tts/mimo")] == TTS_SECRET

    migrated = [entry for entry in entries if entry.status == migration.STATUS_MIGRATED]
    assert len(migrated) == 3
    assert all(entry.count == 1 for entry in migrated)
    # 视觉在新壳没有独立凭据位：要显式说明，不许假装迁过。
    assert "vision-skipped:no-slot" in _details(entries)

    again = accounts.migrate_credentials(ctx, backend=fake)

    assert len(fake.writes) == 3, "第二次跑不许重复写"
    assert all(
        entry.status in (migration.STATUS_ALREADY, migration.STATUS_SKIPPED)
        for entry in again
        if entry.kind == accounts.KIND_CREDENTIALS and entry.detail != "missing"
    )
    assert any(entry.status == migration.STATUS_ALREADY for entry in again)


def test_credentials_dry_run_only_probes(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path, dry_run=True)
    _write_json(legacy / "config.json", _legacy_chat())
    fake = FakeKeyring({("dsh-pet-standalone", "provider/openai-main"): SECRET})

    entries = accounts.migrate_credentials(ctx, backend=fake)

    assert fake.writes == []
    assert ("dsh-pet-core", "core.api:openai-main") not in fake.entries
    assert any(
        entry.status == migration.STATUS_MIGRATED and entry.target.endswith("core.api:openai-main")
        for entry in entries
    )


def test_missing_old_account_is_skipped(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(legacy / "config.json", _legacy_chat())

    entries = accounts.migrate_credentials(ctx, backend=FakeKeyring())

    assert entries
    assert all(
        entry.status in (migration.STATUS_NOT_FOUND, migration.STATUS_SKIPPED)
        for entry in entries
    )
    assert not any(entry.status in migration.FAILURE_STATUSES for entry in entries)


def test_broken_keyring_is_unsupported_and_leaks_nothing(tmp_path: Path) -> None:
    ctx, root, legacy = _ctx(tmp_path)
    _write_json(legacy / "config.json", _legacy_chat())

    entries = accounts.migrate_credentials(ctx, backend=BrokenKeyring())

    assert len(entries) == 1
    assert entries[0].status == migration.STATUS_UNSUPPORTED
    assert entries[0].detail == "keyring-unavailable"
    report_text = json.dumps([entry.as_dict() for entry in entries], ensure_ascii=False)
    for literal in (SECRET, LOCAL_SECRET, SEARCH_SECRET, TTS_SECRET):
        assert literal not in report_text
