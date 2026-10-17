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
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet import catalog
from pet.mod_center_controller import KIND_EXTENSION, LiveUsage, ModCenterController, declared_manifest, unsupported_package_message
from pet.mod_management import ModOutcome
from tests.mod_package_fakes import write_package


app = QApplication.instance() or QApplication([])


def _write_package(root: Path, *, character_id: str = "demo", version: str = "1.0.0",
                   name: str = "Demo", description: str = "", extra: dict | None = None) -> Path:
    return write_package(
        root,
        character_id=character_id,
        version=version,
        name=name,
        description=description,
        extra=extra,
    )


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


def test_a_declared_content_kind_is_not_rejected_by_the_router(env):
    """完整清单声明 ``kind=content`` 是资源包的正确形态；路由层不许把它当成异物。"""
    controller, _host = _controller(env)
    source = _write_package(env[0] / "source")
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))

    assert controller.import_source(source)
    pump(lambda: not controller.busy)

    assert results and results[-1].success
    assert any(row.id == "demo" for row in controller.entries())


class _OfficialHost(Host):
    def __init__(self, data_root):
        super().__init__(data_root)
        self.installed: list[str] = []

    def official_packages(self):
        return ("official.ai-chat",)

    def install_official(self, owner):
        self.installed.append(owner)
        return object(), True


def test_an_uninstalled_official_package_has_an_install_row_and_action(env):
    host = _OfficialHost(env[0])
    controller = ModCenterController(host)

    row = next(row for row in controller.entries() if row.id == "official.ai-chat")
    assert row.source == "official"
    assert row.pending == "未安装"
    assert row.managed is False

    assert controller.install_official("official.ai-chat")
    pump(lambda: not controller.busy)

    assert host.installed == ["official.ai-chat"]


def test_an_unknown_official_owner_is_refused_by_the_controller(env):
    controller, _host = _controller(env)
    assert not controller.install_official("official.nope")


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
    # 如实报：说清它不是角色资源包、声明的是什么，绝不说成导入成功。
    assert results[-1].message.startswith("本版本只支持角色资源包")
    assert "feature" in results[-1].message
    assert not results[-1].success
    assert not [row for row in controller.entries() if row.managed]


def test_a_feature_package_without_a_registered_extension_names_the_missing_half(env):
    """标记字段存在但没有对应注册表条目时，拒绝语要指向真正的缺口。

    D2 片 2 起宿主已接上，这条只剩「这次没能接上」（装配失败 / 路由失败）两种成因，
    所以文案不再说"本版本还没有接上"——那是新的假话。
    """
    controller, _host = _controller(env)
    package = _write_package(env[0] / "marker-only", extra={"execution_kind": "host-worker"})
    results = []
    controller.result.connect(lambda _key, outcome: results.append(outcome))
    assert not controller.import_source(package)
    assert "功能扩展" in results[-1].message
    assert "没能接上" in results[-1].message
    assert not results[-1].success


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


def test_a_registered_extension_id_is_not_refused_by_the_declaration_gate(env):
    """注册表里有这个 id ⇒ 声明层放行，交给那条信任链自己回答能不能装。"""
    package = _write_package(env[0] / "known", extra={"execution_kind": "host-worker"})
    manifest = declared_manifest(package)
    owner = manifest["id"]
    assert unsupported_package_message(package, extensions={owner}) == ""
    assert unsupported_package_message(package, extensions=set()) != ""


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

# ------------------------------------------------------- 功能扩展（注册表由宿主给）

def _result(status, **kwargs):
    """事务层 ``OperationResult`` 的同形状桩（控制器只按属性读它）。"""
    fields = {"operation_id": None, "phase": None, "plan": None, "revision": 1, "reason": None}
    fields.update(kwargs)
    return type("_Result", (), {"status": status, **fields})()


class ExtensionService:
    """事务服务的同形状桩：``inspect()`` + ``store.root``（控制器只用这两项）。"""

    def __init__(self, root: Path, *, active="1.2.3", enabled=True, pending=None, revision=1):
        self.store = type("_Store", (), {"root": Path(root)})()
        self._info = type("_Info", (), {"active": active, "enabled": enabled, "pending_transaction": pending, "revision": revision})()

    def inspect(self):
        return self._info


