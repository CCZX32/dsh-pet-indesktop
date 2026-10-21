from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..engine.geometry import (
    CORNER_MARGIN,
    Rect,
    body_at,
    clamp_body,
    clamp_position,
    rect_distance,
    rect_overlap_area,
)


@dataclass(frozen=True)
class ScreenInfo:
    name: str
    x: int
    y: int
    width: int
    height: int
    dpr: float = 1.0

    @property
    def rect(self) -> Rect:
        return self.x, self.y, self.width, self.height

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass(frozen=True)
class ScreenLayout:
    screens: tuple[ScreenInfo, ...]
    primary: str

    def by_name(self, name: str | None) -> ScreenInfo | None:
        if not name:
            return None
        for screen in self.screens:
            if screen.name == name:
                return screen
        return None

    def rects(self) -> tuple[Rect, ...]:
        return tuple(screen.rect for screen in self.screens)

    def contains(self, name: str) -> bool:
        return self.by_name(name) is not None


def snapshot_from_qt(app=None) -> ScreenLayout:
    """Capture the current logical screen layout from Qt.

    ``availableGeometry`` is already in logical coordinates, so ``dpr`` is
    recorded for display purposes only and never scales the rectangle.
    """
    application = app
    if application is None:
        from PySide6.QtGui import QGuiApplication

        application = QGuiApplication.instance()
    if application is None:
        return ScreenLayout((), "")

    infos: list[ScreenInfo] = []
    for screen in application.screens():
        geometry = screen.availableGeometry()
        infos.append(
            ScreenInfo(
                name=screen.name(),
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
                dpr=float(screen.devicePixelRatio()),
            )
        )

    primary_screen = application.primaryScreen()
    if primary_screen is not None:
        primary = primary_screen.name()
    elif infos:
        primary = infos[0].name
    else:
        primary = ""
    return ScreenLayout(tuple(infos), primary)


def _rank(screen: ScreenInfo, layout: ScreenLayout) -> tuple[bool, str]:
    return screen.name != layout.primary, screen.name


def screen_for_rect(rect: Rect, layout: ScreenLayout) -> ScreenInfo | None:
    if not layout.screens:
        return None
    overlaps = [(screen, rect_overlap_area(rect, screen.rect)) for screen in layout.screens]
    best_overlap = max(area for _, area in overlaps)
    if best_overlap > 0:
        return min((screen for screen, area in overlaps if area == best_overlap), key=lambda s: _rank(s, layout))
    distances = [(screen, rect_distance(rect, screen.rect)) for screen in layout.screens]
    best_distance = min(distance for _, distance in distances)
    return min((screen for screen, distance in distances if distance == best_distance), key=lambda s: _rank(s, layout))


def nearest_screen(rect: Rect, layout: ScreenLayout, *, exclude: Iterable[str] = ()) -> ScreenInfo | None:
    excluded = set(exclude)
    candidates = [screen for screen in layout.screens if screen.name not in excluded]
    if not candidates:
        return None
    distances = [(screen, rect_distance(rect, screen.rect)) for screen in candidates]
    best_distance = min(distance for _, distance in distances)
    return min((screen for screen, distance in distances if distance == best_distance), key=lambda s: _rank(s, layout))


def clamp_rect(rect: Rect, screen: ScreenInfo) -> Rect:
    x, y, width, height = rect
    clamped_x, clamped_y = clamp_position(x, y, width, height, (screen.x, screen.y, screen.width, screen.height))
    return clamped_x, clamped_y, width, height


def _state_value(state: object, key: str) -> Any:
    if isinstance(state, Mapping):
        return state.get(key)
    return getattr(state, key, None)


