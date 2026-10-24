from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from .runtime import TodoRuntime
from .settings_page import TodoPage


def create_host(_context):
    holder = {}
    def runtime_factory(context):
        holder["runtime"] = TodoRuntime(context)
        return holder["runtime"]
    return FeatureDefinition(
        owner="reminder.todo",
        contributions=(
            Contribution(kind="menu", id="open", data={"label": "待办提醒", "command": "open", "order": 88, "icon": "todo"}),
            Contribution(kind="settings_page", id="todo", data={"title": "待办", "order": 660, "icon": "todo"}),
        ),
        runtime_factory=runtime_factory,
        settings_factory=lambda host: TodoPage(host, runtime=holder.get("runtime")),
    )
