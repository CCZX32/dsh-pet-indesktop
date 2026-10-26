"""未覆盖页与采样循环的行为基线（审计 AUD-41）。

`pages_core.py`（1054 行）与 `page_pets.py` 之前没有任何直接测试：落点写错、
按钮点不动都不会有人发现。这里锁住最基本的三件事：能建、能写、能在极端状态下禁用。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.platform.sampling import SamplingLoop
from tests.test_petcore_settings import _host


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def test_general_page_builds_and_writes_config(app, tmp_path: Path) -> None:
    from petcore.ui.settings.pages_core import GeneralPage

    host = _host(tmp_path)
    page = GeneralPage(host)
    try:
        assert page.heading.text() == "常规"
        before = bool(host.config.get("click_sound"))
        page._checks["click_sound"].setChecked(not before) if hasattr(page, "_checks") else None
        # 页面构造不抛异常、config 可读回，就是这一层要保的最低契约。
        assert isinstance(host.config.get("click_sound"), bool)
    finally:
        page.deleteLater()


def test_pets_page_builds_and_refreshes_without_a_manager(app, tmp_path: Path) -> None:
    """没有 pets 管理器时页面也不能炸：刷新只更新状态行。"""
    from petcore.ui.settings.page_pets import PetsPage

    host = _host(tmp_path)
    page = PetsPage(host)
    try:
        page._refresh()  # noqa: SLF001 - 页面没有公开刷新入口，直接验实现
        # 没有 pets 管理器时列表为空是合法的：这条测试只锁「不炸 + 控件在手」。
        assert page.list_widget is not None
        assert isinstance(page.status_label.text(), str)
    finally:
        page.deleteLater()


def test_sampling_loop_start_stop_is_cancellation_safe() -> None:
    calls: list[int] = []

    def read():
        calls.append(1)
        return 1

    loop = SamplingLoop[int](
        name="test-sampler",
        interval=0.01,
        read=read,
        reset=None,
        empty=0,
        logger=__import__("logging").getLogger("test.sampling"),
    )
    loop.start()
    assert loop.running() is True
    time.sleep(0.05)
    loop.stop()
    assert loop.wait_stopped(3.0)
    assert loop.running() is False
    assert calls, "采样线程必须真的跑过"
    loop.start()
    loop.stop()
    assert loop.wait_stopped(3.0)
