# -*- coding: utf-8 -*-
"""Core 侧的聊天包呈现面（``pet/ai_bindings.py``）：受限面 + 进程级提供方解析。

包要的不是桌宠本体，而是"在哪、头像、聊天状态、位置变动通知"四样。这里验的就是
这条边界：面里给出去的全是应用产出的**值**；提供方缺失、返回 None、返回已销毁的
QObject、或者那个窗口自己没实现某个方法，一律安全降级，绝不抛给包。

生产装配（``AppShell._build_feature_runtime`` 注册 → ``_ai_pet_view`` 解析主实例
的聊天宿主）在最后一段用**真方法**验：不建整只桌宠，只给它一个实例壳。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect
from PySide6.QtWidgets import QApplication

from pet.ai_bindings import AiFileView, AiPetView, ai_pet_view, register_ai_pet_view

app = QApplication.instance() or QApplication([])


class _FakeWindow(QObject):
    """PetWindow 形的假货：几何固定，记录状态与位置订阅。"""

    def __init__(self):
        super().__init__()
        self.statuses: list = []
        self.listeners: list = []
        self.alerts: list = []
        self.resolved: list = []
        self.bubbles: list = []

    def visible_content_rect(self):
        return QRect(10, 20, 180, 200)

    def frameGeometry(self):
        return QRect(5, 15, 190, 210)

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


@pytest.fixture
def provider():
    register_ai_pet_view(None)
    yield register_ai_pet_view
    register_ai_pet_view(None)


# --------------------------------------------------------------- 提供方解析


def test_without_a_provider_the_package_gets_nothing(provider):
    assert ai_pet_view() is None


def test_a_provider_returning_none_is_treated_as_no_pet(provider):
    provider(lambda: None)
    assert ai_pet_view() is None


def test_a_non_callable_provider_is_refused(provider):
    with pytest.raises(TypeError):
        provider(object())


def test_the_provider_is_resolved_lazily_each_time(provider):
    """解析发生**每次开窗**，不是绑定那一刻——换窗后包跟的是新窗。"""
    first, second = _FakeWindow(), _FakeWindow()
    current = {"window": first}
    provider(lambda: current["window"])
    assert ai_pet_view().visible_content_rect() == QRect(10, 20, 180, 200)
    current["window"] = second
    assert ai_pet_view()._live() is second


def test_a_destroyed_pet_is_not_handed_to_the_package(provider):
    window = _FakeWindow()
    provider(lambda: window)
    assert ai_pet_view() is not None
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert ai_pet_view() is None


def test_a_provider_that_raises_degrades_instead_of_propagating(provider):
    def boom():
        raise RuntimeError("宿主装配炸了")

    provider(boom)
    assert ai_pet_view() is None


# --------------------------------------------------------------- 受限面


def test_the_pet_view_reports_geometry_and_forwards_status(provider):
    window = _FakeWindow()
    provider(lambda: window)
    view = ai_pet_view()
    assert isinstance(view, AiPetView)
    assert view.visible_content_rect() == QRect(10, 20, 180, 200)
    assert view.frameGeometry() == QRect(5, 15, 190, 210)
    view.set_chat_status("thinking", "正在想")
    assert window.statuses == [("thinking", "正在想")]


def test_position_subscription_round_trips(provider):
    window = _FakeWindow()
    provider(lambda: window)
    view = ai_pet_view()
    listener = lambda: None  # noqa: E731 - 订阅的是可调用对象本身
    view.add_position_listener(listener)
    assert window.listeners == [listener]
    view.remove_position_listener(listener)
    assert window.listeners == []


def test_the_view_degrades_when_the_window_lacks_a_method():
    """窗口只实现了呈现面的一个子集时：缺的那几样返回空值，不 AttributeError。"""

    class _Bare(QObject):
        pass

    view = AiPetView.of(_Bare())
    assert view.visible_content_rect() == QRect()
    assert view.icon_pixmap(32).isNull()
    view.set_chat_status("success")  # 不炸
    view.add_position_listener(lambda: None)


def test_the_view_degrades_after_the_window_is_gone():
    window = _FakeWindow()
    view = AiPetView.of(window)
    del window
    assert view.visible_content_rect() == QRect()
    assert view.frameGeometry() == QRect()
    assert view.icon_pixmap(32).isNull()
    assert view._live() is None


def test_the_pet_view_is_a_weak_reference_not_a_strong_one():
    """呈现面不许把桌宠窗口的寿命延长（否则关窗后那个 QObject 永远不释放）。"""
    window = _FakeWindow()
    view = AiPetView.of(window)
    assert view._live() is window


# --------------------------------------------------------------- 文件解读面


def test_the_file_view_carries_the_package_config_plus_bubbles(provider):
    window = _FakeWindow()
    provider(lambda: window)
    config = object()
    view = AiFileView(ai_pet_view(), config)
    assert view.cfg is config
    assert view.visible_content_rect() == QRect(10, 20, 180, 200)  # 几何仍是桌宠的
    view.show_alert("要解读这个文件吗？", sticky=True)
    view.resolve_alert("file-interpret")
    view.show_bubble("正在解读…", duration_ms=1200)
    assert window.alerts == [("要解读这个文件吗？", {"sticky": True})]
    assert window.resolved == ["file-interpret"]
    assert window.bubbles == [("正在解读…", 1200)]


def test_the_file_view_accepts_a_raw_window_too(provider):
    """生产路径传的是聊天宿主本体（不是已包装的 AiPetView）。"""
    window = _FakeWindow()
    view = AiFileView(window, object())
    assert view._live() is window


# --------------------------------------------------------------- 生产装配


def test_the_shell_resolves_the_primary_instance_chat_host():
    """``AppShell._ai_pet_view``：主实例的聊天宿主就是给包的呈现面。

    这里是**真方法**（不是同名替身）：给它一个实例壳，验的是"主窗优先、
    ``_chat_host()`` 优先于裸 ``win``、没有实例时回 None"这三条。
    """
    from pet.app import AppShell
    from types import SimpleNamespace

    host = _FakeWindow()
    instance = SimpleNamespace(win=object(), _chat_host=lambda: host)
    assert AppShell._ai_pet_view(SimpleNamespace(instance=instance)) is host

    # ``_chat_host`` 缺失时退回裸 win（legacy 拓扑的等价物）
    bare = object()
    assert AppShell._ai_pet_view(SimpleNamespace(instance=SimpleNamespace(win=bare, _chat_host=None))) is bare

    assert AppShell._ai_pet_view(SimpleNamespace(instance=None)) is None
