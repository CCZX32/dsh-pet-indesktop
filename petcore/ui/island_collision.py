"""灵动岛 × 桌宠碰撞接线：同步硬墙 + 抛掷反射 + 拖岛拍鱼（唯一 Qt 层）。

主分支把这件事写在 ``pet/island_collision.py``（单窗口拓扑的同步硬墙）与
``pet/island_bridge.py``（overlay 拓扑的静态成员 + 岛速采样）；petcore 只有一套
拓扑（每只桌宠一个顶层窗口），于是取两者之长：

- **墙机制照 legacy**：身体框在位置出口被同步钳出岛区，和屏幕边界同级。没有
  采样间隙，就没有「钻进 → 被弹 → 再钻回」的抽搐（主分支 issue #146 的教训：
  30Hz 判定 + 速度回弹修不干净）。
- **岛速采样照桥**：一次 ``mouseMoveEvent`` 会喂两遍同一 rect、松手那一拍是夹回/
  落位、展开动画峰值上千 px/s —— 每一条都对应一个实机回归，闸门缺一个就出错。

三个挂接点（全在别处，本模块只提供纯函数入口）：

1. ``PetWindow._clamp_position`` → :meth:`IslandField.clamp`：拖拽/漫游/碰撞分离/
   缩放/换屏共用的位置出口；
2. ``MotionController._tick_throw`` → :meth:`IslandField.reflect_throw`：抛掷 tick
   绕开了位置出口，必须在物理步里反射；
3. ``DynamicIsland`` 的几何回调 → :meth:`IslandField.on_geometry_changed`：岛自己
   动了（拖岛拍鱼 / 停靠 / 展开），把被压住的桌宠经同一条出口推出去。

本模块**不建定时器、不建线程**：全部事件驱动。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import QObject

from ..engine import island_field as field
from ..engine import physics

logger = logging.getLogger("petcore.ui.island_collision")

#: 同一只桌宠两次「真撞」反馈的最小间隔（防一帧多弹 / 音效连发）。
HIT_COOLDOWN_S = 0.15
#: 挤压与碰撞音效的错峰间隔（主分支 ``_SQUASH_INTERVAL_S``）。
SQUASH_INTERVAL_S = 0.25
#: 岛果冻强度换算：接近速度 ÷ 400，上限 3.0（主分支 ``BUMP_STRENGTH_DIVISOR``）。
BUMP_STRENGTH_DIVISOR = 400.0
BUMP_STRENGTH_MAX = 3.0
#: 「在岛顶停稳」的判据：法线朝上 + 竖直速度已很小 + 没有明显横向拖动。
RESTED_NY = -0.4
RESTED_MAX_VX = physics.REST_VX * 4.0


@dataclass(frozen=True, slots=True)
class ThrowResolution:
    """抛掷撞岛的结果：修正后的位置/速度 + 是否命中、是否落稳、墙法线。"""

    px: float
    py: float
    vx: float
    vy: float
    hit: bool = False
    rested: bool = False
    nx: float = 0.0
    ny: float = 0.0


class IslandField(QObject):
    """把灵动岛当桌宠世界的静态障碍物（宿主持有，``host.island_field``）。"""

    def __init__(
        self,
        island,
        config,
        pets_provider: Callable[[], Iterable] | None = None,
        *,
        clock: Callable[[], float] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent if isinstance(parent, QObject) else None)
        self.island = island
        self.config = config
        self._pets_provider = pets_provider or (lambda: ())
        self._clock = clock if callable(clock) else time.monotonic
        self._vx = 0.0
        self._vy = 0.0
        self._last_rect: tuple[float, float, float, float] | None = None
        self._last_time: float | None = None
        self._last_dragging = False
        self._contact: dict[int, tuple[float, float, float]] = {}
        self._cooldown: dict[int, float] = {}
        self._feedback_at: dict[int, float] = {}
        #: 落在胶囊**上表面**停稳的桌宠 → 停稳时的窗口 y。岛走开后它们会悬空，
        #: 必须在下一拍补一次自由落体（normal 态没有重力通道）。
        self._resting: dict[int, int] = {}

    # ---------------------------------------------------------------- 查询
    def enabled(self) -> bool:
        """总开关：``island_collision``（默认开）。关掉后墙立刻消失，无需重启。"""
        try:
            return bool(self.config.get("island_collision", True))
        except Exception:  # noqa: BLE001 - 配置读失败按打开处理（默认值就是开）
            return True

    def stadium(self) -> field.Stadium | None:
        """当前碰撞体；岛不可见/细条/几何动画/开关关一律 ``None``（不建幽灵墙）。"""
        if not self.enabled():
            return None
        getter = getattr(self.island, "collision_rect", None)
        if not callable(getter):
            return None
        try:
            rect = getter()
        except RuntimeError:  # 岛窗口已销毁
            return None
        if rect is None:
            return None
        return field.stadium_from_rect(*rect)

    def island_velocity(self) -> tuple[float, float]:
        return self._vx, self._vy

    # ---------------------------------------------------------------- 位置出口
    def clamp(self, window, x: int, y: int, *, settle: bool = True) -> tuple[int, int]:
        """把「提议窗口位置」钳出岛区；重叠时按相对接近速度决定真撞/轻贴。

        与屏幕边界同语义：身体框永远进不了岛区。真撞（相对接近速度 ≥
        ``IMPULSE_MIN_APPROACH_SPEED``、且冷却已过）走「冲量 + 进抛掷 + 音效 +
        挤压 + 岛果冻」；其余只推出并把自主移动计划收掉（否则会原地踏步顶墙）。

        ``settle=False`` 只做几何（发起漫游时会把 60–240px 外的**目标点**也喂进来，
        那既不是移动也不是接近速度：结算它会把站着不动的桌宠凭空弹飞）。
        """
        stadium = self.stadium()
        if stadium is None:
            return x, y
        try:
            if not window.isVisible() or bool(getattr(window, "probe_active", False)):
                # 探头姿态是「身体按设计探出屏幕」的旋转态：豁免岛墙（主分支同款）。
                self._contact.pop(id(window), None)
                return x, y
            bx, by, bw, bh = window.body_local_rect()
        except RuntimeError:
            return x, y
        body = (float(x + bx), float(y + by), float(bw), float(bh))
        pushed = field.push_out(body, stadium)
        now = self._clock()
        if pushed is None:
            if settle:
                # 只记真实移动的"提议位置"：`settle=False`（漫游目标预钳）那一次
                # 是 60–240px 外的落点，记进来会让下一次真移动拿到假基线。
                self._contact[id(window)] = (body[0], body[1], now)
            return x, y
        new_x = int(round(pushed.left - bx))
        new_y = int(round(pushed.top - by))
        if not settle:
            return new_x, new_y
        previous = self._contact.get(id(window))
        self._contact[id(window)] = (body[0], body[1], now)
        self._resting.pop(id(window), None)
        motion = getattr(window, "motion", None)
        if bool(getattr(window, "dragging", False)) or bool(
            getattr(motion, "thrown", False)
        ):
            # 拖拽中不结算（同宠-宠规则：不能让鼠标把别人一路顶走）；抛掷速度的
            # 反射在 `reflect_throw`（物理步）里做，这里只保证不穿透。
            return new_x, new_y
        dt = None if previous is None else now - previous[2]
        pet_vx, pet_vy = field.tracked_velocity(
            None if previous is None else (previous[0], previous[1]),
            (body[0], body[1]),
            -1.0 if dt is None else dt,
        )
        vn = field.relative_approach(
            (pet_vx, pet_vy), (self._vx, self._vy), (pushed.nx, pushed.ny)
        )
        key = id(window)
        if vn < -field.IMPULSE_MIN_APPROACH_SPEED and (
            now - self._cooldown.get(key, 0.0) >= HIT_COOLDOWN_S
        ):
            self._cooldown[key] = now
            self._bounce(window, vn, pushed)
        else:
            self._light_contact(window)
        return new_x, new_y

    def _bounce(self, window, vn: float, pushed: field.PushOut) -> None:
        """非抛掷真撞：冲量 → 软限速 → 进抛掷 + 三档反馈（撞岛像撞弹床）。"""
        vx, vy = field.impulse_velocity(vn, (pushed.nx, pushed.ny))
        speed = math.hypot(vx, vy)
        try:
            cap = physics.throw_speed_cap(
                str(window.config.get("throw_strength") or "standard")
            )
        except Exception:  # noqa: BLE001 - 配置异常用默认档
            cap = physics.throw_speed_cap("standard")
        capped = physics.soft_clamp_speed(speed, cap=cap)
        if speed > 0.0 and capped > 0.0:
            scale = capped / speed
            vx *= scale
            vy *= scale
        motion = getattr(window, "motion", None)
        setter = getattr(motion, "set_velocity", None)
        if callable(setter):
            try:
                setter(vx, vy)
            except RuntimeError:
                return
        self.notify_hit(window, -vn, (pushed.nx, pushed.ny))

    def _light_contact(self, window) -> None:
        """轻贴：只推出，不响不挤不弹；把自主移动计划收掉（否则顶着墙原地踏步）。"""
        if getattr(window, "_move_plan", None) is None:
            return
        abort = getattr(window, "abort_move_plan", None)
        if callable(abort):
            try:
                abort()
            except RuntimeError:
                return

    def notify_hit(self, window, strength: float, normal: tuple[float, float]) -> None:
        """撞岛反馈：挤压 + 音效 + 岛果冻，**0.25s 共享闸**（主分支口径）。

        两条链都走这里：非抛掷撞岛（:meth:`clamp`）与抛掷撞墙
        （:meth:`reflect_throw` → motion）。各留一份节流会双响：被岛拍飞之后
        追着撞墙，两个通道各自「第一次」就是两声。
        """
        now = self._clock()
        key = id(window)
        if now - self._feedback_at.get(key, 0.0) < SQUASH_INTERVAL_S:
            return
        self._feedback_at[key] = now
        feedback = getattr(window, "island_hit_feedback", None)
        if callable(feedback):
            try:
                feedback()
            except Exception:  # noqa: BLE001 - 反馈坏了不许挡住物理
                logger.debug("island hit feedback failed", exc_info=True)
        bump = getattr(self.island, "bump", None)
        if callable(bump):
            try:
                bump(
                    min(BUMP_STRENGTH_MAX, max(0.0, strength) / BUMP_STRENGTH_DIVISOR),
                    -normal[0],
                    -normal[1],
                )
            except Exception:  # noqa: BLE001 - 岛动效失败不影响碰撞
                logger.debug("island bump failed", exc_info=True)

    # ---------------------------------------------------------------- 抛掷反射
    def reflect_throw(self, window, px: float, py: float, vx: float, vy: float) -> ThrowResolution:
        """抛掷步里撞岛：法向反射（``e=physics.RESTITUTION``）并把身体钉在墙外。

        ``rested`` 表示「落在岛顶且竖直速度已很小」——调用方应当当成落地收尾，
        否则桌宠会在岛顶小反弹到天荒地老（``physics.is_at_rest`` 只认屏幕底边，
        motion 会永远卡在 thrown）。
        """
        stadium = self.stadium()
        if stadium is None:
            return ThrowResolution(px, py, vx, vy)
        try:
            if bool(getattr(window, "probe_active", False)):
                return ThrowResolution(px, py, vx, vy)
            bx, by, bw, bh = window.body_local_rect()
        except RuntimeError:
            return ThrowResolution(px, py, vx, vy)
        body = (float(px + bx), float(py + by), float(bw), float(bh))
        pushed = field.push_out(body, stadium)
        if pushed is None:
            return ThrowResolution(px, py, vx, vy)
        rvx, rvy = field.reflect_velocity((vx, vy), (pushed.nx, pushed.ny), field.RESTITUTION)
        rest_y = int(round(pushed.top - by))
        rested = (
            pushed.ny <= RESTED_NY
            and float(vy) > 0.0
            and float(vy) < physics.GROUND_BOUNCE_STOP_VY
            and abs(rvx) < RESTED_MAX_VX
        )
        self._resting.pop(id(window), None)
        if rested:
            rvx = 0.0
            rvy = 0.0
            # 记住「停稳在胶囊顶上」的位置（= 返回给 motion 的那一帧 y）：normal 态
            # 没有重力，岛被拖走后它会悬在半空；用当时的位置判断「用户有没有自己挪走」。
            self._resting[id(window)] = rest_y
        return ThrowResolution(
            pushed.left - bx,
            pushed.top - by,
            rvx,
            rvy,
            hit=True,
            rested=rested,
            nx=pushed.nx,
            ny=pushed.ny,
        )

    # ---------------------------------------------------------------- 岛移动
    def on_geometry_changed(self) -> None:
        """岛几何变化：采样岛速 → 把被压住的桌宠经唯一位置出口推出/拍飞。"""
        if not self.enabled():
            self.reset()
            return
        getter = getattr(self.island, "collision_rect", None)
        try:
            rect = getter() if callable(getter) else None
        except RuntimeError:
            self.reset()
            return
        if rect is None:
            # 隐藏 / 细条 / 几何动画：墙关着，速度没有意义，基线也要作废（否则
            # 动画或换屏之后的第一拍会拿旧基线算出幽灵速度）。但**不要**清冷却/
            # 反馈表：动画会 60 次/秒走到这里，清一次就等于把 0.25s 单闸关掉。
            self.reset_velocity()
            return
        dragging = bool(getattr(self.island, "dragging", False))
        released = self._last_dragging and not dragging
        now = self._clock()
        current = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        dt = None if self._last_time is None else now - self._last_time
        sample = field.sample_island_velocity(
            self._last_rect, current, dt, dragging=dragging, released=released
        )
        if sample.keep_velocity:
            # 同 rect 的配对上报：保住上一拍速度，别把正在甩的岛当成停了。
            self._last_time = now
        elif not sample.update_baseline:
            # 高频回调（一次 mouseMoveEvent 喂两遍同一 rect）：既不清零也不刷新
            # 基线——清零会让拖拽全程岛速恒 0，退化成只推挤不弹飞。
            pass
        else:
            self._last_rect = current
            self._last_time = now
            self._vx = sample.vx
            self._vy = sample.vy
        self._last_dragging = dragging
        self._push_out_pets()
        capsule = self.stadium()
        if capsule is not None:
            self._drop_orphaned_resting(capsule)

    def _drop_orphaned_resting(self, stadium: field.Stadium) -> None:
        """岛走开后，原本停稳在胶囊顶上的桌宠要自由落体（normal 态没有重力）。"""
        if not self._resting:
            return
        for key, rest_y in tuple(self._resting.items()):
            window = self._find_window(key)
            if window is None:
                self._resting.pop(key, None)
                continue
            try:
                bx, by, bw, bh = window.body_local_rect()
                body = (
                    float(window.x() + bx),
                    float(window.y() + by),
                    float(bw),
                    float(bh),
                )
                still_there = field.push_out(body, stadium) is not None
                moved = abs(float(window.y()) - float(rest_y)) > 1.0
                if still_there:
                    continue
                self._resting.pop(key, None)
                if moved:
                    continue  # 用户自己把它拖走/点走了：不补重力
                motion = getattr(window, "motion", None)
                setter = getattr(motion, "set_velocity", None)
                if callable(setter):
                    setter(0.0, physics.GRAVITY * 0.1)
            except RuntimeError:
                self._resting.pop(key, None)

    def _find_window(self, key: int):
        try:
            windows = list(self._pets_provider() or ())
        except Exception:  # noqa: BLE001
            return None
        for window in windows:
            if window is not None and id(window) == key:
                return window
        return None

    def _prune_stale_keys(self) -> None:
        """桌宠关掉后 `id()` 会复用：不清表会让新窗口继承旧接触/冷却。"""
        if not (self._contact or self._cooldown or self._feedback_at or self._resting):
            return
        try:
            live = {id(window) for window in (self._pets_provider() or ()) if window is not None}
        except Exception:  # noqa: BLE001
            return
        for table in (self._contact, self._cooldown, self._feedback_at, self._resting):
            for key in tuple(table):
                if key not in live:
                    table.pop(key, None)

    def _push_out_pets(self) -> None:
        """岛压住了谁就把谁经 ``_clamp_position`` 推出去（真撞/轻贴共用一条链）。"""
        stadium = self.stadium()
        if stadium is None:
            return
        try:
            windows = list(self._pets_provider() or ())
        except Exception:  # noqa: BLE001 - 宿主还没建好宠物表
            return
        self._prune_stale_keys()
        for window in windows:
            if window is None:
                continue
            try:
                if not window.isVisible() or bool(getattr(window, "dragging", False)):
                    continue
                if bool(getattr(window, "probe_active", False)):
                    continue
                bx, by, bw, bh = window.body_local_rect()
                body = (
                    float(window.x() + bx),
                    float(window.y() + by),
                    float(bw),
                    float(bh),
                )
                if field.push_out(body, stadium) is None:
                    continue
                x, y = window._clamp_position(window.x(), window.y())
                if (x, y) != (window.x(), window.y()):
                    window.move(x, y)
            except RuntimeError:
                continue

    # ---------------------------------------------------------------- 生命周期
    def reset_velocity(self) -> None:
        """只清岛速/采样基线/接触表：几何动画与隐藏态每帧都走这里，不许动节流表。"""
        self._vx = 0.0
        self._vy = 0.0
        self._last_rect = None
        self._last_time = None
        self._last_dragging = False
        self._contact.clear()

    def reset(self) -> None:
        """全部清空：岛关闭/应用退出时用（无定时器，随时可调）。"""
        self.reset_velocity()
        self._cooldown.clear()
        self._feedback_at.clear()
        self._resting.clear()
