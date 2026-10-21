"""拖拽跟随、松手抛掷与碰边反弹。"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QObject, QTimer, Qt

from ..engine import physics
from ..platform import screens as screen_mod

_CONTACT_EPS = 1.0


class MotionController(QObject):
    def __init__(self, window, *, clock=None) -> None:
        super().__init__(window if isinstance(window, QObject) else None)
        self.window = window
        self._clock = clock if callable(clock) else time.monotonic
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

        self.mode = "normal"  # normal / drag / thrown
        self._x = float(window.x())
        self._y = float(window.y())
        self._vx = 0.0
        self._vy = 0.0
        self._target_x = self._x
        self._target_y = self._y
        self._last_tick = self._clock()
        self._trail: list[tuple[float, float, float]] = []
        self._throw_touching: tuple[bool, bool, bool, bool] = (False, False, False, False)

    # ---------------------------------------------------------------- 查询
    @property
    def dragging(self) -> bool:
        return self.mode == "drag"

    @property
    def thrown(self) -> bool:
        return self.mode == "thrown"

    def velocity(self) -> tuple[float, float]:
        return self._vx, self._vy

    def set_velocity(self, vx: float, vy: float) -> None:
        self._vx, self._vy = float(vx), float(vy)
        if self.mode == "normal" and (abs(self._vx) > 1.0 or abs(self._vy) > 1.0):
            # 从「正常」切到「抛掷」必须把内部坐标锚到窗口当前位置：
            # `_x/_y` 只在拖拽/抛掷里维护，normal 期间可能是上一次抛掷的旧值
            # （甚至构造时的 0,0），不重锚就会整只闪现到屏幕另一端。
            self._x, self._y = float(self.window.x()), float(self.window.y())
            self.mode = "thrown"
            self._throw_touching = (False, False, False, False)
            self._last_tick = self._clock()
            self._ensure_timer()
            callback = getattr(self.window, "_on_thrown", None)
            if callable(callback):
                callback()

    # ---------------------------------------------------------------- 拖拽
    def begin_drag(self, x: int, y: int) -> None:
        self.mode = "drag"
        self._x, self._y = float(x), float(y)
        self._target_x, self._target_y = self._x, self._y
        self._vx = self._vy = 0.0
        self._trail = [(self._clock(), self._x, self._y)]
        self._last_tick = self._clock()
        self._ensure_timer()

    def drag_to(self, x: int, y: int) -> None:
        if self.mode != "drag":
            self.begin_drag(self.window.x(), self.window.y())
        self._target_x, self._target_y = float(x), float(y)
        if not bool(self.window.config.get("drag_physics_enabled")):
            self._x, self._y = self._target_x, self._target_y
            self.window.move(int(round(self._x)), int(round(self._y)))
        self._record_trail()
        self._ensure_timer()

    def release(self) -> tuple[float, float]:
        if self.mode != "drag":
            return 0.0, 0.0
        now = self._clock()
        cap = physics.throw_speed_cap(str(self.window.config.get("throw_strength") or "standard"))
        vx, vy = physics.estimate_release_velocity(self._trail, now, cap=cap)
        speed = math.hypot(vx, vy)
        physics_on = bool(self.window.config.get("drag_physics_enabled"))
        drop_gravity = bool(self.window.config.get("drop_gravity_enabled"))
        if (physics_on and speed >= physics.DEAD_ZONE_SPEED) or drop_gravity:
            self.begin_throw(vx, vy)
        else:
            self.stop()
        return vx, vy

    # ---------------------------------------------------------------- 抛掷
    def begin_throw(self, vx: float, vy: float) -> None:
        self.mode = "thrown"
        self._vx, self._vy = float(vx), float(vy)
        self._x, self._y = float(self.window.x()), float(self.window.y())
        self._throw_touching = (False, False, False, False)
        if bool(getattr(self.window, "probe_active", False)):
            effects = self._effects()
            if effects is not None:
                # 兜底入口：主入口是碰撞时 edge_probe.cancel("collision") 前的 arm。
                effects.arm_throw_egg()
        self._last_tick = self._clock()
        self._ensure_timer()
        callback = getattr(self.window, "_on_thrown", None)
        if callable(callback):
            callback()

    def _effects(self):
        return getattr(self.window, "effects", None)

    def stop(self) -> None:
        was_active = self.mode != "normal"
        self.mode = "normal"
        self._vx = self._vy = 0.0
        self._trail.clear()
        self._timer.stop()
        # 落地/停稳都无条件回正（幂等）；探头击飞彩蛋不设飞行时间上限，
        # 但稳定态必须是直立。
        effects = self._effects()
        if effects is not None:
            end = getattr(effects, "end_throw_egg", None)
            if callable(end):
                end()
        if was_active:
            self.window._on_motion_stopped()

    # ---------------------------------------------------------------- tick
    def _ensure_timer(self) -> None:
        if not self._timer.isActive():
            self._last_tick = self._clock()
            self._timer.start()

    def _tick(self) -> None:
        now = self._clock()
        dt = max(0.001, min(0.05, now - self._last_tick))
        self._last_tick = now
        if self.mode == "drag":
            self._tick_drag(dt)
        elif self.mode == "thrown":
            self._tick_throw(dt, now)

    def _tick_drag(self, dt: float) -> None:
        if not bool(self.window.config.get("drag_physics_enabled")):
            return
        self._vx = physics.spring_velocity(self._vx, self._x, self._target_x, dt)
        self._vy = physics.spring_velocity(self._vy, self._y, self._target_y, dt)
        self._x += self._vx * dt
        self._y += self._vy * dt
        x, y = self.window._clamp_position(int(round(self._x)), int(round(self._y)))
        self._x, self._y = float(x), float(y)
        self.window.move(x, y)
        self._record_trail()

    def _tick_throw(self, dt: float, now: float) -> None:
        left, top, right, bottom = self._throw_bounds()
        prev_speed = math.hypot(self._vx, self._vy)
        px, py, vx, vy, bounced = physics.throw_step(
            self._x,
            self._y,
            self._vx,
            self._vy,
            dt,
            left,
            top,
            right,
            bottom,
        )
        self._x, self._y, self._vx, self._vy = px, py, vx, vy
        touching = (
            px <= left + _CONTACT_EPS,
            px >= right - _CONTACT_EPS,
            py >= bottom - _CONTACT_EPS,
            py <= top + _CONTACT_EPS,
        )
        # 每次「离地→接触」都要反馈，而不是一整个抛掷会话只响一次。
        if any(now_on and not before for now_on, before in zip(touching, self._throw_touching)):
            if prev_speed >= physics.BOUNCE_TRIGGER_SPEED:
                self.window._on_motion_bounce()
        self._throw_touching = touching
        self.window.move(int(round(px)), int(round(py)))
        effects = self._effects()
        if effects is not None and getattr(effects, "throw_egg_active", False):
            effects.update_throw_egg(vx, vy, bounced)
        speed = math.hypot(vx, vy)
        if physics.is_at_rest(py, vx, vy, bottom, bounced, speed):
            self.stop()

    def _throw_bounds(self) -> tuple[float, float, float, float]:
        layout = self.window._layout or screen_mod.snapshot_from_qt()
        screen = screen_mod.screen_for_rect(self.window.body_rect(), layout)
        if screen is None:
            screen = layout.by_name(layout.primary)
        if screen is None:
            return 0.0, 0.0, float(self.window.width()), float(self.window.height())
        bx, by, bw, bh = self.window.body_local_rect()
        left = screen.x - bx
        top = screen.y - by
        right = screen.x + screen.width - bx - bw
        bottom = screen.y + screen.height - by - bh
        return float(left), float(top), float(max(left, right)), float(max(top, bottom))

    def _record_trail(self) -> None:
        now = self._clock()
        self._trail.append((now, self._x, self._y))
        cutoff = now - physics.TRAIL_KEEP_SEC
        while self._trail and self._trail[0][0] < cutoff:
            self._trail.pop(0)

    def shutdown(self) -> None:
        self._timer.stop()
