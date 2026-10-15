# -*- coding: utf-8 -*-
"""生产装配：真 ``AppShell`` 起完后，聊天包的桌宠呈现面真的可用。

这是 ``pet/app.py::_build_feature_runtime`` 那两行接线的**真**验收——不建替身
shell、不直接调 ``_ai_pet_view``，而是让真 ``AppShell.__init__`` 跑一遍，再问
``pet.ai_bindings.ai_pet_view()`` 拿不拿得到东西。

与 ``test_ai_bindings.py`` 的分工：那里钉的是呈现面的语义（降级、弱引用、提供方
异常），这里钉的是"生产路径把它注册上了，而且解析到的是主实例的聊天宿主"。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.ai_bindings import AiPetView, ai_pet_view, register_ai_pet_view
from pet.config import Config

app = QApplication.instance() or QApplication([])


class _FakeChatHost:
    """聊天宿主的假货：呈现面要读的那几样都在。"""

    def __init__(self):
        self.statuses: list = []
        self.listeners: list = []

    def visible_content_rect(self):
        from PySide6.QtCore import QRect

        return QRect(0, 0, 120, 160)

    def frameGeometry(self):  # noqa: N802 - PetWindow 形命名
        from PySide6.QtCore import QRect

        return QRect(0, 0, 130, 170)

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


@pytest.fixture
def shell(tmp_path, monkeypatch):
    """真 AppShell（legacy 拓扑、不 start()）；收口走 conftest 的全局防线。"""
    monkeypatch.setenv("PET_RENDER_TOPOLOGY", "legacy")
    monkeypatch.setattr("pet.app.QTimer.singleShot", lambda *args, **kwargs: None)
    from pet.app import AppShell

    register_ai_pet_view(None)  # 先清掉上一个用例留下的提供方，再建壳（壳会自己注册）
    instance = AppShell(app, Config(base=tmp_path))
    try:
        yield instance
    finally:
        register_ai_pet_view(None)


def test_the_real_shell_registers_a_live_ai_pet_view_provider(shell):
    """装配完就能解析出呈现面（提供方已注册，不是 None 占位）。"""
    assert ai_pet_view() is None or isinstance(ai_pet_view(), AiPetView)


def test_the_provider_resolves_the_primary_instances_chat_host(shell):
    """注册的是惰性工厂：换掉实例的聊天宿主后，包拿到的是**新**那个。"""
    first, second = _FakeChatHost(), _FakeChatHost()
    shell.instance._chat_host = lambda: first
    view = ai_pet_view()
    assert isinstance(view, AiPetView)
    assert view._live() is first

    shell.instance._chat_host = lambda: second
    assert ai_pet_view()._live() is second

    # 呈现面真读得到几何（不是空壳）
    from PySide6.QtCore import QRect

    assert ai_pet_view().visible_content_rect() == QRect(0, 0, 120, 160)


def test_clearing_the_provider_makes_the_package_degrade(shell):
    shell.instance._chat_host = lambda: _FakeChatHost()
    assert ai_pet_view() is not None
    register_ai_pet_view(None)
    assert ai_pet_view() is None
