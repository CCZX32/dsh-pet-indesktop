"""``voice.chime`` 入口：只做依赖组装，运行时代码不 import Qt。

语音合成、缓存、播放与失败分类都在 core（``HostPorts.speech``）；本扩展只负责
排期、台词、免打扰判断、气泡/动画与设置页。
"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from .runtime import ChimeRuntime
from .settings_page import ChimePage

OWNER = "voice.chime"

__all__ = ["ChimePage", "ChimeRuntime", "create_host"]


def create_host(_context) -> FeatureDefinition:
    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="menu",
                id="now",
                data={"label": "立即报时", "command": "now", "order": 89, "icon": "chat"},
            ),
            Contribution(
                kind="settings_page",
                id="chime",
                data={"title": "语音报时", "order": 670, "icon": "chat"},
            ),
        ),
        runtime_factory=ChimeRuntime,
        settings_factory=ChimePage,
    )
