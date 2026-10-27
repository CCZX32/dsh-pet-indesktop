"""扩展命令按发起桌宠派发：声明了 slot 的命令必须收到发起者。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from petcore.ui.app import _invoke_feature_command


def test_slot_is_passed_only_when_the_command_accepts_it() -> None:
    received: list[int] = []
    plain: list[str] = []

    def with_slot(slot=None):
        received.append(-1 if slot is None else int(slot))

    def without_slot():
        plain.append("called")

    _invoke_feature_command(with_slot, 3)
    _invoke_feature_command(without_slot, 3)
    _invoke_feature_command(with_slot, None)

    assert received == [3, -1]
    assert plain == ["called"]


def test_feature_menu_items_route_to_the_pet_that_opened_the_menu() -> None:
    """菜单项（现在 AI 三项也走这条路）必须带上「当前右键的是哪只桌宠」。

    子宠的 AI 对话/截图提问落在主宠窗口上，是 L108 之前就存在的风险点：
    ``_register_feature_menus`` 的 callback 原来不带 slot。
    """
    from types import SimpleNamespace

    from petcore.ui.app import CoreHost

    seen: list[tuple[str, str, int | None]] = []

    def command(slot=None):
        seen.append(("ai.chat", "open", slot))

    stub = SimpleNamespace(
        features=SimpleNamespace(command=lambda owner, cid: command),
        _active_window=SimpleNamespace(slot=3),
        window=SimpleNamespace(slot=0),
    )

    CoreHost._run_feature_command(stub, "ai.chat", "open", CoreHost._menu_slot(stub))

    assert seen == [("ai.chat", "open", 3)], "菜单命令应落在打开菜单的那只桌宠上"


def test_menu_slot_falls_back_to_the_primary_window() -> None:
    from types import SimpleNamespace

    from petcore.ui.app import CoreHost

    stub = SimpleNamespace(_active_window=None, window=SimpleNamespace(slot=0))
    assert CoreHost._menu_slot(stub) == 0

    bare = SimpleNamespace(_active_window=None, window=None)
    assert CoreHost._menu_slot(bare) is None
