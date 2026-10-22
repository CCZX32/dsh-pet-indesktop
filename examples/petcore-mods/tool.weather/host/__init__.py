"""tool.weather 的入口：只做依赖组装。"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from .runtime import WeatherRuntime
from .settings_page import WeatherPage

OWNER = "tool.weather"

__all__ = ["WeatherPage", "WeatherRuntime", "create_host"]


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="menu",
                id="show",
                data={"label": "天气", "command": "show", "order": 84, "icon": "weather"},
            ),
            Contribution(
                kind="settings_page",
                id="weather",
                data={"title": "天气", "order": 680, "icon": "weather"},
            ),
        ),
        runtime_factory=WeatherRuntime,
        settings_factory=WeatherPage,
    )
