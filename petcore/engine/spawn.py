"""子宠落座位置（纯几何）：优先贴着主宠排，且必须整只落在可用区内。"""

from __future__ import annotations

from .geometry import Rect, clamp_body, rect_overlap_area

GAP = 24
RINGS = 3
MIN_FREE_RATIO = 0.0


def candidate_positions(
    anchor: Rect, size: tuple[int, int], gap: int = GAP, rings: int = RINGS
) -> list[tuple[int, int]]:
    """按「右 → 左 → 上 → 下」逐圈外扩的候选身体左上角。"""
    ax, ay, aw, ah = anchor
    width, height = size
    positions: list[tuple[int, int]] = []
    for ring in range(1, max(1, int(rings)) + 1):
        offset = int(gap) * ring
        positions.extend(
            [
                (ax + aw + offset, ay),
                (ax - width - offset, ay),
                (ax, ay - height - offset),
                (ax, ay + ah + offset),
            ]
        )
    return positions


def _fits(position: tuple[int, int], size: tuple[int, int], bounds: Rect) -> bool:
    left, top, width, height = bounds
    x, y = position
    body_width, body_height = size
    return (
        x >= left
        and y >= top
        and x + body_width <= left + width
        and y + body_height <= top + height
    )


def choose_spawn_position(
    anchor: Rect,
    size: tuple[int, int],
    bounds: Rect,
    occupied: list[Rect] | tuple[Rect, ...] = (),
    gap: int = GAP,
    rings: int = RINGS,
) -> tuple[int, int]:
    """挑一个既不压住已有桌宠、又完整落在可用区内的落座点（身体左上角）。

    找不到空位时退化为「主宠右侧，再按身体框钳进可用区」——宁可重叠也不出屏。
    """
    candidates = candidate_positions(anchor, size, gap=gap, rings=rings)
    for position in candidates:
        if not _fits(position, size, bounds):
            continue
        body = (position[0], position[1], size[0], size[1])
        if any(
            rect_overlap_area(body, other) > MIN_FREE_RATIO for other in occupied
        ):
            continue
        return position

    fallback = candidates[0] if candidates else (anchor[0], anchor[1])
    body_local = (0, 0, size[0], size[1])
    return clamp_body(fallback[0], fallback[1], body_local, bounds)