class ExtensionManager(QObject):
    """功能扩展管理器的同形状桩：``service`` / ``submit`` / 两个信号 / ``last_result``。

    默认行为照真管理器：接受动作后**异步回报**一条 ``completed`` 结果（经
    ``result_ready`` 信号回灌）。需要精确控制结果序列的用例把 ``auto_result`` 关掉，
    自己 emit。
    """

    result_ready = Signal(object)
    state_changed = Signal()

    def __init__(self, root: Path, *, service=None):
        super().__init__()
        self.service = service or ExtensionService(root)
        self.submitted: list = []
        self.imported: list = []
        self.accepts = True
        self.auto_result = True
        self.last_result = None

    def complete(self, result, *, owner="official.demo"):
        self.last_result = result
        self.result_ready.emit(result)
        return True

    def submit(self, action, *args, **kwargs):
        self.submitted.append((action, args, kwargs))
        return self.accepts and (self.complete(_result("completed")) if self.auto_result else True)

    def submit_local_source(self, source, *, auto_apply=True, enabled=False):
        self.imported.append((Path(source), auto_apply, enabled))
        return self.accepts and (self.complete(_result("completed")) if self.auto_result else True)


def _extension_env(env, *, active="1.2.3", enabled=True, pending=None, name="Demo Extension"):
    """一棵已安装的功能扩展版本目录（清单只作展示元数据）+ 一个注册表条目。"""
    install_root = env[0] / "extensions-data" / "official.demo"
    version_dir = install_root / "versions" / active
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "manifest.json").write_text(json.dumps({"name": name, "description": "样例"}), encoding="utf-8")
    return ExtensionManager(install_root, service=ExtensionService(install_root, active=active, enabled=enabled, pending=pending))


class ExtensionHost(Host):
    def __init__(self, data_root, managers, *, usage=None):
        super().__init__(data_root, usage)
        self._managers = dict(managers)

    def extensions(self):
        return dict(self._managers)


def _extension_controller(env, managers):
    return ModCenterController(ExtensionHost(env[0], managers))


def _feature_package(root: Path, *, owner="official.demo", version="1.2.4") -> Path:
    package = root / "package"
    package.mkdir(parents=True, exist_ok=True)
    (package / "manifest.json").write_text(
        json.dumps({"format_version": 2, "execution_kind": "host-only", "id": owner, "version": version, "name": "Demo Extension"}),
        encoding="utf-8",
    )
    return package


def _only_extensions(controller):
    return [row for row in controller.entries() if row.kind == KIND_EXTENSION]


def test_kinds_advertises_both_resource_and_extension(env):
    from pet.mod_center_controller import KINDS, KIND_RESOURCE

    assert KINDS == (KIND_RESOURCE, KIND_EXTENSION)
    assert _controller(env)[0].kinds == KINDS


def test_an_installed_extension_is_listed_with_its_own_kind(env):
    manager = _extension_env(env, pending="tx-abc")
    controller = _extension_controller(env, {"official.demo": manager})
    rows = _only_extensions(controller)
    assert len(rows) == 1
    row = rows[0]
    assert (row.kind, row.id, row.name, row.version) == (KIND_EXTENSION, "official.demo", "Demo Extension", "1.2.3")
    assert row.enabled and row.managed
    assert row.key == KIND_EXTENSION + ":official.demo"
    assert "等待自然退出" in row.pending


def test_an_extension_without_an_installed_version_is_not_listed(env):
    manager = _extension_env(env)
    manager.service = ExtensionService(manager.service.store.root, active=None)
    assert _only_extensions(_extension_controller(env, {"official.demo": manager})) == []


def test_importing_a_registered_extension_package_reaches_its_manager(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append((key, outcome)))
    package = _feature_package(env[0] / "incoming")
    assert controller.import_source(package) is True
    pump(lambda: not controller.busy)
    assert manager.imported == [(package, True, False)]
    assert results[-1][0] == KIND_EXTENSION + ":official.demo"
    assert results[-1][1].success and results[-1][1].message == "已导入；点击启用即可使用"


