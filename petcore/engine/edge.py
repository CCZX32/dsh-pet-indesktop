"""边缘探头的纯几何：贴边判定、旋转投影、目标窗口 x、放宽钳制域。"""

from __future__ import annotations

import math

from .geometry import Rect

EDGE_PROBE_ANGLE = 45.0
EDGE_PEEK_EXPOSURE = 0.55
EDGE_ENGAGE_EXPOSURE = 0.82
EDGE_ENTER_MS = 300
EDGE_STRAIGHTEN_MS = 250
EDGE_RETURN_MS = 300
EDGE_IDLE_SECONDS = 5.0
EDGE_REST_SECONDS = 0.35
EDGE_TOLERANCE_PX = 1
# 落地反弹后身体常常停在离边缘十几像素处；贴边判定要给这段余量，进入时再吸附到边上。
EDGE_ENGAGE_TOLERANCE_PX = 28


def edge_side_at_rest(
    body_rect: Rect, bounds: Rect, tolerance: int = EDGE_TOLERANCE_PX
) -> str | None:
    """身体框是否贴在可用区的左/右缘（容差吸收整数取整与落地反弹）。"""
    x, _y, width, _height = body_rect
    left, _top, bwidth, _bheight = bounds
    if width <= 0:
        return None
    if x <= left + tolerance:
        return "left"
    if x + width >= left + bwidth - tolerance:
        return "right"
    return None


def edge_snap_x(side: str, body_local: Rect, bounds: Rect) -> int:
    """贴边姿态下让身体框正好压边的窗口 x。"""
    bx, _by, bw, _bh = body_local
    left, _top, width, _height = bounds
    if side == "left":
        return int(round(left - bx))
    if side == "right":
        return int(round(left + width - bx - bw))
    raise ValueError(f"unknown edge side: {side!r}")


def rotated_bounds(rect: Rect, pivot: tuple[float, float], angle_deg: float) -> Rect:
    """``rect`` 绕 ``pivot`` 旋转后的投影外接矩形（整数化）。"""
    x, y, width, height = rect
    if abs(angle_deg) < 1e-9:
        return rect
    px, py = pivot
    radians = math.radians(float(angle_deg))
    cos = math.cos(radians)
    sin = math.sin(radians)
    xs: list[float] = []
    ys: list[float] = []
    for cx, cy in ((x, y), (x + width, y), (x, y + height), (x + width, y + height)):
        dx = cx - px
        dy = cy - py
        xs.append(px + dx * cos - dy * sin)
        ys.append(py + dx * sin + dy * cos)
    left = math.floor(min(xs))
    top = math.floor(min(ys))
    right = math.ceil(max(xs))
    bottom = math.ceil(max(ys))
    return left, top, max(1, right - left), max(1, bottom - top)


def probe_target_x(
    side: str, exposure: float, projected_local: Rect, bounds: Rect
) -> int:
    """探头姿态下窗口左上角的目标 x。

    ``projected_local`` 是身体框绕帧中心旋转后的窗口局部矩形；露出比例的分母
    是它的宽度，不是整窗宽度。
    """
    exposure = max(0.0, min(1.0, float(exposure)))
    offscreen = (1.0 - exposure) * projected_local[2]
    left, _top, width, _height = bounds
    if side == "left":
        return int(round(left - offscreen - projected_local[0]))
    if side == "right":
        return int(round(left + width + offscreen - projected_local[0] - projected_local[2]))
    raise ValueError(f"unknown edge side: {side!r}")


def probe_body_bounds(bounds: Rect, body_local: Rect) -> Rect:
    """探头姿态下放宽的身体钳制域（身体可整体推出屏幕）。

    必须减去 ``body_local.x``：身体框在画布里本就右偏，不减会让左向几乎不放宽。
    """
    left, top, width, height = bounds
    bx, by, bw, bh = body_local
    return (
        left - bx - bw,
        top - by,
        width + 2 * bw + 2 * bx,
        height + 2 * by,
    )
