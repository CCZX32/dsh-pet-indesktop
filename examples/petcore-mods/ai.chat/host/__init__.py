"""ai.chat 的入口：只做依赖组装，不放业务逻辑。"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from .constants import OWNER
from .runtime import AiChatRuntime
from .settings_page import AiChatPage

__all__ = ["AiChatPage", "AiChatRuntime", "create_host"]


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="settings_page",
                id="chat",
                data={"title": "AI 对话", "order": 640, "icon": "chat"},
            ),
        ),
        runtime_factory=AiChatRuntime,
        settings_factory=AiChatPage,
    )
