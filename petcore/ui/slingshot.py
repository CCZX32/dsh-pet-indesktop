"""弹弓蓄力瞄准：拖拽中右键进入，松左键发射，Esc/右键取消。"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..engine import physics


class SlingshotController:
    def __init__(self, window) -> None:
        self.window = window
        self.aiming = False
        self.suppress_until = 0.0
        self._anchor_cursor = QPointF()
        self._cursor = QPointF()
        self._anchor_window = None

    def maybe_enter(self, anchor: QPointF, cursor: QPointF) -> bool:
        if self.aiming:
            return True
        if not bool(self.window.config.get("slingshot_enabled", True)):
            return False
        if not getattr(self.window, "dragging", False):
            return False
        self.aiming = True
        self._anchor_cursor = QPointF(anchor)
        self._cursor = QPointF(cursor)
        self._anchor_window = self.window.pos()
        # 瞄准期间位置钉在锚点；不退回到 normal，避免触发落地回调。
        self.window.motion._timer.stop()
        self.window.update()
        return True

    def update(self, cursor: QPointF) -> None:
        if not self.aiming:
            return
        self._cursor = QPointF(cursor)
        self.window.update()

    def pull(self) -> QPointF:
        return self._anchor_cursor - self._cursor

    def distance(self) -> float:
        pull = self.pull()
        return math.hypot(pull.x(), pull.y())

    def launch(self) -> bool:
        if not self.aiming:
            return False
        distance = self.distance()
        pull = self.pull()
        if distance < physics.SLINGSHOT_MIN_DISTANCE:
            self.cancel()
            return False
        cap = physics.throw_speed_cap(
            str(self.window.config.get("throw_strength") or "standard")
        )
        speed = physics.slingshot_speed(
            distance,
            physics.SLINGSHOT_MIN_DISTANCE,
            physics.SLINGSHOT_MAX_DISTANCE,
            cap,
        )
        if speed <= 0.0:
            self.cancel()
            return False
        ux, uy = pull.x() / distance, pull.y() / distance
        if self._anchor_window is not None:
            self.window.move(self._anchor_window)
        self.aiming = False
        self.window.motion.begin_throw(ux * speed, uy * speed)
        self.window.update()
        self.suppress_until = time.monotonic() + 0.35
        return True

    def cancel(self) -> None:
        if not self.aiming:
            return
        self.aiming = False
        if self._anchor_window is not None:
            self.window.move(self._anchor_window)
        self._anchor_window = None
        self.window.update()
        self.suppress_until = time.monotonic() + 0.35

    def suppresses_context_menu(self) -> bool:
        """瞄准中或发射/取消后的短暂窗口内，右键不应弹菜单。"""
        return self.aiming or time.monotonic() < self.suppress_until

    def paint(self, painter) -> None:
        if not self.aiming:
            return
        pull = self.pull()
        distance = self.distance()
        if distance <= 1e-6:
            return
        progress = max(0.0, min(1.0, distance / physics.SLINGSHOT_MAX_DISTANCE))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(104, 174, 196, 180), 2.0))
        painter.drawLine(self._cursor, self._anchor_cursor)
        bx, by, bw, bh = self.window.body_local_rect()
        anchor = QPointF(bx + bw / 2.0, by + bh / 2.0)
        speed = physics.slingshot_speed(
            distance,
            physics.SLINGSHOT_MIN_DISTANCE,
            physics.SLINGSHOT_MAX_DISTANCE,
            physics.throw_speed_cap(str(self.window.config.get("throw_strength") or "standard")),
        )
        ux, uy = pull.x() / distance, pull.y() / distance
        points = physics.slingshot_trajectory(ux * speed, uy * speed)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (dx, dy) in enumerate(points):
            fade = 1.0 - index / max(1, len(points) - 1)
            painter.setBrush(QColor(104, 174, 196, int(150 * fade)))
            radius = (2.8 - 1.35 * (1.0 - fade)) * progress
            painter.drawEllipse(QPointF(anchor.x() + dx, anchor.y() + dy), radius, radius)
        painter.restore()
