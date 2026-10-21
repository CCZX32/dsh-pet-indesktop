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