def restore_position(
    state: object,
    layout: ScreenLayout,
    width: int,
    height: int,
    *,
    body_local: Rect | None = None,
) -> tuple[int, int, str]:
    if not layout.screens:
        return 0, 0, ""

    screen_name = _state_value(state, "screen_name")
    pos_x = _state_value(state, "pos_x")
    pos_y = _state_value(state, "pos_y")
    rx = _state_value(state, "rx")
    ry = _state_value(state, "ry")
    body_rx = _state_value(state, "body_rx")
    body_ry = _state_value(state, "body_ry")

    screen = layout.by_name(screen_name)
    if screen is None and pos_x is not None and pos_y is not None:
        probe = (int(pos_x), int(pos_y), width, height)
        if body_local is not None:
            probe = body_at(int(pos_x), int(pos_y), body_local)
        candidate = screen_for_rect(probe, layout)
        if candidate is not None and rect_overlap_area(probe, candidate.rect) > 0:
            screen = candidate
    if screen is None:
        screen = layout.by_name(layout.primary) or layout.screens[0]

    if body_local is not None and body_local == (0, 0, width, height):
        body_local = None
    body = body_local
    if body is not None:
        bx, by, bw, bh = body
        if body_rx is not None:
            min_x = screen.x - bx
            span_x = screen.width - bw
            x = min_x if span_x <= 0 else min_x + round(float(body_rx) * span_x)
        elif rx is not None:
            x = screen.x + round(float(rx) * (screen.width - width))
        elif pos_x is not None:
            x = int(pos_x)
        else:
            x = screen.right - CORNER_MARGIN - bx - bw
        if body_ry is not None:
            min_y = screen.y - by
            span_y = screen.height - bh
            y = min_y if span_y <= 0 else min_y + round(float(body_ry) * span_y)
        elif ry is not None:
            y = screen.y + round(float(ry) * (screen.height - height))
        elif pos_y is not None:
            y = int(pos_y)
        else:
            y = screen.bottom - by - bh
        clamped_x, clamped_y = clamp_body(x, y, body, screen.rect)
        return clamped_x, clamped_y, screen.name

    if rx is not None:
        x = screen.x + round(float(rx) * (screen.width - width))
    elif pos_x is not None:
        x = int(pos_x)
    else:
        x = screen.right - width - CORNER_MARGIN
    if ry is not None:
        y = screen.y + round(float(ry) * (screen.height - height))
    elif pos_y is not None:
        y = int(pos_y)
    else:
        y = screen.bottom - height - CORNER_MARGIN

    clamped_x, clamped_y, _, _ = clamp_rect((x, y, width, height), screen)
    return clamped_x, clamped_y, screen.name


def adopt_position(
    x: int,
    y: int,
    width: int,
    height: int,
    layout: ScreenLayout,
    current_name: str | None,
    *,
    body_local: Rect | None = None,
) -> tuple[int, int, str]:
    rect = (x, y, width, height)
    probe = body_at(x, y, body_local) if body_local is not None else rect
    target = screen_for_rect(probe, layout)
    if target is None:
        return x, y, current_name or ""
    if rect_overlap_area(probe, target.rect) == 0:
        current = layout.by_name(current_name)
        if current is not None:
            target = current
    if body_local is not None:
        clamped_x, clamped_y = clamp_body(x, y, body_local, target.rect)
        return clamped_x, clamped_y, target.name
    clamped_x, clamped_y, _, _ = clamp_rect(rect, target)
    return clamped_x, clamped_y, target.name


def position_ratio(x: int, y: int, width: int, height: int, screen: ScreenInfo) -> tuple[float, float]:
    span_x = screen.width - width
    span_y = screen.height - height
    rx = 0.0 if span_x <= 0 else (x - screen.x) / span_x
    ry = 0.0 if span_y <= 0 else (y - screen.y) / span_y
    return max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))


def migrate_layout(
    previous: ScreenLayout,
    current: ScreenLayout,
    state: object,
    width: int,
    height: int,
    *,
    body_local: Rect | None = None,
) -> tuple[int, int, str] | None:
    if not current.screens:
        return None
    screen_name = _state_value(state, "screen_name")
    if not screen_name or current.contains(str(screen_name)):
        return None
    return restore_position(state, current, width, height, body_local=body_local)