def test_updating_an_extension_from_another_packages_row_is_refused(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.import_source(_feature_package(env[0] / "incoming"), expected=KIND_EXTENSION + ":official.other") is False
    assert not manager.imported
    assert "不是同一个包" in results[-1].message


def test_a_busy_extension_manager_is_reported_truthfully(env):
    manager = _extension_env(env)
    manager.accepts = False
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller.import_source(_feature_package(env[0] / "incoming"))
    pump(lambda: not controller.busy)
    assert not results[-1].success and "正在操作" in results[-1].message


@pytest.mark.parametrize("action, expected", [("enable", ("enable", True)), ("disable", ("enable", False))])
def test_enable_and_disable_route_to_the_extension_manager(env, action, expected):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.perform(action, [KIND_EXTENSION + ":official.demo"])
    action_name, args, kwargs = manager.submitted[0]
    assert action_name == expected[0] and args[0] is expected[1]
    assert kwargs["expected_revision"] == 1
    assert results[-1].success and results[-1].message == ("已启用" if action == "enable" else "已停用")


@pytest.mark.parametrize("action, submitted", [("delete", "uninstall"), ("rollback", "rollback")])
def test_delete_and_rollback_route_to_the_extension_manager(env, action, submitted):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller.perform(action, [KIND_EXTENSION + ":official.demo"])
    action_name, args, kwargs = manager.submitted[0]
    assert action_name == submitted and args == () and kwargs == {}
    assert results[-1].success


@pytest.mark.parametrize("pending, accepted", [(None, False), ("tx-1", True)])
def test_an_awaiting_release_result_is_reported_as_accepted_only_when_the_transaction_is_pending(env, pending, accepted):
    manager = _extension_env(env)
    manager.service = ExtensionService(manager.service.store.root, pending=pending)
    manager.auto_result = False
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller.perform("delete", [KIND_EXTENSION + ":official.demo"])
    manager.complete(_result("awaiting_release", operation_id="tx-1", reason="version_in_use"))
    outcome = results[-1]
    assert not outcome.success and outcome.pending is accepted
    assert ("等待相关程序自然退出" in outcome.message) is accepted


def test_a_lock_busy_load_walks_the_retry_ladder_before_reporting(env):
    """管理器的「加载」报锁忙时，控制器按阶梯重试；超限才如实报。

    DLC 的重试语义是：安装状态已经落地，但管理器这一次**加载**撞上锁（``last_result``
    报锁忙）。重试期间管理器自己会再试一次加载，所以这里在重试点上更新
    ``last_result``，模拟那一次已经成功。
    """
    manager = _extension_env(env)
    manager.auto_result = False
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))

    def submit(source, *, auto_apply=True, enabled=False):
        manager.last_result = _result("completed", reason="management_lock_busy")
        manager.result_ready.emit(_result("completed"))
        return True

    manager.submit_local_source = submit
    retries = []
    original_retry = controller._retry_load

    def spy(owner, result):
        retries.append(owner)
        manager.last_result = _result("completed")  # 管理器的下一次加载成功了
        return original_retry(owner, result)

    controller._retry_load = spy
    controller.import_source(_feature_package(env[0] / "incoming"))
    pump(lambda: not controller.busy)
    assert retries == ["official.demo"]
    assert results[-1].success


def test_a_load_that_did_not_finish_is_not_reported_as_installed(env):
    """状态存下了、加载没走完 —— 两件事必须分开说。"""
    manager = _extension_env(env)
    manager.auto_result = False
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))

    def submit(source, *, auto_apply=True, enabled=False):
        manager.last_result = _result("recovery_required", reason="startup_load_failed")
        manager.result_ready.emit(_result("completed"))
        return True

    manager.submit_local_source = submit
    controller.import_source(_feature_package(env[0] / "incoming"))
    pump(lambda: not controller.busy)
    assert not results[-1].success
    assert results[-1].message.startswith("安装状态已保存，但加载未完成")
    assert "startup_load_failed" in results[-1].message


def test_a_result_for_another_owner_is_ignored(env):
    manager = _extension_env(env)
    manager.auto_result = False
    controller = _extension_controller(env, {"official.demo": manager})
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller.import_source(_feature_package(env[0] / "incoming"))
    manager.complete(_result("completed"))
    pump(lambda: not controller.busy)
    assert len(results) == 1
    manager.result_ready.emit(_result("completed"))  # 队列已空 ⇒ 不产生第二行
    assert len(results) == 1


