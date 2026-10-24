from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from .runtime import FestivalRuntime
from .settings_page import FestivalPage


def create_host(_context):
    holder = {}
    def runtime_factory(context):
        holder["runtime"] = FestivalRuntime(context)
        return holder["runtime"]
    return FeatureDefinition(
        owner="fun.festival",
        contributions=(
            Contribution(kind="menu", id="today", data={"label": "今日节日", "command": "today", "order": 87, "icon": "todo"}),
            Contribution(kind="settings_page", id="festival", data={"title": "节日提醒", "order": 650, "icon": "todo"}),
        ),
        runtime_factory=runtime_factory,
        settings_factory=lambda host: FestivalPage(host, runtime=holder.get("runtime")),
    )
