"""点击显示余额：左键点击必须按「被点那只」的 slot 异步请求。

实现分布在三处：`petcore/config.py` 的 `click_show_balance`（按 slot）、
`petcore/ui/pet_window.py::_maybe_request_click_balance`（点击触发）、
`petcore/ui/app.py::request_balance`（缓存 + 单飞 + 气泡/岛反馈）。
本文件只钉住点击这一跳：点击线程不许自己做网络 I/O，只提交请求。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.pet_window import PetWindow


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.balance_calls: list[tuple[int | None, bool]] = []

    def characters(self):
        return list(self._characters)

    def build_menu(self, parent=None):
        return None

    def open_settings(self, initial_page=None, window=None):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        return None

    def request_balance(self, slot=None, *, force=True):
        self.balance_calls.append((slot, force))


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path, host: FakeHost, *, slot: int = 0, enabled: bool = True) -> PetWindow:
    character = fallback()
    config = Config(
        tmp_path,
        {
            "character": "fallback",
            "scale": 0.5,
            "no_move": True,
            "click_show_balance": enabled,
        },
    )
    window = PetWindow(config, tmp_path, host, slot=slot)
    window.start(character)
    return window


def test_click_requests_balance_for_the_clicked_pet(app, tmp_path: Path) -> None:
    host = FakeHost([fallback()])
    window = _window(tmp_path, host, slot=1)
    try:
        window._on_click()  # noqa: SLF001 - 点击入口
        assert host.balance_calls == [(1, True)]
    finally:
        window.shutdown()


def test_click_without_the_option_never_requests(app, tmp_path: Path) -> None:
    host = FakeHost([fallback()])
    window = _window(tmp_path, host, enabled=False)
    try:
        window._on_click()  # noqa: SLF001
        assert host.balance_calls == []
    finally:
        window.shutdown()


def test_click_balance_failure_does_not_break_the_click(app, tmp_path: Path) -> None:
    """余额端口抛错只记日志：点击动画与监听者必须照常跑完。"""

    host = FakeHost([fallback()])
    window = _window(tmp_path, host)
    seen: list[object] = []
    window.add_click_listener(lambda pet: seen.append(pet))

    def boom(slot=None, *, force=True):
        raise RuntimeError("balance exploded")

    host.request_balance = boom  # type: ignore[method-assign]
    try:
        window._on_click()  # noqa: SLF001
        assert seen == [window]
    finally:
        window.shutdown()


def test_thrown_pet_does_not_consume_the_balance_option(app, tmp_path: Path) -> None:
    """飞行中不消费点击（主分支同口径），因此也不该发余额请求。"""

    from petcore.ui.motion import MotionController

    host = FakeHost([fallback()])
    window = _window(tmp_path, host)
    try:
        window.motion = MotionController(window, clock=lambda: 100.0)
        window.motion.set_velocity(-300.0, 0.0)
        assert window.motion.thrown is True
        window._on_click()  # noqa: SLF001
        assert host.balance_calls == []
    finally:
        window.shutdown()
