"""拖拽/抛掷/弹弓的纯函数核心。

从主分支的物理参数与数学口径移植，保持 `engine/` 零 Qt、零 `pet.*` 依赖。
窗口层只负责喂状态并搬窗口。
"""

from __future__ import annotations

import math

SPRING_K = 200.0
SPRING_C = 30.0

TRAIL_KEEP_SEC = 0.15
RELEASE_WINDOW_SEC = 0.12
RELEASE_STALE_SEC = 0.15
MIN_SPAN_SEC = 0.02
SEG_MIN_DT = 0.008
DEAD_ZONE_SPEED = 500.0
MAX_THROW_SPEED = 6000.0
PEAK_WEIGHT = 0.5
ACCEL_REF = 8000.0
ACCEL_GAIN_MAX = 0.6

THROW_STRENGTH_CAPS = {
    "gentle": 3600.0,
    "standard": 4800.0,
    "strong": 7200.0,
    "crazy": 9000.0,
}

SLINGSHOT_MIN_DISTANCE = 24.0
SLINGSHOT_MAX_DISTANCE = 160.0
SLINGSHOT_BASE_SPEED = 900.0
SLINGSHOT_MAX_DEFORMATION = 1.3

GRAVITY = 1400.0
RESTITUTION = 0.68
GROUND_FRICTION = 2.5
REST_VY = 40.0
GROUND_BOUNCE_STOP_VY = 120.0
REST_VX = 15.0
BOUNCE_TRIGGER_SPEED = 120.0


def normalize_throw_strength(value: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in THROW_STRENGTH_CAPS else "standard"


def throw_speed_cap(strength: str) -> float:
    return THROW_STRENGTH_CAPS[normalize_throw_strength(strength)]


def slingshot_deformation(
    pull_x: float,
    pull_y: float,
    progress: float,
    maximum: float = SLINGSHOT_MAX_DEFORMATION,
) -> tuple[float, float]:
    """橡皮带各向异性拉伸：沿拉力方向拉长、垂直方向压扁。"""
    progress = max(0.0, min(1.0, float(progress)))
    maximum = max(1.0, float(maximum))
    distance = math.hypot(float(pull_x), float(pull_y))
    if distance <= 1e-6 or progress <= 0.0:
        return 1.0, 1.0
    ux, uy = float(pull_x) / distance, float(pull_y) / distance
    stretch = 1.0 + (maximum - 1.0) * progress
    squeeze = 1.0 - (1.0 - 1.0 / maximum) * progress
    return (
        math.hypot(stretch * ux, squeeze * uy),
        math.hypot(stretch * uy, squeeze * ux),
    )


def flight_anim_speed(speed_px_s: float) -> float:
    speed = max(0.0, float(speed_px_s))
    return 1.0 + min(speed / 1400.0, 1.0) * 0.75


def soft_clamp_speed(speed: float, cap: float = MAX_THROW_SPEED) -> float:
    if speed <= 0.0 or cap <= 0.0:
        return 0.0
    return cap * (1.0 - math.exp(-speed / cap))


def slingshot_speed(distance: float, minimum: float, maximum: float, cap: float) -> float:
    if distance < minimum or maximum <= minimum or cap <= 0.0:
        return 0.0
    ratio = max(0.0, min(1.0, (float(distance) - minimum) / (maximum - minimum)))
    eased = 1.0 - (1.0 - ratio) ** 2
    raw = SLINGSHOT_BASE_SPEED + (3.0 * cap - SLINGSHOT_BASE_SPEED) * eased
    return soft_clamp_speed(raw, cap=cap)


def slingshot_trajectory(
    vx: float,
    vy: float,
    duration: float = 0.8,
    points: int = 12,
    gravity: float = GRAVITY,
) -> list[tuple[float, float]]:
    if duration <= 0.0 or points <= 0:
        return []
    if points == 1:
        return [(0.0, 0.0)]
    step = float(duration) / (points - 1)
    return [
        (float(vx) * (index * step), float(vy) * (index * step) + 0.5 * gravity * (index * step) ** 2)
        for index in range(points)
    ]


def spring_velocity(
    v: float, x: float, target: float, dt: float, k: float = SPRING_K, c: float = SPRING_C
) -> float:
    return v + ((target - x) * k - v * c) * dt


def _window(trail: list, now: float, span: float) -> list:
    cutoff = now - span
    return [sample for sample in trail if sample[0] >= cutoff]


def estimate_release_velocity(
    trail: list, now: float, cap: float = MAX_THROW_SPEED
) -> tuple[float, float]:
    """由拖拽轨迹估算松手初速 (vx, vy)；松手前停顿视为原地放下。"""
    if not trail:
        return 0.0, 0.0
    if now - trail[-1][0] > RELEASE_STALE_SEC:
        return 0.0, 0.0
    window = _window(trail, now, RELEASE_WINDOW_SEC)
    if len(window) < 2:
        return 0.0, 0.0
    t0, x0, y0 = window[0]
    t1, x1, y1 = window[-1]
    span = t1 - t0
    if span < MIN_SPAN_SEC:
        return 0.0, 0.0

    base_vx, base_vy = (x1 - x0) / span, (y1 - y0) / span
    base_speed = math.hypot(base_vx, base_vy)

    segments: list[tuple[float, float]] = []
    px_, py_, pt_ = x0, y0, t0
    for t, x, y in window[1:]:
        dt = t - pt_
        if dt >= SEG_MIN_DT:
            segments.append((math.hypot(x - px_, y - py_) / dt, t))
            px_, py_, pt_ = x, y, t
    peak_speed = max((speed for speed, _ in segments), default=base_speed)

    accel = 0.0
    if len(segments) >= 2:
        accel = (segments[-1][0] - segments[0][0]) / max(
            segments[-1][1] - segments[0][1], MIN_SPAN_SEC
        )

    speed = (1.0 - PEAK_WEIGHT) * base_speed + PEAK_WEIGHT * peak_speed
    gain = 1.0 + min(max(accel, 0.0) / ACCEL_REF, 1.0) * ACCEL_GAIN_MAX
    speed = soft_clamp_speed(speed * gain, cap=cap)
    if base_speed < 1e-6:
        return 0.0, speed
    return base_vx / base_speed * speed, base_vy / base_speed * speed


def throw_step(
    px: float,
    py: float,
    vx: float,
    vy: float,
    dt: float,
    left: float,
    top: float,
    right: float,
    bottom: float,
    gravity: float = GRAVITY,
    bounce_stop_vy: float = GROUND_BOUNCE_STOP_VY,
) -> tuple[float, float, float, float, bool]:
    vy += gravity * dt
    px += vx * dt
    py += vy * dt
    bounced = False
    if px < left:
        px, vx, bounced = left, abs(vx) * RESTITUTION, True
    elif px > right:
        px, vx, bounced = right, -abs(vx) * RESTITUTION, True
    if py < top:
        py, vy, bounced = top, abs(vy) * RESTITUTION, True
    elif py >= bottom:
        py = bottom
        vx *= max(0.0, 1.0 - GROUND_FRICTION * dt)
        if abs(vy) < bounce_stop_vy:
            vy = 0.0
        else:
            vy = -abs(vy) * RESTITUTION
        bounced = True
    return px, py, vx, vy, bounced


def is_at_rest(py: float, vx: float, vy: float, bottom: float, bounced: bool, speed: float) -> bool:
    if py >= bottom - 1 and abs(vy) < 1 and abs(vx) < REST_VX:
        return True
    return bounced and speed < REST_VY and abs(vy) < 1
