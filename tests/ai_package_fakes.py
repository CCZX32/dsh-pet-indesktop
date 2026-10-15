# -*- coding: utf-8 -*-
"""官方 AI 对话包测试的共享装配：真打包（build_ai_chat_package）+ 真验签装载。

与 ``screen_package_fakes`` 同一套纪律：独立于内置聊天的配置与凭据后端走内存实现
（绝不碰真实钥匙串）；包代码只经 ``FeaturePackageLoader`` 的验签字节导入。
"""

from __future__ import annotations

from pathlib import Path

from pet.feature_policy import official_package_verifier
from pet.official_features import AI_FEATURE_ID
from pet.plugins.feature_packages import FeaturePackageLoader

OWNER = AI_FEATURE_ID
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "features" / "ai-chat"


class MemoryVault:
    """内存凭据后端（``pet.credentials.secure_backend`` 的替身）。"""

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
    from scripts.build_ai_chat_package import build_package as build

    return build(PACKAGE_SOURCE, target_dir)


def load_host(built: Path):
    """验签 + 装载宿主代码（只调 ``create_host``，不执行其它包代码）。"""
    verifier = official_package_verifier(OWNER)
    descriptor = verifier.verify(built)
    loader = FeaturePackageLoader(verifier)
    handle = loader.load_host(descriptor)
    return loader, descriptor, handle


def import_pkg(handle, dotted: str):
    """按装载命名空间取包内模块（``host.runtime`` / ``host.chat.service`` …）。"""
    import importlib

    return importlib.import_module(handle.namespace + "." + dotted)


class FakePetView:
    """桌宠呈现面的假货：生产是 AppShell 注册的聊天窗宿主形态。

    记录气泡/告警/状态/位置订阅，几何固定——包读的就这几样，别的一概没有。
    """

    def __init__(self, *, visible=True):
        self._visible = visible
        self.bubbles: list = []
        self.alerts: list = []
        self.resolved: list = []
        self.statuses: list = []
        self.listeners: list = []

    def visible_content_rect(self):
        from PySide6.QtCore import QRect

        return QRect(100, 100, 180, 200) if self._visible else QRect()

    def frameGeometry(self):
        from PySide6.QtCore import QRect

        return QRect(90, 90, 200, 220)

    def icon_pixmap(self, size=64):
        from PySide6.QtGui import QPixmap

        return QPixmap()

    def set_chat_status(self, state, text=""):
        self.statuses.append((state, text))

    def add_position_listener(self, callback):
        self.listeners.append(callback)

    def remove_position_listener(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def show_alert(self, text, **options):
        self.alerts.append((text, options))

    def resolve_alert(self, identity):
        self.resolved.append(identity)

    def show_bubble(self, text, duration_ms=3200):
        self.bubbles.append((text, duration_ms))


def assert_not_frozen_source_leak() -> None:
    """打包后的 ``sys.path`` 不被装载链污染（与识屏包同一条命题）。"""
    import sys

    assert not any("ai-chat" in entry for entry in sys.path)


def dispose_qobject(obj) -> None:
    """收口包 Runtime 的窗口与线程（进程退出时访问违规的既有教训）。"""
    if obj is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent

    runtime = getattr(obj, "runtime", None)
    for window in list(getattr(runtime, "_windows", None) or ()):
        try:
            window.close()
            window.deleteLater()
        except Exception:
            pass
    close = getattr(obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
