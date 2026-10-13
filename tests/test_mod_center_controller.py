# -*- coding: utf-8 -*-
"""MOD 中心逻辑层：真磁盘（tmp_path）上的导入 / 启停 / 删除 / 回滚 / 换装。

蓝本 = DLC 分支 ``tests/test_mod_center_integration.py`` 的资源侧用例
（DLC 分支的 ``tests/test_mod_center_integration.py``）；宿主面按本仓库重写——DLC 用 ``ResourceClient``
（跨进程 QLocal 通道）准备释放，这里用**派发前快照**（``LiveUsage``）：测试直接给
一张快照，就能把「有没有桌宠正在用这个包」两个分支都钉住，不必起真窗。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet import catalog
from pet.mod_center_controller import LiveUsage, ModCenterController, unsupported_package_message
from pet.mod_management import ModOutcome

app = QApplication.instance() or QApplication([])


def _write_package(root: Path, *, character_id: str = "demo", version: str = "1.0.0",
                   name: str = "Demo", description: str = "", extra: dict | None = None) -> Path:
    package = root / "package"
    videos = package / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    (videos / "idle.webm").write_bytes(b"test-video")
    manifest: dict[str, object] = {"id": character_id, "name": name, "version": version}
    if description:
        manifest["description"] = description
    manifest.update(extra or {})
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


def _zip(source: Path, target: Path) -> Path:
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return target


class Host:
    """最小宿主：托管根 + 可注入的派发前快照 + 记录换装请求。"""

    def __init__(self, data_root: Path, usage: LiveUsage | None = None):
        self.data_root = Path(data_root)
        self.usage = usage or LiveUsage(verified=True)
        self.used: list[str] = []
        self.published = 0
        self.use_outcome: ModOutcome | None = None

    def live_usage(self) -> LiveUsage:
        return self.usage

    def use_resource(self, entry) -> ModOutcome:
        self.used.append(entry.character_id)
        return self.use_outcome or ModOutcome(True, "当前桌宠已换装")

    def catalog_changed(self) -> None:
        self.published += 1


@pytest.fixture
def env(tmp_path, monkeypatch):
    """托管根 = ``<tmp>/<APP_DIR_NAME>``，并由 catalog 把它当作外部角色根（生产口径）。"""
    data_root = tmp_path / "dsh-pet-standalone"
    managed = data_root / "characters"
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [managed])
    return data_root, managed


def pump(predicate, *, timeout: float = 20.0) -> None:
    """真实事件循环里等后台线程的结果（不固定 sleep）。"""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        wait = QEventLoop()
        QTimer.singleShot(20, wait.quit)
        wait.exec()
    assert predicate()


def _controller(env, usage: LiveUsage | None = None):
    data_root, _managed = env
    host = Host(data_root, usage)
    return ModCenterController(host), host


# ------------------------------------------------------------------ 导入

def test_import_from_directory_is_disabled_then_enable_and_delete(env):
    data_root, _managed = env
    controller, host = _controller(env)
    source = _write_package(env[0] / "source")
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert controller.import_source(source)
    pump(lambda: not controller.busy)
    assert results[-1].message.startswith("已导入")
    entry = next(row for row in controller.entries() if row.id == "demo")
    assert not entry.enabled
    # 新导入默认停用 ⇒ 托管副本落在 mod-disabled/（不在扫描根里，停用即真的不参与）
    assert entry.path.parent == data_root / "mod-disabled"
    assert host.published == 1                   # 每次操作后都发失效令牌

    # 重复导入同一版本：如实回报，不改用户的选择（仍是停用）
    assert controller.import_source(source)
    pump(lambda: not controller.busy)
    assert results[-1].message == "已存在，不重复导入"
    assert not controller.resources._entry("demo").enabled

    entry = controller.entries()[0]
    assert controller.perform("enable", [entry.key])
    pump(lambda: not controller.busy)
    assert controller.resources._entry("demo").enabled
    assert controller.perform("delete", [entry.key])
    pump(lambda: not controller.busy)
    assert all(outcome.success for outcome in results), [outcome.message for outcome in results]
    assert source.is_dir()
    assert not any(row.id == "demo" for row in controller.entries())


def test_import_from_zip_lands_disabled(env):
    data_root, _managed = env
    controller, _host = _controller(env)
    archive = _zip(_write_package(env[0] / "source"), env[0] / "mod.zip")
    assert controller.import_source(archive)
    pump(lambda: not controller.busy)
    entry = next(row for row in controller.entries() if row.id == "demo")
    assert not entry.enabled and entry.managed


def test_update_keeps_the_user_choice_and_retains_the_old_copy(env):
    data_root, _managed = _controller_root = env
    controller, _host = _controller(env)
    first = _write_package(env[0] / "one", version="1.0.0")
    controller.import_source(first)
    pump(lambda: not controller.busy)
    controller.perform("enable", [controller.entries()[0].key])
    pump(lambda: not controller.busy)

    # 更新到 1.0.1：仍保持启用，旧版本进 mod-versions 供回滚
    second = _write_package(env[0] / "two", version="1.0.1")
    assert controller.import_source(second, expected="角色资源:demo")
    pump(lambda: not controller.busy)
    entry = controller.resources._entry("demo")
    assert entry.enabled and entry.version == "1.0.1"
    assert (data_root / "mod-versions" / "demo" / "1.0.0").is_dir()


def test_update_refuses_a_different_package(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    other = _write_package(env[0] / "other", character_id="other")
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert controller.import_source(other, expected="角色资源:demo")
    pump(lambda: not controller.busy)
    assert not results[-1].success
    assert "同一个角色包" in results[-1].message


def test_rollback_restores_the_retained_version(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one", version="1.0.0"))
    pump(lambda: not controller.busy)
    controller.perform("enable", [controller.entries()[0].key])
    pump(lambda: not controller.busy)
    controller.import_source(_write_package(env[0] / "two", version="1.0.1"), expected="角色资源:demo")
    pump(lambda: not controller.busy)

    assert controller.perform("rollback", [controller.entries()[0].key])
    pump(lambda: not controller.busy)
    assert controller.resources._entry("demo").version == "1.0.0"


# ------------------------------------------------------------ 占用与放行

def test_release_refused_when_a_live_pet_renders_the_package(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    controller.perform("enable", [controller.entries()[0].key])
    pump(lambda: not controller.busy)
    entry = controller.resources._entry("demo")
    assert entry.enabled
    # 下一批操作前的快照：某个活桌宠正在渲染这个包的素材目录
    controller.host.usage = LiveUsage(verified=True, asset_dirs=(entry.path / "videos",))
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert controller.perform("disable", [entry.key])
    pump(lambda: not controller.busy)
    assert not results[-1].success and results[-1].pending
    assert "正在使用" in results[-1].message
    assert controller.resources._entry("demo").enabled
    assert entry.path.is_dir()


def test_release_refused_when_the_host_cannot_answer(env):
    """宿主答不上来时按"可能在用"处理：拒绝，且文案说的是「确认不了」而不是「你在用」。"""
    controller, _host = _controller(env, LiveUsage(verified=False))
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    entry = controller.entries()[0]
    controller.host.usage = LiveUsage(verified=False)
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    controller.perform("delete", [entry.key])
    pump(lambda: not controller.busy)
    assert not results[-1].success
    assert "无法确认" in results[-1].message
    assert not results[-1].message.startswith("这只桌宠正在使用")
    assert entry.path.exists()


def test_enable_is_allowed_even_while_a_pet_runs(env):
    """启用不动已有副本，不需要放行判据（停止才需要）。"""
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    entry = controller.entries()[0]
    controller.host.usage = LiveUsage(verified=True, asset_dirs=(entry.path / "videos",))
    controller.perform("enable", [entry.key])
    pump(lambda: not controller.busy)
    assert controller.resources._entry("demo").enabled


def test_updating_an_in_use_package_is_refused_in_words_the_user_can_act_on(env):
    """「更新」与「停用/删除」说同一句话（更新也要先换装），且不落盘。"""
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one", version="1.0.0"))
    pump(lambda: not controller.busy)
    controller.perform("enable", ["角色资源:demo"])
    pump(lambda: not controller.busy)
    entry = controller.resources._entry("demo")
    controller.host.usage = LiveUsage(verified=True, asset_dirs=(entry.path / "videos",))
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert controller.import_source(_write_package(env[0] / "two", version="1.0.1"))
    assert not results[-1].success and results[-1].pending
    assert results[-1].message.startswith("这只桌宠正在使用")
    assert controller.resources._entry("demo").version == "1.0.0"


def test_reimporting_the_same_version_is_not_treated_as_a_conflict(env):
    """同版本重复导入根本不落盘 ⇒ 不必先换装，照旧回报「已存在」。"""
    controller, _host = _controller(env)
    source = _write_package(env[0] / "one", version="1.0.0")
    controller.import_source(source)
    pump(lambda: not controller.busy)
    controller.perform("enable", ["角色资源:demo"])
    pump(lambda: not controller.busy)
    entry = controller.resources._entry("demo")
    controller.host.usage = LiveUsage(verified=True, asset_dirs=(entry.path / "videos",))
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    controller.import_source(source)
    pump(lambda: not controller.busy)
    assert results[-1].success and results[-1].message == "已存在，不重复导入"


# ----------------------------------------------------------------- 非资源

def test_feature_package_is_refused_with_a_truthful_reason(env):
    controller, _host = _controller(env)
    package = _write_package(env[0] / "feature", extra={"kind": "feature", "execution_kind": "host-worker"})
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert not controller.import_source(package)
    assert not controller.busy
    assert "功能扩展" in results[-1].message
    assert not [row for row in controller.entries() if row.managed]


@pytest.mark.parametrize("declared", [
    {"kind": "feature"},
    {"execution_kind": "host-worker"},
    {"format_version": 2},
    {"factory": "sample-offline/v1"},
])
def test_declared_non_resource_markers_are_refused(env, declared):
    package = _write_package(env[0] / "pkg", extra=declared)
    assert unsupported_package_message(package)
    assert unsupported_package_message(_zip(package, env[0] / "pkg.zip"))


def test_plain_character_package_is_not_treated_as_a_feature(env):
    package = _write_package(env[0] / "plain")
    assert unsupported_package_message(package) == ""
    assert unsupported_package_message(env[0] / "missing.zip") == ""


def test_a_broken_package_fails_with_a_readable_reason(env):
    controller, _host = _controller(env)
    broken = env[0] / "broken"
    broken.mkdir(parents=True)
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert controller.import_source(broken)
    pump(lambda: not controller.busy)
    assert not results[-1].success
    assert "操作未完成" in results[-1].message


def test_importing_a_missing_path_reports_without_starting_a_batch(env):
    controller, _host = _controller(env)
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert not controller.import_source(env[0] / "nope.zip")
    assert not controller.busy
    assert not results[-1].success


# --------------------------------------------------------------- 队列协议

def test_use_runs_on_the_calling_thread_and_reports_the_host_outcome(env):
    controller, host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    controller.perform("enable", [controller.entries()[0].key])
    pump(lambda: not controller.busy)
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    controller.perform("use", [controller.entries()[0].key])
    assert host.used == ["demo"]
    assert results[-1].message == "当前桌宠已换装"


def test_unknown_action_and_unknown_key_change_nothing(env):
    controller, host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    assert controller.perform("explode", ["角色资源:demo"]) is False
    assert controller.perform("enable", ["角色资源:nope"]) is True   # 空批次，立即收尾
    pump(lambda: not controller.busy)
    assert not controller.resources._entry("demo").enabled
    assert host.used == []


def test_batch_reports_every_key_once_in_order(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one", character_id="alpha"))
    pump(lambda: not controller.busy)
    controller.import_source(_write_package(env[0] / "two", character_id="beta"))
    pump(lambda: not controller.busy)
    batches = []
    controller.batch_finished.connect(batches.append)
    keys = [row.key for row in controller.entries() if row.managed]
    assert len(keys) == 2
    assert controller.perform("enable", keys)
    pump(lambda: not controller.busy)
    assert [key for key, _outcome in batches[0]] == keys
    assert all(outcome.success for _key, outcome in batches[0])


def test_a_second_batch_is_refused_while_one_runs(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    controller.busy = True
    assert controller.perform("enable", [controller.entries()[0].key]) is False


def test_close_stops_the_queue(env):
    controller, _host = _controller(env)
    controller.import_source(_write_package(env[0] / "one"))
    pump(lambda: not controller.busy)
    entry = controller.entries()[0]
    controller.busy = True
    controller._queue.append(("enable", entry, None))
    controller.close()
    controller._next()
    assert not controller.resources._entry("demo").enabled
