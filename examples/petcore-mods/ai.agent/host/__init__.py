"""ai.agent 的入口：只做依赖组装，不放业务逻辑。"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from .constants import OWNER
from .runtime import AgentLinkRuntime
from .settings_page import AgentLinkPage

__all__ = ["AgentLinkPage", "AgentLinkRuntime", "create_host"]


def create_host(context):
    def agent_enabled() -> bool:
        port = getattr(getattr(context, "ports", None), "config", None)
        getter = getattr(port, "get", None)
        if not callable(getter):
            return False
        try:
            return bool(getter("ai_agent_enabled", False))
        except Exception:
            return False

    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="settings_page",
                id="agent",
                data={"title": "Agent 联动", "order": 660, "icon": "agent"},
            ),
            Contribution(
                kind="menu",
                id="enabled",
                data={
                    "label": "Agent 联动",
                    "command": "agent_toggle",
                    "order": 56,
                    "icon": "agent",
                    "checked": agent_enabled,
                },
            ),
        ),
        runtime_factory=AgentLinkRuntime,
        settings_factory=AgentLinkPage,
    )
