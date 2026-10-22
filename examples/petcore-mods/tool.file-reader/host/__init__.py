"""tool.file-reader 的入口：只做依赖组装。"""

from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition

from .runtime import OWNER, FileReaderRuntime
from .settings_page import FileReaderPage

__all__ = ["FileReaderPage", "FileReaderRuntime", "create_host"]


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="menu",
                id="read_last",
                data={
                    "label": "解读刚才拖入的文件",
                    "command": "read_last",
                    "order": 85,
                    "icon": "folder",
                },
            ),
            Contribution(
                kind="settings_page",
                id="file-reader",
                data={"title": "文件解读", "order": 690, "icon": "folder"},
            ),
        ),
        runtime_factory=FileReaderRuntime,
        settings_factory=FileReaderPage,
    )
