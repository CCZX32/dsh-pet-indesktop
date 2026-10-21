from __future__ import annotations

import random

from ..contracts.content import AnimationSpec
from .geometry import (
    MOVE_STRIDE_DEFAULT_PX,
    Rect,
    band_bounds,
    clamp_body,
    clamp_body_to_screens,
    clamp_position,
)


def body_reach(
    avail_left: float,
    avail_right: float,
    body_left: float,
    body_width: float,
    margin: float,
) -> tuple[float, float, float]:
    """身体框中心的可达界：返回 (cx, left_bound, right_bound)。"""
    half = body_width / 2
    return (
        body_left + half,
        avail_left + margin + half,
        avail_right - margin - half,
    )


def choose_move_direction(
    cx: float,
    left_bound: float,
    right_bound: float,
    min_distance: float,
    rng=None,
) -> int | None:
    """按两侧可达空间选 -1/ +1；两侧都不足返回 None。"""
    randomizer = rng or random
    if cx - left_bound >= min_distance and right_bound - cx >= min_distance:
        return randomizer.choice([-1, 1])
    if cx - left_bound >= min_distance:
        return -1
    if right_bound - cx >= min_distance:
        return 1
    return None


def quantize_move(
    distance_px: float,
    stride_px: float,
    room_px: float,
    loop_duration: float,
) -> tuple[int, float, float]:
    """把位移量化为整圈步态；返回 (loops, distance, duration)。"""
    stride = max(1.0, float(stride_px))
    loops = max(1, round(float(distance_px) / stride))
    while loops > 1 and loops * stride > room_px:
        loops -= 1
    return loops, min(loops * stride, float(room_px)), loops * float(loop_duration)


def move_position_at_frame(plan: dict, frames_elapsed: float) -> tuple[float, float]:
    """按 clip 帧号插值窗口位置；curve 静止段不推进，末拍强制到位。"""
    curve = plan.get("curve")
    total = max(1, int(plan.get("total_frames") or 1))
    if curve:
        per_loop = max(1, int(plan.get("frames_per_loop") or 1))
        loops = max(1, int(plan.get("loops") or 1))
        frames = min(float(total), max(0.0, float(frames_elapsed)))
        loop_index = min(int(frames // per_loop), loops - 1)
        intra = frames - loop_index * per_loop
        last = len(curve) - 1
        if last <= 0:
            progress = 1.0
        else:
            pos = min(float(last), intra * last / max(1, per_loop - 1))
            low = int(pos)
            fraction = pos - low
            intra_progress = curve[low] + (
                curve[min(low + 1, last)] - curve[low]
            ) * fraction
            progress = (loop_index + intra_progress) / loops
    else:
        if frames_elapsed >= total - 1:
            progress = 1.0
        else:
            progress = min(1.0, max(0.0, frames_elapsed / total))
    start_x = float(plan.get("start_x") or 0.0)
    start_y = float(plan.get("start_y") or 0.0)
    target_x = float(plan.get("target_x") or start_x)
    target_y = float(plan.get("target_y") or start_y)
    progress = max(0.0, min(1.0, float(progress)))
    return (
        start_x + (target_x - start_x) * progress,
        start_y + (target_y - start_y) * progress,
    )


def wander_target_y(
    start_y: float,
    top: float,
    bottom: float,
    height: float,
    margin: float,
    rng=None,
) -> int:
    randomizer = rng or random
    low = top + margin
    high = bottom - height - margin
    if high <= low:
        return int(start_y)
    max_dy = max(40, int((high - low) * 0.25))
    return int(max(low, min(high, start_y + randomizer.randint(-max_dy, max_dy))))


def stride_for(spec: AnimationSpec, move_strides: dict[str, int] | None) -> int:
    if move_strides:
        value = move_strides.get(spec.name)
        if isinstance(value, int) and value > 0:
            return value
    return MOVE_STRIDE_DEFAULT_PX


def clamp_to_screens(
    x: int,
    y: int,
    width: int,
    height: int,
    screens: tuple[Rect, ...],
    body_local: Rect | None = None,
) -> tuple[int, int]:
    if not screens:
        return x, y
    if body_local is not None:
        return clamp_body_to_screens(x, y, body_local, screens)
    body = (x, y, width, height)
    left, top, bw, bh = band_bounds(body, screens)
    return clamp_position(x, y, width, height, (left, top, bw, bh))


def clamp_to_screen(
    x: int, y: int, screen: Rect, body_local: Rect | None = None
) -> tuple[int, int]:
    """按身体框钳进单块屏；``body_local=None`` 时保持整窗旧行为。"""
    if body_local is None:
        return clamp_position(x, y, screen[2], screen[3], screen)
    return clamp_body(x, y, body_local, screen)
