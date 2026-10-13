# -*- coding: utf-8 -*-
"""D3：本地 ZIP 功能包导入链——从「选一个 ZIP」到「在扩展管理里可见可启停」。

走的是**真**东西：材料由 ``scripts.build_mod_example`` 把仓库里的示例功能包打成
目录 + ZIP；``DialogModHost`` + ``ModCenterController`` 是设置页用的那两个对象；
``LocalFeatureRuntime`` 是 ``extensions()`` 的真值；事务/安装状态/验签是 D2 已落地的
那一套，本片没有另起炉灶。链路上每一条都要能机器判定：

1. **正路径**：ZIP 导入成功、默认停用、在 MOD 中心列成「功能扩展」一行，可启停；
2. **ZIP 与目录同包同版本**收敛到一次安装（幂等），不产生第二份副本；
3. **坏 manifest**：清单读不出来 / 关键字段缺失 ⇒ 拒绝，且不留任何第三方安装痕迹；
4. **校验失败**：打包之后字节被换过 ⇒ 验签那一环拒（路由只看清单，所以它拦不住）；
5. **路由与 owner 隔离**：未知 owner 按第三方 DLC 接受；官方保留 ID 一律拒，
   而且**不会**被谁先占住 ``feature-data/<官方 id>/``；两个第三方 owner 的端口互不可见；
6. **重复安装与版本解析**：同版本同摘要幂等、同版本改字节拒、升版本保留 previous、降版本拒；
7. **探针前置**：``host/`` 装不起来 / ``create_host()`` 说的 owner 与清单不符 ⇒ 在
   **装之前**被 ``pet.feature_package_preflight`` 拒掉，安装状态与版本目录都不动。
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from pet import __version__
from pet.config import Config
from pet.feature_management import LocalFeatureRuntime
from pet.local_package_intents import route_local_package
from pet.mod_center_controller import KIND_EXTENSION, ModCenterController
from pet.plugins.package_trust import FeaturePackageVerifier, PackageVerificationError
from pet.settings_mod_domain import DialogModHost
from tests._feature_import_package import DEFAULT_OWNER as OWNER
from tests._feature_import_package import build, build_tree, rearchive, source_tree

OTHER_OWNER = "community.someone.tool"
OFFICIAL_OWNER = "official.ai-chat"

app = QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ 装配

class _Shell(QWidget):
    """带了扩展宿主的设置对话框父窗（``DialogModHost.feature_host`` 的唯一来源）。"""

    def __init__(self, runtime):
        super().__init__()
        self.feature_runtime = runtime


class _Dialog(QWidget):
    def __init__(self, config, parent):
        super().__init__(parent)
        self.config = config


class _Center:
    """一次测试用的最小装配：宿主 + 控制器 + 收集到的结果行。"""

    def __init__(self, tmp_path: Path, *, role="core"):
        self.config = Config(base=tmp_path)
        self.runtime = LocalFeatureRuntime(self.config, role=role)
        # 壳与对话框都要留引用：PySide6 的包装对象被回收时 C++ 对象会跟着销毁。
        self.shell = _Shell(self.runtime)
        self.dialog = _Dialog(self.config, self.shell)
        self.controller = ModCenterController(DialogModHost(self.dialog))
        self.results: list[tuple[str, object]] = []
        self.controller.result.connect(lambda key, outcome: self.results.append((key, outcome)))

    @property
    def outcome(self):
        return self.results[-1][1]

    def rows(self):
        return [row for row in self.controller.entries() if row.kind == KIND_EXTENSION]

    def import_source(self, source, **kwargs) -> bool:
        started = self.controller.import_source(source, **kwargs)
        assert _pump(lambda: not self.controller.busy), "MOD 中心的操作没有收敛"
        return started

    def close(self) -> None:
        self.controller.close()
        self.runtime.close()


def _pump(predicate, *, timeout: float = 60.0) -> bool:
    """真事件循环 + 宽预算地等一个状态（不猜时序、不固定 sleep）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _center(tmp_path: Path) -> _Center:
    return _Center(tmp_path)


def _data_root(tmp_path: Path) -> Path:
    return Config(base=tmp_path).dir


def _package_root(tmp_path: Path, **kwargs) -> tuple[Path, Path]:
    return build(tmp_path / "pkg", **kwargs)


def _handmade_zip(tmp_path: Path, name: str, entries: dict[str, str]) -> Path:
    """手搓一个 ZIP——坏 manifest 的几种形状没法用打包脚本产出。"""
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w") as stream:
        for path, text in entries.items():
            stream.writestr(path, text)
    return archive


# ------------------------------------------------------------------ 正路径

