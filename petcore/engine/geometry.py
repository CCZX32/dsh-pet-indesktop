from __future__ import annotations

CANVAS_W = 640
CANVAS_H = 360
FEET_Y = 330
PAD = CANVAS_H - FEET_Y

DEFAULT_SCALE = 0.72
SCALE_MIN = 0.10
SCALE_MAX = 3.00
SCALE_STEPS = (0.5, 0.72, 0.85, 1.0)
CORNER_MARGIN = 24

DRAG_THRESHOLD = 5
MOVE_MIN_PX = 60
MOVE_MAX_PX = 240
MOVE_MARGIN = 20
MOVE_STRIDE_DEFAULT_PX = 120

P_IDLE = 0.30
P_TURN = 0.40
P_ACTS = 0.80

HEAD_FALLBACK_RATIO = 0.45

Rect = tuple[int, int, int, int]


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, float(scale)))


def content_size(scale: float) -> tuple[int, int]:
    return max(1, round(CANVAS_W * scale)), max(1, round(CANVAS_H * scale))


def clamp_position(x: int, y: int, w: int, h: int, bounds: Rect) -> tuple[int, int]:
    left, top, width, height = bounds
    max_x = left + max(0, width - w)
    max_y = top + max(0, height - h)
    return max(left, min(max_x, x)), max(top, min(max_y, y))


def body_local_rect(
    body_box: tuple[int, int, int, int] | None,
    scale: float,
    canvas: tuple[int, int] = (CANVAS_W, CANVAS_H),
) -> Rect:
    """稳定身体框（窗口局部坐标）。

    ``body_box`` 是 manifest 的源像素坐标（640×360 画布，已镜像对称化）。
    未声明的角色回退整窗，语义等同「窗口即身体」。
    """
    width = max(1, round(canvas[0] * scale))
    height = max(1, round(canvas[1] * scale))
    if body_box is None:
        return 0, 0, width, height
    x1, y1, x2, y2 = body_box
    return (
        round(x1 * scale),
        round(y1 * scale),
        max(1, round((x2 - x1) * scale)),
        max(1, round((y2 - y1) * scale)),
    )


def body_at(x: int, y: int, body_local: Rect) -> Rect:
    bx, by, bw, bh = body_local
    return x + bx, y + by, bw, bh


def _clamp_span(value: int, lo: int, hi: int, off: int, span: int) -> int:
    """把 ``value`` 钳到使 ``[value+off, value+off+span]`` 完整落在 ``[lo, hi]``。

    ``hi`` 是连续右/下界。可用区比身体还窄/矮时钳到下界，避免把窗口推到
    屏幕另一侧（与主分支 ``_clamp_axis`` 同一兜底）。
    """
    lower = lo - off
    upper = hi - off - span
    if upper < lower:
        return lower
    return max(lower, min(upper, value))


def clamp_body(x: int, y: int, body_local: Rect, bounds: Rect) -> tuple[int, int]:
    """按身体框把窗口左上角钳进单个可用区。

    身体框必须完整落在 ``bounds`` 内；窗口透明边允许越界。这是「靠边按形象
    而不是按动画画布」的唯一数学入口。
    """
    left, top, width, height = bounds
    bx, by, bw, bh = body_local
    return (
        _clamp_span(x, left, left + width, bx, bw),
        _clamp_span(y, top, top + height, by, bh),
    )


def _rect_covered(rect: Rect, screens: tuple[Rect, ...]) -> bool:
    """``rect`` 是否逐点落在各屏并集内（轴对齐网格切分）。

    跨屏缝上身体横跨两块相连屏是合法的；错位屏之间的空洞不合法。
    """
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        return True
    xs = {x, x + width}
    ys = {y, y + height}
    for left, top, sw, sh in screens:
        if x < left < x + width:
            xs.add(left)
        if x < left + sw < x + width:
            xs.add(left + sw)
        if y < top < y + height:
            ys.add(top)
        if y < top + sh < y + height:
            ys.add(top + sh)
    xs = sorted(xs)
    ys = sorted(ys)
    for left, right in zip(xs, xs[1:]):
        for top, bottom in zip(ys, ys[1:]):
            cx = (left + right) / 2.0
            cy = (top + bottom) / 2.0
            if not any(
                sx <= cx <= sx + sw and sy <= cy <= sy + sh
                for sx, sy, sw, sh in screens
            ):
                return False
    return True


def clamp_body_to_screens(
    x: int, y: int, body_local: Rect, screens: tuple[Rect, ...]
) -> tuple[int, int]:
    """按身体框在多屏布局中收口。

    身体已落在各屏并集内（含跨屏缝）就不动；落进屏间空洞时，对每块屏求
    钳制候选，取位移平方最小的那一块。
    """
    if not screens:
        return x, y
    if _rect_covered(body_at(x, y, body_local), screens):
        return x, y
    best: tuple[int, int, int] | None = None
    for screen in screens:
        cx, cy = clamp_body(x, y, body_local, screen)
        distance = (cx - x) * (cx - x) + (cy - y) * (cy - y)
        if best is None or distance < best[0]:
            best = (distance, cx, cy)
    if best is None:
        return x, y
    return best[1], best[2]


def body_position_ratio(
    x: int,
    y: int,
    width: int,
    height: int,
    screen: Rect,
    body_local: Rect,
) -> tuple[float, float]:
    """窗口位置在「身体可完整落在该屏」的合法范围里的比例。

    与 ``position_ratio`` 的区别：分母不是 ``screen.width - window.width``，
    而是身体贴左/贴右时窗口左上角的移动范围。身体贴边时窗口可以部分出屏，
    比例仍能精确往返。
    """
    del width, height
    left, top, screen_w, screen_h = screen
    bx, by, bw, bh = body_local
    min_x = left - bx
    max_x = left + screen_w - bx - bw
    min_y = top - by
    max_y = top + screen_h - by - bh
    span_x = max_x - min_x
    span_y = max_y - min_y
    rx = 0.5 if span_x <= 0 else (x - min_x) / span_x
    ry = 0.5 if span_y <= 0 else (y - min_y) / span_y
    return max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))


def band_bounds(body: Rect, screens: tuple[Rect, ...]) -> Rect:
    if not screens:
        return body
    bx, by, bw, bh = body
    right = bx + bw

    def overlaps_x(screen: Rect) -> bool:
        return screen[0] + screen[2] >= bx and screen[0] <= right

    band = [screen for screen in screens if overlaps_x(screen)]
    if not band:
        band = list(screens)
    left = min(screen[0] for screen in band)
    top = min(screen[1] for screen in band)
    right_edge = max(screen[0] + screen[2] for screen in band)
    bottom_edge = max(screen[1] + screen[3] for screen in band)
    return left, top, right_edge - left, bottom_edge - top


def rect_overlap_area(a: Rect, b: Rect) -> int:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def rect_distance(a: Rect, b: Rect) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = max(bx - (ax + aw), ax - (bx + bw), 0)
    dy = max(by - (ay + ah), ay - (by + bh), 0)
    return dx + dy


def ratio_in_span(position: int, start: int, length: int) -> float:
    if length <= 0:
        return 0.5
    return max(0.0, min(1.0, (position - start) / length))


def position_from_ratio(ratio: float, start: int, length: int) -> int:
    return start + round(max(0.0, min(1.0, ratio)) * length)