def test_a_vanished_extension_is_reported_instead_of_silently_doing_nothing(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    entry = _only_extensions(controller)[0]
    controller.extensions.clear()
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller._begin([("enable", entry, None)])
    assert not results[-1].success and "已经不可用" in results[-1].message


def test_an_extension_manager_that_raises_is_reported_not_swallowed(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    entry = _only_extensions(controller)[0]

    def refuse(*_args, **_kwargs):
        raise RuntimeError("stub refusal")

    manager.submit = refuse
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    controller._begin([("disable", entry, None)])
    assert not results[-1].success and "操作未完成" in results[-1].message


def test_extension_and_resource_rows_share_one_queue_and_one_batch(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    controller.import_source(_write_package(env[0] / "char", character_id="demo"))
    pump(lambda: not controller.busy)

    batches = []
    controller.batch_finished.connect(lambda rows: batches.append(rows))
    assert controller.perform("enable", ["角色资源:demo", KIND_EXTENSION + ":official.demo"])
    pump(lambda: batches)
    assert [key for key, _outcome in batches[-1]] == ["角色资源:demo", KIND_EXTENSION + ":official.demo"]
    assert all(outcome.success for _key, outcome in batches[-1])
    assert manager.submitted[0][0] == "enable"


# ------------------------------------------------------- 撤回前的草稿预检（D2 片 2）

class _DraftHost(ExtensionHost):
    """带 ``prepare_feature_revocation`` 的宿主：预检结论由用例给定。"""

    def __init__(self, data_root, managers, *, allowed=True):
        super().__init__(data_root, managers)
        self.allowed = allowed
        self.asked: list = []

    def prepare_feature_revocation(self, owner):
        self.asked.append(owner)
        return self.allowed


def _draft_controller(env, manager, *, allowed=True):
    host = _DraftHost(env[0], {"official.demo": manager}, allowed=allowed)
    return host, ModCenterController(host)


def test_a_refused_revocation_precheck_aborts_before_touching_the_manager(env):
    """取消 = 中止：管理器连一条命令都不该收到（草稿与安装副本都原样保留）。"""
    manager = _extension_env(env)
    host, controller = _draft_controller(env, manager, allowed=False)
    results = []
    controller.result.connect(lambda key, outcome: results.append((key, outcome)))
    entry = _only_extensions(controller)[0]
    controller._begin([("disable", entry, None)])
    pump(lambda: results)
    assert host.asked == ["official.demo"]
    assert manager.submitted == []
    assert results[-1][1].success is False
    assert "已取消" in results[-1][1].message


def test_an_allowed_revocation_precheck_reaches_the_manager(env):
    manager = _extension_env(env)
    host, controller = _draft_controller(env, manager, allowed=True)
    entry = _only_extensions(controller)[0]
    controller._begin([("disable", entry, None)])
    pump(lambda: not controller.busy)
    assert host.asked == ["official.demo"]
    assert manager.submitted[0][0] == "enable"


def test_enable_is_never_gated_by_the_draft_precheck(env):
    """启用不丢任何东西：不该被草稿问一次（问的每一条都要能中止动作才有意义）。"""
    manager = _extension_env(env, enabled=False)
    host, controller = _draft_controller(env, manager, allowed=False)
    entry = _only_extensions(controller)[0]
    controller._begin([("enable", entry, None)])
    pump(lambda: not controller.busy)
    assert host.asked == []
    assert manager.submitted[0][0] == "enable"


def test_an_update_of_an_installed_extension_is_gated_too(env):
    manager = _extension_env(env)
    host, controller = _draft_controller(env, manager, allowed=False)
    package = _feature_package(env[0] / "incoming")
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.import_source(package, expected=KIND_EXTENSION + ":official.demo") is True
    pump(lambda: results)
    assert host.asked == ["official.demo"]
    assert manager.imported == []
    assert "已取消" in results[-1].message


def test_a_host_without_the_precheck_capability_behaves_exactly_as_before(env):
    manager = _extension_env(env)
    controller = _extension_controller(env, {"official.demo": manager})
    entry = _only_extensions(controller)[0]
    controller._begin([("disable", entry, None)])
    pump(lambda: not controller.busy)
    assert manager.submitted[0][0] == "enable"


def test_a_precheck_that_raises_does_not_block_the_user(env):
    """预检本身出错不许把用户卡死在"点不动"上：如实放行，让下游权威判据回答。"""
    manager = _extension_env(env)
    host = _DraftHost(env[0], {"official.demo": manager})

    def broken(_owner):
        raise RuntimeError("precheck blew up")

    host.prepare_feature_revocation = broken
    controller = ModCenterController(host)
    entry = _only_extensions(controller)[0]
    controller._begin([("disable", entry, None)])
    pump(lambda: not controller.busy)
    assert manager.submitted[0][0] == "enable"