def test_a_zip_package_imports_disabled_and_lists_in_the_mod_center(tmp_path):
    center = _center(tmp_path)
    try:
        package, archive = _package_root(tmp_path)
        assert center.import_source(archive) is True
        assert center.outcome.success is True
        rows = center.rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.id == OWNER and row.version == "1.0.0"
        assert row.name == "离线打招呼" and row.kind == KIND_EXTENSION
        assert row.enabled is False
        # 默认停用：装上了但没跑
        assert center.runtime.host.state(OWNER) == "disabled"
        assert center.runtime.mounts.runtimes == {}
        assert center.runtime.menu_owners() == ()
    finally:
        center.close()


def test_the_mod_center_enables_and_disables_a_zip_imported_package(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = _package_root(tmp_path)
        assert center.import_source(archive) is True
        key = center.rows()[0].key

        assert center.controller.perform("enable", [key]) is True
        assert _pump(lambda: not center.controller.busy and center.runtime.host.enabled(OWNER))
        assert center.rows()[0].enabled is True
        assert center.runtime.menu_owners() == (OWNER,)

        assert center.controller.perform("disable", [key]) is True
        assert _pump(lambda: not center.controller.busy and not center.runtime.host.enabled(OWNER))
        assert center.rows()[0].enabled is False
        # 停用不删安装副本
        assert center.runtime.managers[OWNER].service.inspect().active == "1.0.0"
    finally:
        center.close()


def test_the_zip_and_the_directory_of_the_same_package_are_one_install(tmp_path):
    """ZIP 与目录在 ``preflight`` 里归一成同一份 staged 目录 ⇒ 同版本同摘要 = 幂等。"""
    center = _center(tmp_path)
    try:
        package, archive = _package_root(tmp_path)
        assert center.import_source(archive) is True
        before = center.runtime.managers[OWNER].service.inspect()

        assert center.import_source(package) is True
        assert center.outcome.success is True and "已存在" in center.outcome.message
        after = center.runtime.managers[OWNER].service.inspect()
        assert (after.active, after.revision) == (before.active, before.revision)
        assert len(center.rows()) == 1
    finally:
        center.close()


# ------------------------------------------------------------------ 坏 manifest

def test_a_zip_with_an_incomplete_feature_manifest_is_refused(tmp_path):
    center = _center(tmp_path)
    try:
        archive = _handmade_zip(
            tmp_path,
            "broken.zip",
            {
                "manifest.json": json.dumps({"format_version": 2, "execution_kind": "host-only", "id": "demo.broken", "version": "1.0.0"}),
                "host/factory.py": "def create_host():\n    return None\n",
            },
        )
        assert center.controller.import_source(archive) is False
        assert center.outcome.success is False
        assert "清单" in center.outcome.message
        assert center.runtime.extensions() == {}
        assert center.rows() == []
        assert not (_data_root(tmp_path) / "plugins" / "demo.broken").exists()
    finally:
        center.close()


def test_a_zip_with_an_unparsable_manifest_is_refused(tmp_path):
    center = _center(tmp_path)
    try:
        archive = _handmade_zip(tmp_path, "junk.zip", {"manifest.json": "{ not json", "host/factory.py": ""})
        assert center.import_source(archive) is True  # 进队列了，由存储层判定
        assert center.outcome.success is False
        assert center.outcome.message.startswith("操作未完成")
        assert center.runtime.extensions() == {}
    finally:
        center.close()


# ------------------------------------------------------------------ 校验失败

def test_a_zip_whose_payload_bytes_changed_is_refused_by_the_verifier(tmp_path):
    """路由只读清单（它没变），所以拒点在验签那一环——正是它该拦的地方。"""
    center = _center(tmp_path)
    try:
        built, archive = _package_root(tmp_path)
        payload = built / "host" / "factory.py"
        payload.write_bytes(payload.read_bytes() + b"\n# tampered\n")
        rearchive(built)
        assert center.import_source(archive) is True
        assert center.outcome.success is False
        assert "package_verification_failed" in center.outcome.message
        info = center.runtime.managers[OWNER].service.inspect()
        assert info.active is None and info.pending_transaction is None
        assert not (center.runtime.managers[OWNER].service.store.root / "versions" / "1.0.0").exists()
    finally:
        center.close()


def test_a_bogus_signature_is_refused_by_the_signed_policy(tmp_path):
    """本地用户信任路径刻意不看 ``manifest.sig``（Phase5A 口径）；签名是**正式签名模式**
    的门——同一个验证器换到那条策略上，bogus 签名必须拒。"""
    package, _archive = _package_root(tmp_path)
    (package / "manifest.sig").write_bytes(b"\x00" * 64)
    signed = FeaturePackageVerifier(
        core_version=__version__,
        api_version="1",
        feature_id="official.screen-understanding",
        allowed_capabilities=frozenset({"screen.capture"}),
        allow_local_packages=False,
        platform=sys.platform,
        trust_anchors={"release": b"\x01" * 32},
    )
    try:
        signed.verify(package)
    except PackageVerificationError as exc:
        assert "signature" in str(exc)
    else:
        raise AssertionError("bogus 签名没有被拒")


# --------------------------------------------------------- 路由与 owner 隔离

def test_an_unknown_owner_is_routed_as_a_third_party_dlc(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = _package_root(tmp_path, owner=OTHER_OWNER, name="社区工具")
        route = route_local_package(archive)
        assert route.is_official is False
        # 未知 owner 照样路由成第三方：登记表里没有它就按 DLC 接受（Phase 5A §1）
        assert center.runtime.route(archive) == OTHER_OWNER
        assert list(center.runtime.extensions()) == [OTHER_OWNER]
        assert center.import_source(archive) is True
        assert center.outcome.success is True
        assert [row.id for row in center.rows()] == [OTHER_OWNER]
    finally:
        center.close()


def test_a_zip_claiming_an_official_owner_is_refused(tmp_path):
    """官方 ID 是保留的：本地 ZIP 占不了它的名字，也拿不到它的数据根。

    这份材料是手搓的：``scripts.build_mod_example`` 自己就会拒掉"借官方 ID"的包，
    所以这里直接给一个形状合法、声明官方 owner 的 ZIP——路由层只看有界清单，
    正是它该拦住的地方。
    """
    center = _center(tmp_path)
    try:
        archive = _handmade_zip(
            tmp_path,
            "official.zip",
            {
                "manifest.json": json.dumps(
                    {
                        "format_version": 2,
                        "execution_kind": "host-only",
                        "key_id": "local-user",
                        "id": OFFICIAL_OWNER,
                        "factory": "ai-chat/v1",
                        "version": "1.0.0",
                        "api_version": "1",
                        "core_requires": ">=1.0.0,<6.0.0",
                        "platforms": [sys.platform],
                        "capabilities": ["menu.contribute"],
                        "worker": None,
                        "files": {"host/factory.py": {"sha256": "0" * 64, "size": 22}},
                    }
                ),
                "host/factory.py": "def create_host():\n    return None\n",
            },
        )
        route = route_local_package(archive)
        assert route.is_official is True
        assert center.runtime.route(archive) is None
        assert center.runtime.extensions() == {}
        assert center.controller.import_source(archive) is False
        assert center.outcome.success is False
        assert "官方功能扩展的保留 ID" in center.outcome.message
        data_root = _data_root(tmp_path)
        assert not (data_root / "feature-data" / OFFICIAL_OWNER).exists()
        assert not (data_root / "plugins" / OFFICIAL_OWNER).exists()
    finally:
        center.close()


def test_two_third_party_owners_get_disjoint_owner_scoped_ports(tmp_path):
    center = _center(tmp_path)
    try:
        _package_a, archive_a = build(tmp_path / "a", owner=OWNER, name="甲")
        _package_b, archive_b = build(tmp_path / "b", owner=OTHER_OWNER, name="乙")
        assert center.import_source(archive_a) is True and center.outcome.success is True
        assert center.import_source(archive_b) is True and center.outcome.success is True
        assert sorted(center.runtime.extensions()) == sorted([OWNER, OTHER_OWNER])

        context_a = center.runtime.startup(OWNER).context
        context_b = center.runtime.startup(OTHER_OWNER).context
        assert context_a.owner == OWNER and context_b.owner == OTHER_OWNER
        context_a.configuration.commit_namespace({"greeting": "a"}, expected_revision=context_a.configuration.revision())
        assert context_a.configuration.read_namespace() == {"greeting": "a"}
        assert context_b.configuration.read_namespace() == {}  # 别人的命名空间看不见

        root = _data_root(tmp_path) / "feature-data"
        assert (root / OWNER / "configuration.json").is_file()
        assert not (root / OTHER_OWNER / "configuration.json").exists()
    finally:
        center.close()


def test_this_owners_manager_refuses_a_package_for_another_owner(tmp_path):
    center = _center(tmp_path)
    try:
        _package_a, archive_a = build(tmp_path / "a", owner=OWNER)
        _package_b, archive_b = build(tmp_path / "b", owner=OTHER_OWNER)
        assert center.import_source(archive_a) is True
        manager = center.runtime.managers[OWNER]
        seen: list = []
        manager.result_ready.connect(seen.append)
        assert manager.submit_local_source(archive_b, auto_apply=True, enabled=False) is False
        assert _pump(lambda: bool(seen))
        assert seen[-1].reason == "local_package_target_invalid"
        assert not (_data_root(tmp_path) / "plugins" / OTHER_OWNER).exists()
    finally:
        center.close()


def test_a_zip_in_a_path_with_spaces_and_non_ascii_is_imported(tmp_path):
    """路径里有空格与中文是 Windows 上的常规现实（安装目录、桌面都在这一类路径下）。

    这条同时压到两段：事务层的暂存/版本目录，以及探针把包路径经 argv 交给子进程的那一段。
    """
    center = _center(tmp_path)
    try:
        source = tmp_path / "功能 包 目录"
        _package, archive = build(source, owner=OWNER, name="带空格的包")
        assert archive.is_file()
        assert center.import_source(archive) is True
        assert center.outcome.success is True
        assert [row.id for row in center.rows()] == [OWNER]
        context = center.runtime.startup(OWNER).context
        context.configuration.commit_namespace({"greeting": "ok"}, expected_revision=context.configuration.revision())
        assert context.configuration.read_namespace() == {"greeting": "ok"}
    finally:
        center.close()


# ------------------------------------------------- 重复安装与版本解析

def test_reimporting_the_same_zip_is_idempotent(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = _package_root(tmp_path)
        assert center.import_source(archive) is True
        manager = center.runtime.managers[OWNER]
        before = manager.service.inspect()
        assert center.import_source(archive) is True
        assert center.outcome.success is True and center.outcome.message == "已存在，不重复导入"
        after = manager.service.inspect()
        assert (after.active, after.revision) == (before.active, before.revision)
    finally:
        center.close()


def test_a_newer_zip_version_upgrades_and_keeps_the_previous(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = build(tmp_path / "v1", owner=OWNER, version="1.0.0")
        assert center.import_source(archive) is True
        _package, newer = build(tmp_path / "v2", owner=OWNER, version="1.0.1")
        assert center.import_source(newer) is True
        assert center.outcome.success is True
        info = center.runtime.managers[OWNER].service.inspect()
        assert (info.active, info.previous) == ("1.0.1", "1.0.0")
        assert [row.version for row in center.rows()] == ["1.0.1"]
    finally:
        center.close()


def test_a_zip_with_the_same_version_but_other_bytes_is_refused(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = build(tmp_path / "v1", owner=OWNER, version="1.0.0")
        assert center.import_source(archive) is True
        tree = source_tree(tmp_path / "same-version", owner=OWNER, version="1.0.0")
        factory = tree / "host" / "factory.py"
        factory.write_bytes(factory.read_bytes() + b"\n# same version, other bytes\n")
        _package, other = build_tree(tree, tmp_path / "built")
        assert center.import_source(other) is True
        assert center.outcome.success is False
        assert "same_version_different_digest" in center.outcome.message
        assert center.runtime.managers[OWNER].service.inspect().active == "1.0.0"
    finally:
        center.close()


def test_a_downgrading_zip_is_refused(tmp_path):
    center = _center(tmp_path)
    try:
        _package, archive = build(tmp_path / "new", owner=OWNER, version="1.0.1")
        assert center.import_source(archive) is True
        _package, older = build(tmp_path / "old", owner=OWNER, version="1.0.0")
        assert center.import_source(older) is True
        assert center.outcome.success is False
        assert "downgrade_not_proven_compatible" in center.outcome.message
        assert center.runtime.managers[OWNER].service.inspect().active == "1.0.1"
    finally:
        center.close()


# --------------------------------------------------- 探针：装之前就拒

def test_a_zip_whose_host_code_does_not_import_is_refused_before_install(tmp_path):
    center = _center(tmp_path)
    try:
        tree = source_tree(tmp_path / "src")
        (tree / "host" / "factory.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        _package, archive = build_tree(tree, tmp_path / "built")
        assert center.import_source(archive) is True  # 清单与摘要都对，路由与预检都过得去
        assert center.outcome.success is False
        assert "probe_import_failed" in center.outcome.message
        info = center.runtime.managers[OWNER].service.inspect()
        assert info.active is None and info.pending_transaction is None
        assert center.rows() == []
    finally:
        center.close()


def test_a_zip_whose_code_claims_another_owner_is_refused_before_install(tmp_path):
    center = _center(tmp_path)
    try:
        tree = source_tree(tmp_path / "src")
        factory = tree / "host" / "factory.py"
        factory.write_text(factory.read_text("utf-8").replace(f'OWNER = "{OWNER}"', 'OWNER = "demo.impostor"'), "utf-8")
        _package, archive = build_tree(tree, tmp_path / "built")
        assert center.import_source(archive) is True
        assert center.outcome.success is False
        assert "probe_owner_mismatch" in center.outcome.message
        assert center.runtime.managers[OWNER].service.inspect().active is None
    finally:
        center.close()
