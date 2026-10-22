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
