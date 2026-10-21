"""点击 Q 弹的纯几何。"""

from __future__ import annotations

import math

SQUASH_DURATION_MS = 220
SQUASH_SX = 0.10
SQUASH_SY = 0.15


def squash_geometry(
    window_width: int,
    window_height: int,
    frame_width: int,
    frame_height: int,
    progress: float,
) -> tuple[int, int, int, int]:
    """返回 Q 弹帧在窗口内的绘制矩形（底部居中，先压扁再横向鼓出）。"""
    progress = max(0.0, min(1.0, float(progress)))
    pulse = math.sin(math.pi * progress)
    width = max(1, int(round(frame_width * (1.0 + SQUASH_SX * pulse))))
    height = max(1, int(round(frame_height * (1.0 - SQUASH_SY * pulse))))
    x = int(round((window_width - width) / 2))
    y = window_height - height
    return x, y, width, height
