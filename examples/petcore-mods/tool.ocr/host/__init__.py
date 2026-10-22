"""tool.ocr 的入口：只做依赖组装。"""

from __future__ import annotations

from petcore.contracts.feature import FeatureDefinition

from .runtime import OWNER, OcrRuntime

__all__ = ["OcrRuntime", "create_host"]


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=(),
        runtime_factory=OcrRuntime,
    )
