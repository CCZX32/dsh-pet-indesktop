# -*- coding: utf-8 -*-
"""官方识屏包测试的共享装配：真打包（build_screen_package）+ 真验签装载。

与上游 ``tests/screen_fakes.py`` 同纪律：独立视觉配置走内存凭据后端，
绝不碰真实钥匙串；包代码只经 ``FeaturePackageLoader`` 的验签字节导入。
"""

from __future__ import annotations

import sys
from pathlib import Path

from pet.feature_policy import official_package_verifier
from pet.official_features import SCREEN_FEATURE_ID
from pet.plugins.feature_packages import FeaturePackageLoader

OWNER = SCREEN_FEATURE_ID
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "features" / "screen-understanding"


class MemoryVault:
    priority = 1

    def __init__(self):
        self.items = {}
        self.fail = False

    def set_password(self, service, ref, value):
        if self.fail:
            raise RuntimeError("TEST-SECRET backend write failed")
        self.items[service, ref] = value

    def get_password(self, service, ref):
        if self.fail:
            raise RuntimeError("TEST-SECRET backend read failed")
        return self.items.get((service, ref))

    def delete_password(self, service, ref):
        self.items.pop((service, ref), None)


def build_package(target_dir: Path) -> Path:
    """真打包：从仓库里的作者源码树组装 + 官方验签（与发布同一道门）。"""
    from scripts.build_screen_package import build_package as build

    return build(PACKAGE_SOURCE, target_dir)


def load_host(built: Path):
    """验签 + 装载宿主代码（不调用 create_host 以外的包代码）。"""
    verifier = official_package_verifier(OWNER)
    descriptor = verifier.verify(built)
    loader = FeaturePackageLoader(verifier)
    handle = loader.load_host(descriptor)
    return loader, descriptor, handle


def import_pkg(handle, dotted: str):
    """按装载命名空间取包内模块（``host.runtime`` / ``common.policy`` …）。"""
    import importlib

    return importlib.import_module(handle.namespace + "." + dotted)


class FakePresentation:
    """进程级呈现提供方假货：MultiWindowProxy 语义面。"""

    def __init__(self, *, visible=True):
        self._visible = visible
        self.bubbles: list = []
        self.holds: list = []
        self.synced: list = []
        self.agent_link_manager = None
        self.mouse_through = False

    def isVisible(self):
        return self._visible

    def show_bubble(self, text, duration_ms=4500):
        self.bubbles.append((text, duration_ms))

    def hold_bubble(self, seconds):
        self.holds.append(seconds)

    def on_look_synced(self, user_text, reply):
        self.synced.append((user_text, reply))


def dispose_qobject(obj) -> None:
    """收口 watcher/manual 的桥接 QObject（进程退出时访问违规的既有教训）。"""
    from PySide6.QtCore import QCoreApplication, QEvent

    for holder in (obj, getattr(obj, "watcher", None), getattr(obj, "manual", None)):
        bridge = getattr(holder, "_bridge", None)
        if bridge is not None:
            QCoreApplication.sendPostedEvents(bridge, QEvent.Type.DeferredDelete)


def assert_not_frozen_source_leak() -> None:
    """打包后的 sys.path 不被装载链污染（上游同名命题）。"""
    assert not any("screen-understanding" in entry for entry in sys.path)
