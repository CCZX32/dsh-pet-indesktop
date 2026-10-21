"""黄金回旋与通用缓动的纯数学。"""

from __future__ import annotations

GOLDEN_SPIN_DURATION_MS = 700
GOLDEN_SPIN_END_ANGLE = -360.0
GOLDEN_SPIN_ACCEL = 0.82
GOLDEN_SPIN_MIN_REV_MS = 200
GOLDEN_SPIN_CLICK_RUSH_MS = 130


def ease_out_cubic(progress: float) -> float:
    progress = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - progress) ** 3


def eased_progress(elapsed_ms: float, duration_ms: float) -> float:
    duration = max(1.0, float(duration_ms))
    return ease_out_cubic(max(0.0, float(elapsed_ms)) / duration)


def spin_angle(progress: float, start: float = 0.0, end: float = GOLDEN_SPIN_END_ANGLE) -> float:
    return float(start) + (float(end) - float(start)) * eased_progress(progress, 1.0)
