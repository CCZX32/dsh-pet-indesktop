# -*- coding: utf-8 -*-
"""宿主缝 ``feature_route(source)``：修「首次安装永远进不去」的死锁。

注册表由**安装状态**导出，而安装状态只能通过导入改变——所以「这个 id 还没注册」
不能反过来否掉一次导入。宿主在这一步答得出 owner，就把包交给那个 owner 的管理器；
答不出来（没有这个缝，或返回 ``None``）保持现状：如实说清哪一环没接上。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pet import catalog
from pet.mod_center_controller import KIND_EXTENSION, ModCenterController

from tests.test_mod_center_controller import ExtensionHost, Host, _extension_env, _feature_package, pump


@pytest.fixture
def env(tmp_path, monkeypatch):
    """与 ``tests/test_mod_center_controller.py`` 同一口径的托管根夹具。"""
    data_root = tmp_path / "dsh-pet-standalone"
    managed = data_root / "characters"
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [managed])
    return data_root, managed


class RoutingHost(Host):
    """宿主缝替身：路由命中时**当场**把管理器装进注册表（生产侧就是这一步）。"""

    def __init__(self, env, route):
        super().__init__(env[0])
        self.env, self.route = env, route
        self.routed: list[Path] = []
        self.managers: dict = {}

    def extensions(self):
        return dict(self.managers)

    def feature_route(self, source):
        self.routed.append(Path(source))
        if self.route is None:
            return None
        self.managers.setdefault(self.route, _extension_env(self.env, active="1.0.0"))
        return self.route


def _routing_controller(env, route):
    host = RoutingHost(env, route)
    return ModCenterController(host), host


def test_a_first_install_routes_by_declared_id_before_the_registry_knows_it(env):
    controller, host = _routing_controller(env, "official.demo")
    results = []
    controller.result.connect(lambda key, outcome: results.append((key, outcome)))
    package = _feature_package(env[0] / "incoming")
    assert controller.extensions == {}  # 注册表里还没有它——这正是死锁现场
    assert controller.import_source(package) is True
    pump(lambda: not controller.busy)
    assert host.routed == [package]
    assert results[-1][0] == KIND_EXTENSION + ":official.demo"
    assert results[-1][1].success
    assert controller.extensions["official.demo"].imported == [(package, True, False)]


def test_a_route_that_answers_nothing_keeps_the_existing_refusal(env):
    controller, host = _routing_controller(env, None)
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.import_source(_feature_package(env[0] / "incoming")) is False
    assert host.routed  # 问过了，答案是没有
    assert not results[-1].success
    assert "还没有接上" in results[-1].message


def test_a_route_for_another_package_is_not_trusted(env):
    """宿主报的 owner 与包自己声明的 id 不一致 ⇒ 不路由，落到如实拒绝。"""
    controller, host = _routing_controller(env, "official.other")
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    package = _feature_package(env[0] / "incoming")
    assert controller.import_source(package) is False
    assert host.routed == [package]  # 问过了
    assert not results[-1].success
    assert "official.other" not in controller.extensions
    assert "还没有接上" in results[-1].message


def test_an_update_routed_to_another_package_is_refused(env):
    controller, _host = _routing_controller(env, "official.demo")
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.import_source(_feature_package(env[0] / "incoming"), expected=KIND_EXTENSION + ":official.other") is False
    assert "不是同一个包" in results[-1].message


def test_a_host_without_the_seam_behaves_exactly_as_before(env):
    manager = _extension_env(env)
    host = ExtensionHost(env[0], {"official.demo": manager})
    assert not hasattr(host, "feature_route")
    controller = ModCenterController(host)
    results = []
    controller.result.connect(lambda key, outcome: results.append(outcome))
    assert controller.import_source(_feature_package(env[0] / "incoming")) is True
    pump(lambda: not controller.busy)
    assert manager.imported and results[-1].success
