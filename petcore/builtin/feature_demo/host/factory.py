from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition


class HelloRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"hello": self.hello}

    def hello(self) -> None:
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say("你好，我是 core 的扩展接口演示。")
            presentation.play_animation("Say")

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


def create_host(context):
    return FeatureDefinition(
        owner=context.owner,
        contributions=(
            Contribution(
                kind="menu",
                id="hello",
                data={"label": "打个招呼", "command": "hello", "order": 55},
            ),
        ),
        runtime_factory=HelloRuntime,
    )
