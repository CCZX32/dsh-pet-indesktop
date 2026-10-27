"""灵动岛作为桌宠世界的静态障碍物：体育场几何 + 推出 + 冲量（零 Qt）。

主分支 `pet/island_collision.py` 是「岛窗口 + 桌宠窗口」一把抓的实现；这里只留
可测的数学，窗口接线在 ``petcore/ui/island_collision.py``。三条口径与主分支一致，
改动前先读 ``docs/PETCORE-SPEC.md``「岛 × 桌宠碰撞」：

- **只覆盖胶囊本体**：``min(窗口高, CAPSULE_HEIGHT)`` 造体育场，展开卡片的卡片
  区域不是幽灵墙。
- **矩形径向半径**：身体框沿法线的径向半径（``rect_radial``）比内切椭圆大，
  椭圆只在四条边中点相切，四角会穿模。
- **中心恰在轴上强制向上**：岛横向扫过一只被完全盖住的桌宠时，从下面把它铲起来。

本模块不 import Qt、不 import ``pet.*``、不 import ``petcore.ui``（结构守卫
``tests/test_petcore_architecture.py`` 会守）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from . import physics

#: 胶囊视觉高度：与 ``petcore/ui/island.CAPSULE_HEIGHT`` 同值。碰撞体只取这一段，
#: 展开卡片时多出来的高度不设墙。
CAPSULE_HEIGHT = 44.0

#: 撞岛像撞弹床：入场那一次的回收系数（主分支 ``collision.STATIC_RESTITUTION``）。
#: **只能给「还没在抛掷」的那一次**——已经飞起来的桌宠再乘 1.3 就是能量泵，永远
#: 停不下来（主分支先例 ``docs/PR-REPORT-THROWN-ISLAND-PUMP-2026-09-24.md``）。
STATIC_RESTITUTION = 1.3

#: 抛掷中撞岛/撞边共用的回收系数（``physics.RESTITUTION`` 同值，只读引用）。
RESTITUTION = physics.RESTITUTION

#: 真撞门：相对接近速度低于它只算轻贴（只推出，不响不挤不弹）。
IMPULSE_MIN_APPROACH_SPEED = 80.0

#: 冲量速度上限 = 抛掷硬上限，杜绝异常值把桌宠甩出屏幕。
MAX_IMPULSE_SPEED = physics.MAX_THROW_SPEED

#: 接触跟踪的有效间隔（超过按首次接触处理，无速度）。
CONTACT_MAX_DT = 0.5

#: 接触跟踪的合理速度上限：发起移动计划时会先算一次 240px 外的落点，那不是
#: 接近速度；漫游实测步速 4.5–24 px/s（见 ``docs/PETCORE-LOG.md`` L103），
#: 任何超过这条线的「速度」都只可能是坐标跳变。
MAX_TRACKED_SPEED = 2000.0

#: 接触跟踪的最小间隔：同一毫秒内的重复查询不算速度。
MIN_TRACKED_DT = 0.01


@dataclass(frozen=True, slots=True)
class Stadium:
    """体育场（两端半圆 + 中间直轴）：``(x0, x1]`` 是轴线，``axis_y`` 是轴高。"""

    x0: float
    x1: float
    axis_y: float
    radius: float
    height: float


@dataclass(frozen=True, slots=True)
class PushOut:
    """推出结果：修正后的身体框左上角、墙法线（指向桌宠一侧）与重叠深度。"""

    left: float
    top: float
    nx: float
    ny: float
    depth: float


def stadium_from_rect(
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    capsule_height: float = CAPSULE_HEIGHT,
) -> Stadium | None:
    """岛窗口矩形 → 胶囊体育场；非法矩形返回 ``None``（不建幽灵墙）。"""
    try:
        left = float(left)
        top = float(top)
        width = float(width)
        height = float(height)
    except (TypeError, ValueError):
        return None
    for value in (left, top, width, height):
        if not math.isfinite(value):
            return None
    if width <= 0.0 or height <= 0.0:
        return None
    limit = float(capsule_height)
    body_height = min(height, limit) if limit > 0.0 else height
    radius = body_height / 2.0
    if radius <= 0.0 or width < 2.0 * radius:
        # 细条（16px 厚）能到这来，但窗口宽度小于直径时轴线会反向：退回整宽圆。
        radius = min(radius, width / 2.0)
        if radius <= 0.0:
            return None
    axis_y = top + radius
    return Stadium(
        x0=left + radius,
        x1=left + width - radius,
        axis_y=axis_y,
        radius=radius,
        height=body_height,
    )


def rect_radial(rx: float, ry: float, nx: float, ny: float) -> float:
    """矩形（半宽 ``rx``、半高 ``ry``）沿单位法线 ``(nx, ny)`` 的径向半径。"""
    if abs(nx) <= 1e-9:
        return ry / max(abs(ny), 1e-9)
    if abs(ny) <= 1e-9:
        return rx / max(abs(nx), 1e-9)
    return min(rx / abs(nx), ry / abs(ny))


def axis_closest(stadium: Stadium, px: float, py: float) -> tuple[float, float]:
    """胶囊轴线上离 ``(px, py)`` 最近的点。"""
    return min(max(px, stadium.x0), stadium.x1), stadium.axis_y


def push_out(
    body: Sequence[float],
    stadium: Stadium,
    *,
    gap: float = 1.0,
) -> PushOut | None:
    """身体框（全局 ``left, top, w, h``）与胶囊重叠时推出；不重叠返回 ``None``。

    身体框整体被推到「轴最近点 + 法线 ×（身体径向半径 + 岛半径 + gap）」，因此
    调用方只要把位置写回去就不会穿透。
    """
    left, top, width, height = (float(value) for value in body[:4])
    if width <= 0.0 or height <= 0.0:
        return None
    rx = width / 2.0
    ry = height / 2.0
    cx = left + rx
    cy = top + ry
    closest_x, axis_y = axis_closest(stadium, cx, cy)
    dx = cx - closest_x
    dy = cy - axis_y
    dist = math.hypot(dx, dy)
    if dist <= 1e-9:
        # 中心恰在轴上：沿 -y 推出（向上），岛横向扫过时把人「铲」起来。
        nx, ny, radial = 0.0, -1.0, ry
    else:
        nx, ny = dx / dist, dy / dist
        radial = rect_radial(rx, ry, nx, ny)
    surface = radial + stadium.radius
    if dist >= surface:
        return None
    target_cx = closest_x + nx * (surface + gap)
    target_cy = axis_y + ny * (surface + gap)
    return PushOut(
        left=target_cx - rx,
        top=target_cy - ry,
        nx=nx,
        ny=ny,
        depth=surface - dist,
    )


def relative_approach(
    pet_velocity: Sequence[float],
    island_velocity: Sequence[float],
    normal: Sequence[float],
) -> float:
    """相对接近速度的法向分量（法线指向桌宠一侧，接近为负）。"""
    vn = (
        (float(pet_velocity[0]) - float(island_velocity[0])) * float(normal[0])
        + (float(pet_velocity[1]) - float(island_velocity[1])) * float(normal[1])
    )
    return vn


def impulse_velocity(
    vn: float,
    normal: Sequence[float],
    *,
    restitution: float = STATIC_RESTITUTION,
    cap: float = MAX_IMPULSE_SPEED,
) -> tuple[float, float]:
    """非抛掷撞岛的速度增量：``dv = -(1 + e) * vn``，硬上限 ``cap``。"""
    dv = -(1.0 + float(restitution)) * float(vn)
    if dv < 0.0:
        dv = 0.0
    if cap > 0.0 and dv > cap:
        dv = cap
    return dv * float(normal[0]), dv * float(normal[1])


def reflect_velocity(
    velocity: Sequence[float],
    normal: Sequence[float],
    restitution: float = RESTITUTION,
) -> tuple[float, float]:
    """抛掷中撞墙：法向分量反号并乘回收系数（出射永不大于入射）。"""
    vx = float(velocity[0])
    vy = float(velocity[1])
    nx = float(normal[0])
    ny = float(normal[1])
    vn = vx * nx + vy * ny
    if vn >= 0.0:
        # 已经在离开：不反射（否则同一位置会二次反射成抽风）
        return vx, vy
    k = (1.0 + float(restitution)) * vn
    return vx - k * nx, vy - k * ny


def tracked_velocity(
    previous: Sequence[float] | None,
    current: Sequence[float],
    dt: float,
    *,
    max_speed: float = MAX_TRACKED_SPEED,
    min_dt: float = MIN_TRACKED_DT,
    max_dt: float = CONTACT_MAX_DT,
) -> tuple[float, float]:
    """用两次「提议位置」的位移估计接触速度；不合理时返回零（= 轻贴）。

    首次接触、间隔过长、``dt`` 太小、或推算速度超过 ``max_speed``（坐标跳变，
    例如发起移动计划时先算一次 240px 外的落点）一律当 0。
    """
    if previous is None:
        return 0.0, 0.0
    try:
        dt = float(dt)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if not math.isfinite(dt) or dt <= min_dt or dt >= max_dt:
        return 0.0, 0.0
    vx = (float(current[0]) - float(previous[0])) / dt
    vy = (float(current[1]) - float(previous[1])) / dt
    if not math.isfinite(vx) or not math.isfinite(vy):
        return 0.0, 0.0
    if max_speed > 0.0 and math.hypot(vx, vy) > max_speed:
        return 0.0, 0.0
    return vx, vy

#: 岛速估计上限（px/s）：拖拽中钳到这里，非拖拽一律清零（真实拖拽之外没有
#: 合法的高速来源）。
MAX_ISLAND_SPEED = 1500.0

#: 瞬移守卫：单拍位移超过「3000 px/s × dt + 窗口宽」就不是拖拽，是换屏/夹回/落位。
TELEPORT_SPEED = 3000.0

#: 采样间隔窗口。``dt`` 太小是高频回调（一次 ``mouseMoveEvent`` 会喂两遍同一
#: rect）：必须**跳过**而不是「清零并刷新基线」，否则 100Hz+ 回调让拖拽全程岛速
#: 恒 0，退化成只推挤不弹飞。``dt`` 太大是长暂停：旧的位移不能再算速度。
MIN_SAMPLE_DT = 0.01
MAX_SAMPLE_DT = 0.5

#: 单拍位移小于它视为「同 rect 上报」。
SAME_RECT_EPS = 1.0


@dataclass(frozen=True, slots=True)
class VelocitySample:
    """一拍岛速估计的结果。

    ``update_baseline=False`` = 高频回调，调用方既不清零也不刷新采样基线；
    ``keep_velocity=True`` = 同 rect 的配对上报（拖拽中一次 move 会喂两遍）：
    沿用上一拍速度，别把正在甩的岛当成停了。
    """

    vx: float = 0.0
    vy: float = 0.0
    update_baseline: bool = True
    keep_velocity: bool = False


def sample_island_velocity(
    previous: Sequence[float] | None,
    current: Sequence[float],
    dt: float | None,
    *,
    dragging: bool,
    released: bool = False,
) -> VelocitySample:
    """岛速采样（``previous``/``current`` 都是 ``(left, top, w, h)``）。

    闸门来自主分支 ``pet/island_bridge.py:322-411``，每一条都对应一个实机回归：
    尺寸变化（只重置采样点）、高频回调（跳过、不清零）、长暂停（旧位移不算）、
    瞬移守卫、同 rect 的配对上报（拖拽中保住速度）、松手闸（松手那一拍是夹回/
    落位，不能算成撞击）、超速（拖拽中钳制，其余清零）。
    """
    if previous is None:
        return VelocitySample()
    left, top, width, height = (float(value) for value in current[:4])
    prev_left, prev_top, prev_w, prev_h = (float(value) for value in previous[:4])
    if released:
        # 松手那一拍的位移是夹回/落位：作废基线，别拿它算过期位移。
        return VelocitySample()
    if abs(width - prev_w) > 0.5 or abs(height - prev_h) > 0.5:
        return VelocitySample()
    if dt is None or not math.isfinite(float(dt)) or float(dt) <= MIN_SAMPLE_DT:
        # 高频回调：**拖拽中**必须跳过（不清零、不刷新基线，否则拖拽全程速度恒 0），
        # 但「岛已经停住、只是同一帧喂了两遍」时不能留着停手前的速度——那会让旁边走过来的
        # 桌宠被凭空拍飞。判据只看 rect 有没有动，不依赖 dragging 的时序。
        dx0 = left - prev_left
        dy0 = top - prev_top
        if not dragging and math.hypot(dx0, dy0) < SAME_RECT_EPS:
            return VelocitySample()
        return VelocitySample(update_baseline=False)
    dt = float(dt)
    if dt > MAX_SAMPLE_DT:
        return VelocitySample()
    dx = left - prev_left
    dy = top - prev_top
    jump = math.hypot(dx, dy)
    if jump > TELEPORT_SPEED * dt + width:
        return VelocitySample()
    if jump < SAME_RECT_EPS:
        if dragging:
            # 一次 mouseMoveEvent 里 move() 与显式上报喂两遍同一 rect：保留速度。
            return VelocitySample(keep_velocity=True)
        return VelocitySample()
    vx = dx / dt
    vy = dy / dt
    speed = math.hypot(vx, vy)
    if speed > MAX_ISLAND_SPEED:
        if not dragging:
            return VelocitySample()
        scale = MAX_ISLAND_SPEED / speed
        return VelocitySample(vx * scale, vy * scale)
    return VelocitySample(vx, vy)
