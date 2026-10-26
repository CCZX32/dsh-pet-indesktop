"""动画/图/模式枚举：**契约层**的类型。

这些枚举是 mod 与 core 的公共词汇（`AnimationSpec` 直接用它们），所以必须住在
`contracts/`：`engine/` 只依赖标准库，`contracts/` 只依赖自己——两边都能引用。
`petcore/engine/enums.py` 仍然 re-export，历史 import 不用改。
"""

from __future__ import annotations

from enum import Enum


class GraphType(str, Enum):
    DEFAULT = "Default"
    EVENT = "Event"
    IDEL = "Idel"
    MOVE = "Move"
    TOUCH_HEAD = "Touch_Head"
    TOUCH_BODY = "Touch_Body"
    RAISED_STATIC = "Raised_Static"
    RAISED_DYNAMIC = "Raised_Dynamic"
    SAY = "Say"
    SLEEP = "Sleep"
    STARTUP = "StartUP"
    WORK = "Work"


class AnimatType(str, Enum):
    SINGLE = "Single"
    A_START = "A_Start"
    B_LOOP = "B_Loop"
    C_END = "C_End"


class ModeType(str, Enum):
    HAPPY = "Happy"
    NOMAL = "Nomal"
    POOR_CONDITION = "PoorCondition"
    ILL = "Ill"


__all__ = ["AnimatType", "GraphType", "ModeType"]
