# -*- coding: utf-8 -*-
"""Setup 首启回执消费：读一次、按盘上内容幂等安装、然后删除。

回执由安装器写（`packaging/dsh-pet.iss`），语义是"这次 Setup 在盘上留下了
哪些官方包"。产品侧首次启动必须把它接上，否则用户勾选安装后还要去 MOD 中心
再点一次「安装」。规则：

* 只对"回执 true + `features/<pkg>/manifest.json` 存在 + 当前没有 active 版本"
  的 owner 走一次 `install_official`；
* 每个 owner 独立失败，失败只记录，不阻塞启动、不影响下一个；
* 无论成败都删除回执（MOD 中心仍会显示「安装」行；回执不是重试队列）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pet import startup_receipt as sr
from pet.official_features import AI_FEATURE_ID, SCREEN_FEATURE_ID


class FakeRuntime:
    def __init__(self, *, active=(), fail=()):
        self.installed: list[str] = []
        self.enabled_flags: list[tuple[str, bool]] = []
        self.active = set(active)
        self.fail = set(fail)

    def official_packages(self):
        return tuple(owner for owner in (AI_FEATURE_ID, SCREEN_FEATURE_ID) if owner not in self.active)

    def install_official(self, owner, *, enabled=False):
        if owner in self.fail:
            raise RuntimeError(f"cannot install {owner}")
        self.enabled_flags.append((owner, enabled))
        self.installed.append(owner)
        self.active.add(owner)
        return object(), True


def _write_receipt(app_dir: Path, payload) -> Path:
    path = app_dir / sr.RECEIPT_NAME
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _features(app_dir: Path, *names: str) -> Path:
    root = app_dir / "features"
    for name in names:
        package = root / name
        package.mkdir(parents=True, exist_ok=True)
        (package / "manifest.json").write_text("{}", encoding="utf-8")
    return root


def _receipt(**values) -> dict:
    payload = {"schema": sr.SCHEMA}
    payload.update(values)
    return payload


def test_missing_receipt_is_a_quiet_no_op(tmp_path):
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert result.present is False
    assert result.removed is False
    assert runtime.installed == []


@pytest.mark.parametrize("payload", ["not json", "[]", {"schema": "v0"}, {"schema": sr.SCHEMA, "ai_chat": "yes"}])
def test_invalid_receipt_is_removed_without_installing(tmp_path, payload):
    _write_receipt(tmp_path, payload)
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert result.valid is False
    assert result.removed is True
    assert runtime.installed == []
    assert not (tmp_path / sr.RECEIPT_NAME).exists()


def test_false_flags_install_nothing_and_still_delete_the_receipt(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=False, screen=False))
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert result.valid is True
    assert result.requested == ()
    assert result.removed is True
    assert runtime.installed == []


def test_selected_packages_are_installed_once_then_the_receipt_is_gone(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=True, screen=True))
    _features(tmp_path, "ai-chat", "screen-understanding")
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert runtime.installed == [AI_FEATURE_ID, SCREEN_FEATURE_ID]
    assert runtime.enabled_flags == [(AI_FEATURE_ID, True), (SCREEN_FEATURE_ID, True)]
    assert result.installed == (AI_FEATURE_ID, SCREEN_FEATURE_ID)
    assert result.removed is True
    assert not (tmp_path / sr.RECEIPT_NAME).exists()


def test_receipt_true_without_the_package_files_is_reported_missing(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=True))
    _features(tmp_path)  # features/ exists but no ai-chat manifest
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert runtime.installed == []
    assert result.missing == (AI_FEATURE_ID,)
    assert result.removed is True


def test_already_active_packages_are_skipped_not_reinstalled(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=True))
    _features(tmp_path, "ai-chat")
    runtime = FakeRuntime(active={AI_FEATURE_ID})

    result = sr.consume(tmp_path, runtime)

    assert runtime.installed == []
    assert result.skipped_active == (AI_FEATURE_ID,)
    assert result.removed is True


def test_one_failure_does_not_block_the_other_package(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=True, screen=True))
    _features(tmp_path, "ai-chat", "screen-understanding")
    runtime = FakeRuntime(fail={AI_FEATURE_ID})

    result = sr.consume(tmp_path, runtime)

    assert runtime.installed == [SCREEN_FEATURE_ID]
    assert dict(result.failed) == {AI_FEATURE_ID: "RuntimeError: cannot install official.ai-chat"}
    assert result.removed is True


def test_unknown_receipt_keys_are_ignored(tmp_path):
    _write_receipt(tmp_path, _receipt(ai_chat=False, future_package=True))
    runtime = FakeRuntime()

    result = sr.consume(tmp_path, runtime)

    assert result.valid is True
    assert runtime.installed == []


def test_consume_uses_the_explicit_features_directory(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    features = tmp_path / "elsewhere"
    (features / "ai-chat").mkdir(parents=True)
    (features / "ai-chat" / "manifest.json").write_text("{}", encoding="utf-8")
    _write_receipt(app_dir, _receipt(ai_chat=True))
    runtime = FakeRuntime()

    result = sr.consume(app_dir, runtime, features_dir=features)

    assert runtime.installed == [AI_FEATURE_ID]
    assert result.installed == (AI_FEATURE_ID,)


def test_schedule_defers_consumption_to_the_event_loop(tmp_path, monkeypatch):
    calls: list[tuple] = []

    class FakeTimer:
        @staticmethod
        def singleShot(delay, callback):
            calls.append(delay)
            callback()

    monkeypatch.setattr("PySide6.QtCore.QTimer", FakeTimer)
    _write_receipt(tmp_path, _receipt(ai_chat=False))
    runtime = FakeRuntime()

    assert sr.schedule_consume(runtime, tmp_path) is True

    assert calls == [sr.STARTUP_DELAY_MS]
    assert not (tmp_path / sr.RECEIPT_NAME).exists()


def test_app_shell_schedules_receipt_consumption():
    """接线判据：AppShell 构造出宿主后必须排一次消费（否则回执永远没人读）。"""
    text = (Path(__file__).resolve().parents[1] / "pet" / "app.py").read_text(encoding="utf-8")
    assert "schedule_consume(self.feature_runtime)" in text


def test_schedule_without_a_runtime_is_a_no_op():
    assert sr.schedule_consume(None) is False
