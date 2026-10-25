from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

from .. import paths
from ..config import Config
from ..contracts.content import AnimationSpec, CharacterSpec
from ..engine.animation import AnimationPlayer
from ..engine.behavior import (
    BehaviorDirector,
    KIND_MOVE,
    KIND_TURN,
    normalize_weights,
)
from ..engine.catalog import GraphCatalog
from ..engine.enums import AnimatType, GraphType
from ..engine.geometry import (
    CORNER_MARGIN,
    DRAG_THRESHOLD,
    MOVE_MARGIN,
    MOVE_MAX_PX,
    MOVE_MIN_PX,
    SCALE_STEPS,
    body_local_rect,
    body_position_ratio,
    content_size,
)
from ..engine.motion import (
    choose_move_direction,
    clamp_to_screen,
    clamp_to_screens,
    move_position_at_frame,
    quantize_move,
    stride_for,
)
from ..engine.pet_state import PetState
from ..media.click_sound import ClickSoundPair, choose_click_sound, resolve_click_sound_candidates
from ..media.images import screen_dpr
from ..media.library import ClipLibrary
from ..media.sound import SoundPlayer
from ..platform import screens as screen_mod
from ..platform.win import (
    PerPixelInputController,
    apply_click_through,
    apply_stream_window,
    apply_tool_window,
)
from .bubble import SpeechBubble
from .easter_egg import DEFAULT_EASTER_EGG_TITLE, EasterEggController
from .edge_probe import EdgeProbeController
from .effects import EffectController
from .feeding import FeedingController
from .motion import MotionController
from .renderer import frame_pixmap
from .slingshot import SlingshotController

logger = logging.getLogger("petcore.ui.window")


@dataclass
class ScreenState:
    screen_name: str | None = None
    rx: float | None = None
    ry: float | None = None
    body_rx: float | None = None
    body_ry: float | None = None
    pos_x: float | None = None
    pos_y: float | None = None


class PetWindow(QWidget):
    #: 桌宠移动后发出（拖动、抛掷、漫游、碰撞分离都会走 ``moveEvent``）；
    #: 聊天窗用它做「跟随桌宠」的合并定位。
    pet_moved = Signal()

    def __init__(self, config: Config, root: Path, host, *, slot: int = 0):
        super().__init__(None)
        self.config = config
        self.root = Path(root)
        self.host = host
        self.slot = int(slot)
        self.is_primary = self.slot == 0
        self.click_through = bool(config.get("click_through"))
        self.always_on_top = bool(config.get("always_on_top"))
        self.stream_capture_mode = bool(config.get("stream_capture_mode"))
        self.dragging = False
        self._suppress_context_menu = False
        self.state = PetState(scale=float(config.get("scale") or 0.72))
        self.character: CharacterSpec | None = None
        self._body_local = body_local_rect(None, self.state.scale)
        self._head_local = self._body_local
        self._probe_angle = 0.0
        self._probe_exposure = 1.0
        self._edge_probe = EdgeProbeController(self)
        self.effects = EffectController(self)
        self.easter = EasterEggController(self)
        self.motion = MotionController(self)
        self.slingshot = SlingshotController(self)
        self.feeding = FeedingController(self)
        self.library = ClipLibrary(str(config.get("frameseq") or "auto"))
        self.sound = SoundPlayer(float(config.get("volume") or 0.8))
        self._click_sound_pair = ClickSoundPair(self.sound.play)
        self._click_sound_token: int | None = None
        self.bubble = SpeechBubble()
        self.bubble.clicked.connect(self._on_bubble_clicked)
        self.bubble.set_text_scale(self._text_scale_factor())
        self.bubble.set_stream_mode(self.stream_capture_mode)
        self._clip = None
        self._image = None
        self._pixmap = None
        self._action_kind: str | None = None
        self._pending_flip = False
        self._loop_active = False
        self._probe_drag_throw = False
        self._move_plan: dict | None = None
        self._move_loop = 0
        self._move_last_frame = -1
        self._press_global: QPoint | None = None
        self._press_pos: QPoint | None = None
        self._last_cursor_local: QPointF | None = None
        self._click_listeners: list = []
        self._drop_listeners: list = []
        self._bubble_follow_pending = False
        self._gap_until = 0.0
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(16)
        self._move_timer.timeout.connect(self._tick_move)
        self._input_controller: PerPixelInputController | None = None
        self._layout = None
        self._apply_flags(initial=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAcceptDrops(True)

    def available_characters(self) -> list[CharacterSpec]:
        return list(self.host.characters())

    @property
    def character_id(self) -> str:
        return self.character.id if self.character is not None else ""

    def _update_body_local(self) -> None:
        box = self.character.body_box if self.character is not None else None
        canvas = self.character.canvas if self.character is not None else None
        head = self.character.head_box if self.character is not None else None
        if canvas is None:
            self._body_local = body_local_rect(box, self.state.scale)
            self._head_local = (
                body_local_rect(head, self.state.scale) if head is not None else self._body_local
            )
        else:
            self._body_local = body_local_rect(box, self.state.scale, canvas)
            self._head_local = (
                body_local_rect(head, self.state.scale, canvas)
                if head is not None
                else self._body_local
            )

    def body_local_rect(self) -> tuple[int, int, int, int]:
        return self._body_local

    def body_rect(self) -> tuple[int, int, int, int]:
        bx, by, bw, bh = self._body_local
        return self.x() + bx, self.y() + by, bw, bh

    @property
    def probe_active(self) -> bool:
        return self._edge_probe.active

    def probe_angle(self) -> float:
        return self._probe_angle

    def probe_exposure(self) -> float:
        return self._probe_exposure

    def set_probe_pose(self, angle: float, exposure: float) -> None:
        self._probe_angle = float(angle)
        self._probe_exposure = max(0.0, min(1.0, float(exposure)))
        self.update()

    def move_probe_to(self, x: float) -> None:
        self.move(int(round(x)), self.y())

    def probe_bounds(self) -> tuple[int, int, int, int] | None:
        layout = self._layout or screen_mod.snapshot_from_qt()
        screen = screen_mod.screen_for_rect(
            self.body_rect(), layout
        )
        return screen.rect if screen is not None else None

    def stop_for_probe(self) -> None:
        self._cancel_move_plan()
        self.state.dragging = False
        if self._action_kind not in (None, "idle"):
            self._play_idle()

    def remember_probe_geometry(self) -> None:
        self._remember_geometry()

    def set_edge_probe_enabled(self, enabled: bool, *, persist: bool = True) -> None:
        self._edge_probe.set_enabled(bool(enabled))
        self.config.set("edge_probe_enabled", bool(enabled))
        if persist:
            self.config.save()

    def toggle_edge_probe(self) -> None:
        self.set_edge_probe_enabled(
            not bool(self.config.get("edge_probe_enabled"))
        )

    def start(self, character: CharacterSpec | None = None) -> None:
        character = character or (self.available_characters()[0] if self.available_characters() else None)
        if character is None:
            logger.error("no character available")
            return
        self._activate(character)
        self._restore_geometry()
        self.show()
        if self.stream_capture_mode:
            apply_stream_window(int(self.winId()))
        else:
            apply_tool_window(int(self.winId()))
        self._play_idle()
        click_spec = self.catalog.find_for(GraphType.TOUCH_BODY, AnimatType.SINGLE)
        if click_spec is not None:
            QTimer.singleShot(800, lambda spec=click_spec: self.library.warm_first_frame(spec))
        QTimer.singleShot(200, self._warm_interaction_assets)
        if self.click_through:
            self._apply_click_through()
        else:
            self._input_controller = PerPixelInputController(self, self.is_transparent_at)
        if bool(self.config.get("edge_probe_enabled")):
            QTimer.singleShot(800, self._edge_probe.maybe_enter)

    def _warm_interaction_assets(self) -> None:
        """预热点击素材与音效：第一次点击不该卡在解码/音频后端初始化上。"""
        if self.character is None:
            return
        for spec in self.catalog.specs_for(GraphType.TOUCH_BODY):
            if spec.animat is AnimatType.SINGLE:
                try:
                    self.library.warm_first_frame(spec)
                except Exception:
                    logger.debug("warm click clip failed: %s", spec.name, exc_info=True)
        self.sound.prepare(paths.legacy_asset_root() / "sounds" / "click.wav")
        for candidate in self._click_sound_candidates():
            try:
                self.sound.prepare(candidate)
            except Exception:
                logger.debug("warm click sound failed: %s", candidate, exc_info=True)

    def _click_sound_candidates(self):
        try:
            return resolve_click_sound_candidates(
                self.config.get("click_sound_pack"),
                paths.legacy_asset_root(),
            )
        except Exception:
            return [paths.legacy_asset_root() / "sounds" / "click.wav"]

    def _activate(self, character: CharacterSpec) -> None:
        self._stop_clip()
        self.library.close_all()
        self.library = ClipLibrary(str(self.config.get("frameseq") or "auto"))
        self.character = character
        self.catalog = GraphCatalog(character.animations)
        self.player = AnimationPlayer(self.catalog)
        self.director = BehaviorDirector(
            self.catalog, weights_provider=self._behavior_weights
        )
        self.state.current = None
        self.state.dragging = False
        self.dragging = False
        self._action_kind = None
        self._pending_flip = False
        self._move_timer.stop()
        self._move_plan = None
        self._move_loop = 0
        self._move_last_frame = -1
        self.motion.mode = "normal"
        self.motion._timer.stop()
        self._gap_until = 0.0
        self.effects.reset()
        self.slingshot.aiming = False
        width, height = content_size(self.state.scale)
        self.setFixedSize(width, height)
        self._update_body_local()

    def set_character(self, character_id: str, *, persist: bool = True) -> None:
        self._edge_probe.cancel("character", restore=True)
        for character in self.available_characters():
            if character.id == character_id:
                self.config.set("character", character_id)
                if persist:
                    self.config.save()
                previous = self.pos()
                self._activate(character)
                self.move(previous)
                self._restore_geometry(persist=persist)
                self._play_idle()
                self.update()
                return

    def _apply_flags(self, *, initial: bool = False) -> None:
        if self.stream_capture_mode:
            # 直播捕获：普通顶层窗口（不进 Tool 分支），OBS/直播姬才能枚举到。
            flags = (
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        position = self.pos() if not initial else None
        self.setWindowFlags(flags)
        self.setWindowTitle("dsh-pet core" if self.stream_capture_mode else "")
        if position is not None:
            self.move(position)
        if was_visible and not initial:
            self.show()
        # 气泡与桌宠必须是同一图层：置顶跟着走，否则图片气泡会被桌宠盖住。
        self.bubble.set_host_on_top(self.always_on_top)

    def _play_idle(self) -> None:
        spec = self.player.play(GraphType.IDEL, animat=AnimatType.B_LOOP)
        if spec is None:
            action = self.director.idle() or self.director.choose()
            spec = action.spec if action is not None else None
        if spec is None:
            self._start_fallback()
            return
        self._play_spec(spec, "idle")

    def _play_spec(self, spec: AnimationSpec, kind: str) -> None:
        self._loop_active = False
        if self._effects_lock_active() and not self._spec_allowed_while_locked(spec):
            # 主分支 _effects_filter_switch：探头/彩蛋接管期间只允许待机与转向，
            # 其它素材（act/click/手动播放）一律降级待机。
            idle = self.catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP)
            if idle is None:
                return
            spec, kind = idle, "idle"
        clip = self.library.clip_for(spec)
        if clip is None:
            logger.warning("no clip backend for %s", spec.name)
            self._start_fallback()
            return
        self._cancel_move_plan()
        if self._clip is clip and self.state.current is spec and kind == self._action_kind:
            # 同一 clip 续圈：WebMClip 圈末驻留等 re-arm，硬停会换代并丢末帧。
            clip.start()
            return
        self._stop_clip()
        self._clip = clip
        clip.clear_callbacks()
        clip.on_frame(self._on_frame)
        clip.on_finished(self._on_finished)
        clip.on_error(self._on_error)
        self.player.current = spec
        self.state.current = spec
        self._action_kind = kind
        self._pending_flip = kind == KIND_TURN and not self._effects_lock_active()
        speed = float(self.config.get("playback_speed") or 1.0)
        if abs(speed - 1.0) > 1e-9:
            clip.set_playback_speed(speed)
        clip.start()
        if clip.current_image() is not None:
            self._on_frame(clip.current_frame_number())
        if kind == KIND_MOVE:
            self._begin_move(spec, clip.duration_seconds)

    def _start_fallback(self) -> None:
        clip = self.library.fallback()
        self._stop_clip()
        self._clip = clip
        clip.clear_callbacks()
        clip.on_frame(self._on_frame)
        clip.on_finished(self._on_finished)
        clip.on_error(self._on_error)
        clip.start()

    def _stop_clip(self) -> None:
        if self._clip is not None:
            self._clip.stop()
            self._clip.clear_callbacks()
            self._clip = None

    def _on_frame(self, _number: int) -> None:
        if self._clip is None:
            return
        image = self._clip.current_image()
        self._image = image
        if image is not None:
            self._pixmap = frame_pixmap(
                image,
                self.width(),
                self.height(),
                mirrored=self._mirrored(),
                dpr=screen_dpr(self),
            )
        self._advance_move_from_frame()
        self.update()

    def _mirrored(self) -> bool:
        """``facing == "right"`` 时水平镜像（素材原生朝左，同主分支）。"""
        if self.character is None or self.state.facing != "right":
            return False
        current = self.state.current
        return current is None or current.name not in self.character.text_clips

    def _on_finished(self) -> None:
        if not self.isVisible():
            return
        if self._loop_active:
            # 循环接缝（唱歌/报时）：被探头、击飞、拖拽接管时立即解除，
            # 否则同一段素材一直重播，行为链永远不掷骰。
            if self._effects_lock_active() or self.dragging or self.motion.thrown:
                self._loop_active = False
            else:
                if self._clip is not None:
                    self._clip.start()
                return
        if self._move_plan is not None:
            loops = int(self._move_plan.get("loops") or 1)
            if self._clip is not None and self._move_loop + 1 < loops:
                self._move_loop += 1
                self._move_last_frame = -1
                self._clip.start()
                return
            self._finish_move()
        if self.dragging:
            if self._clip is not None:
                self._clip.start()
            return
        if self.motion.thrown:
            # 飞行/弹跳属于接管态：不掷骰、不切动作，等落地稳定后由
            # _on_motion_stopped() 接回行为链（主分支 THROWN 语义）。
            if self._clip is not None:
                self._clip.start()
            return
        if self._pending_flip:
            self.state.flip()
            self._pending_flip = False
        kind = self._action_kind
        if self._is_idle_dwell(kind):
            # 待机一圈结束就是掷骰时机（主分支 STATE_IDLE 到点 → _roll_next）。
            # 绝不能走 player.advance()：IDEL 是 B_LOOP + loop=True，advance 会
            # 原样返回同一个 idle spec，桌宠就永远停在待机。
            if self._gap_active():
                self._play_idle()
                return
            self._roll_next()
            return
        nxt = self.player.advance()
        if nxt is not None:
            self._play_spec(nxt, kind or "idle")
            return
        self.effects.consume_click_finished()
        self._finish_action(kind)

    def _is_idle_dwell(self, kind: str | None) -> bool:
        current = self.state.current
        return bool(
            kind == "idle"
            and current is not None
            and current.graph is GraphType.IDEL
            and current.animat is AnimatType.B_LOOP
            and current.loop
        )

    def _finish_action(self, kind: str | None) -> None:
        """动作播完：先播 gap 氛围步（待机），到点再掷骰。"""
        gap = float(self.config.get("animation_gap_seconds") or 0.0)
        if gap > 0.0 and kind not in ("click", "drag", "throw", "idle"):
            self._gap_until = time.monotonic() + gap
            self._play_idle()
            return
        self._roll_next()

    def _roll_next(self) -> None:
        self._gap_until = 0.0
        action = self.director.choose()
        if action is None:
            self._play_idle()
            return
        self._play_spec(action.spec, action.kind)

    def _effects_lock_active(self) -> bool:
        """探头会话或击飞彩蛋接管：位置/素材都受限制。"""
        return bool(self.probe_active or self.effects.throw_egg_active)

    @staticmethod
    def _spec_allowed_while_locked(spec: AnimationSpec) -> bool:
        if spec.graph is GraphType.IDEL:
            return True
        return spec.graph is GraphType.MOVE and spec.locate == "in_place"

    def _behavior_weights(self) -> tuple[float, float, float, float]:
        config = self.config
        return normalize_weights(
            config.get("anim_weight_idle"),
            config.get("anim_weight_turn"),
            config.get("anim_weight_act"),
            config.get("anim_weight_move"),
        )

    def _gap_active(self) -> bool:
        return self._gap_until > 0.0 and time.monotonic() < self._gap_until

    def _cancel_animation_gap(self) -> None:
        self._gap_until = 0.0

    def _on_error(self, message: str) -> None:
        logger.warning("clip error: %s", message)

    def _begin_move(self, spec: AnimationSpec, duration: float) -> None:
        self._cancel_move_plan()
        if bool(self.config.get("no_move")) or self.probe_active:
            self._play_idle()
            return
        bounds = self.probe_bounds()
        if bounds is None or self.character is None:
            self._play_idle()
            return
        body_x, _body_y, body_w, _body_h = self.body_rect()
        left, _top, width, _height = bounds
        center_x = body_x + body_w / 2.0
        left_bound = left + MOVE_MARGIN + body_w / 2.0
        right_bound = left + width - MOVE_MARGIN - body_w / 2.0
        direction = choose_move_direction(
            center_x, left_bound, right_bound, MOVE_MIN_PX, rng=self.director.rng
        )
        if direction is None:
            self._play_idle()
            return
        room = (center_x - left_bound) if direction < 0 else (right_bound - center_x)
        if room < MOVE_MIN_PX:
            self._play_idle()
            return
        distance = self.director.rng.randint(MOVE_MIN_PX, min(MOVE_MAX_PX, int(room)))
        stride_px = stride_for(spec, self.character.move_strides) * self.state.scale
        loops, distance_px, move_duration = quantize_move(
            distance, stride_px, room, max(0.001, float(duration or 0.0))
        )
        if loops <= 0 or distance_px <= 0.0 or move_duration <= 0.0:
            self._play_idle()
            return

        # 朝向先于首帧：否则第一帧仍按旧朝向镜像，看起来和位移相反。
        self.state.facing = "right" if direction > 0 else "left"
        self._pending_flip = False
        self._on_frame(0)

        clip = self._clip
        curve = (self.character.move_curves or {}).get(spec.name)
        frames_per_loop = len(curve) if curve else max(1, int(clip.frame_count if clip is not None else 1))
        start_x = float(self.x())
        start_y = float(self.y())
        target_x = start_x + direction * distance_px
        target_y = start_y
        target_x = float(self._clamp_position(int(round(target_x)), int(round(target_y)))[0])
        self._move_plan = {
            "spec": spec.name,
            "start_x": start_x,
            "start_y": start_y,
            "target_x": target_x,
            "target_y": target_y,
            "loops": loops,
            "frames_per_loop": frames_per_loop,
            "total_frames": frames_per_loop * loops,
            "curve": curve,
        }
        self._move_loop = 0
        self._move_last_frame = -1
        self._move_timer.start()

    def _tick_move(self) -> None:
        if self._move_plan is None or self._clip is None or not self.isVisible():
            self._move_timer.stop()

    def _cancel_move_plan(self) -> None:
        self._move_timer.stop()
        self._move_plan = None
        self._move_loop = 0
        self._move_last_frame = -1

    def shift_move_plan(self, dx: float, dy: float) -> None:
        """碰撞分离把宠物推开后，把移动计划整体平移，继续走而不是被拉回原位。"""
        plan = self._move_plan
        if plan is None:
            return
        if not dx and not dy:
            return
        plan["start_x"] = float(plan.get("start_x") or 0.0) + dx
        plan["start_y"] = float(plan.get("start_y") or 0.0) + dy
        plan["target_x"] = float(plan.get("target_x") or 0.0) + dx
        plan["target_y"] = float(plan.get("target_y") or 0.0) + dy

    def abort_move_plan(self) -> None:
        """撞上探头宠物等「不能再往前走」的场合：清计划并回待机。"""
        self._cancel_move_plan()
        if self._action_kind == KIND_MOVE:
            self._play_idle()

    def _advance_move_from_frame(self) -> None:
        plan = self._move_plan
        clip = self._clip
        if plan is None or clip is None:
            return
        frame = clip.current_frame_number()
        per_loop = max(1, int(plan.get("frames_per_loop") or 1))
        if frame < self._move_last_frame:
            self._move_loop += 1
        self._move_last_frame = frame
        if self._move_loop >= int(plan.get("loops") or 1):
            self._finish_move()
            return
        frames_elapsed = self._move_loop * per_loop + frame
        x, y = move_position_at_frame(plan, frames_elapsed)
        x, y = self._clamp_position(int(round(x)), int(round(y)))
        self.move(x, y)

    def _finish_move(self) -> None:
        plan = self._move_plan
        if plan is None:
            return
        x, y = self._clamp_position(
            int(round(plan.get("target_x") or self.x())),
            int(round(plan.get("target_y") or self.y())),
        )
        self.move(x, y)
        self._cancel_move_plan()
        self._edge_probe.maybe_enter()

    def _clamp_position(self, x: int, y: int) -> tuple[int, int]:
        if self._layout is None:
            return x, y
        width, height = self.width(), self.height()
        if bool(self.config.get("multi_screen")):
            return clamp_to_screens(
                x, y, width, height, self._layout.rects(), self._body_local
            )
        name = self.config.get("screen_name")
        screen = self._layout.by_name(name) if name else None
        if screen is None:
            screen = self._layout.by_name(self._layout.primary)
        if screen is None and self._layout.screens:
            # 某些平台/离屏后端的屏幕名为空串，by_name 永远命中不到；退回第一块屏。
            screen = screen_mod.screen_for_rect(
                (x, y, width, height), self._layout
            ) or self._layout.screens[0]
        if screen is None:
            return x, y
        return clamp_to_screen(x, y, screen.rect, self._body_local)

    def _restore_geometry(self, *, persist: bool = True) -> None:
        self._layout = screen_mod.snapshot_from_qt()
        saved = (self.config.get("positions") or {}).get(self.character_id) or {}
        state = ScreenState(
            screen_name=saved.get("screen_name") or self.config.get("screen_name"),
            rx=saved.get("rx") if saved.get("rx") is not None else self.config.get("rx"),
            ry=saved.get("ry") if saved.get("ry") is not None else self.config.get("ry"),
            body_rx=saved.get("body_rx")
            if saved.get("body_rx") is not None
            else self.config.get("body_rx"),
            body_ry=saved.get("body_ry")
            if saved.get("body_ry") is not None
            else self.config.get("body_ry"),
            pos_x=saved.get("pos_x") if saved.get("pos_x") is not None else self.config.get("pos_x"),
            pos_y=saved.get("pos_y") if saved.get("pos_y") is not None else self.config.get("pos_y"),
        )
        x, y, name = screen_mod.restore_position(
            state,
            self._layout,
            self.width(),
            self.height(),
            body_local=self._body_local,
        )
        self.move(x, y)
        self._remember_geometry(name, persist=persist)

    def _remember_geometry(self, screen_name: str | None = None, *, persist: bool = True) -> None:
        if self._layout is None:
            return
        self._layout = screen_mod.snapshot_from_qt()
        name = screen_name or self.config.get("screen_name")
        screen = self._layout.by_name(name) if name else None
        if screen is None:
            screen = screen_mod.screen_for_rect(self.body_rect(), self._layout)
        if screen is None:
            return
        rx, ry = screen_mod.position_ratio(
            self.x(), self.y(), self.width(), self.height(), screen
        )
        body_rx, body_ry = body_position_ratio(
            self.x(),
            self.y(),
            self.width(),
            self.height(),
            screen.rect,
            self._body_local,
        )
        entry = {
            "screen_name": screen.name,
            "rx": rx,
            "ry": ry,
            "body_rx": body_rx,
            "body_ry": body_ry,
            "pos_x": self.x(),
            "pos_y": self.y(),
        }
        positions = dict(self.config.get("positions") or {})
        if self.character_id:
            positions[self.character_id] = dict(entry)
        self.config.data.update(entry)
        self.config.data["positions"] = positions
        if persist:
            self.config.save()

    def handle_screens_changed(self) -> None:
        self._edge_probe.cancel("screens", restore=True)
        if self._layout is None:
            return
        current = screen_mod.snapshot_from_qt()
        state = ScreenState(
            screen_name=self.config.get("screen_name"),
            rx=self.config.get("rx"),
            ry=self.config.get("ry"),
            body_rx=self.config.get("body_rx"),
            body_ry=self.config.get("body_ry"),
            pos_x=self.x(),
            pos_y=self.y(),
        )
        migrated = screen_mod.migrate_layout(
            self._layout,
            current,
            state,
            self.width(),
            self.height(),
            body_local=self._body_local,
        )
        self._layout = current
        if migrated is not None:
            x, y, name = migrated
            self.move(x, y)
            self._remember_geometry(name)
            self.say("显示器布局改变了，我把位置重新放到可见区域了。")
        else:
            x, y = self._clamp_position(self.x(), self.y())
            self.move(x, y)
            self._remember_geometry()

    def set_scale(self, scale: float, *, persist: bool = True) -> None:
        self._edge_probe.cancel("scale", restore=True)
        self._cancel_move_plan()
        self.slingshot.cancel()
        self.effects.reset()
        center = self.frameGeometry().center()
        self.state.set_scale(scale)
        self._update_body_local()
        width, height = content_size(self.state.scale)
        self.setFixedSize(width, height)
        self.move(center.x() - width // 2, center.y() - height // 2)
        x, y = self._clamp_position(self.x(), self.y())
        self.move(x, y)
        self.config.set("scale", self.state.scale)
        if persist:
            self.config.save()
        self._remember_geometry(persist=persist)
        self._on_frame(0)
        if self.bubble.isVisible():
            self.bubble.reposition(self.bubble_anchor_rect())

    def set_click_through(self, value: bool, *, persist: bool = True) -> None:
        self.click_through = bool(value)
        self.config.set("click_through", self.click_through)
        if persist:
            self.config.save()
        self._apply_click_through()

    def toggle_click_through(self) -> None:
        self.set_click_through(not self.click_through)

    def _apply_click_through(self) -> None:
        if self.click_through:
            if self._input_controller is not None:
                self._input_controller.stop()
                self._input_controller = None
            apply_click_through(self, True)
        else:
            apply_click_through(self, False)
            if self._input_controller is None:
                self._input_controller = PerPixelInputController(self, self.is_transparent_at)

    def set_always_on_top(self, value: bool, *, persist: bool = True) -> None:
        self.always_on_top = bool(value)
        self.config.set("always_on_top", self.always_on_top)
        if persist:
            self.config.save()
        self._apply_flags()

    def toggle_always_on_top(self) -> None:
        self.set_always_on_top(not self.always_on_top)

    def set_stream_capture_mode(self, value: bool, *, persist: bool = True) -> None:
        """直播捕获兼容：切换成普通顶层窗口，气泡同步跟随。"""
        self.stream_capture_mode = bool(value)
        self.config.set("stream_capture_mode", self.stream_capture_mode)
        if persist:
            self.config.save()
        self._apply_flags()
        if self.stream_capture_mode:
            apply_stream_window(int(self.winId()))
        else:
            apply_tool_window(int(self.winId()))
        self.bubble.set_stream_mode(self.stream_capture_mode)
        if self.isVisible():
            self.show()

    def toggle_hidden(self) -> None:
        self.set_visible(not self.isVisible())

    def set_visible(self, visible: bool) -> None:
        if bool(visible) == self.isVisible():
            return
        if not visible:
            self._edge_probe.pause()
            self._stop_clip()
            self.bubble.hide()
            self.hide()
            return
        self.show()
        self._edge_probe.resume()
        self.raise_()
        if self._action_kind is not None and self._clip is not None:
            self._clip.start()
        else:
            self._play_idle()

    def _unrotated_point(self, local: QPoint) -> QPoint:
        angle = self._probe_angle + self.effects.effect_angle()
        if abs(angle) < 1e-6:
            return local
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radians = math.radians(-angle)
        dx = local.x() - cx
        dy = local.y() - cy
        return QPoint(
            int(round(cx + dx * math.cos(radians) - dy * math.sin(radians))),
            int(round(cy + dx * math.sin(radians) + dy * math.cos(radians))),
        )

    def _unsquash_point(self, local: QPoint) -> QPoint | None:
        if not self.effects.squash_active:
            return local
        x, y, width, height = self.effects.squash_rect()
        if width <= 0 or height <= 0:
            return None
        if not (x <= local.x() < x + width and y <= local.y() < y + height):
            return None
        return QPoint(
            int((local.x() - x) * self.width() / width),
            int((local.y() - y) * self.height() / height),
        )

    def is_transparent_at(self, local: QPoint) -> bool:
        image = self._image
        if image is None or image.isNull():
            return True
        if self.width() <= 0 or self.height() <= 0:
            return True
        unsquashed = self._unsquash_point(local)
        if unsquashed is None:
            return True
        local = self._unrotated_point(unsquashed)
        if not (0 <= local.x() < self.width() and 0 <= local.y() < self.height()):
            return True
        ix = int(local.x() * image.width() / self.width())
        iy = int(local.y() * image.height() / self.height())
        if not (0 <= ix < image.width() and 0 <= iy < image.height()):
            return True
        return image.pixelColor(ix, iy).alpha() < 8

    def paintEvent(self, _event) -> None:
        if self._pixmap is None:
            return
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        angle = self._probe_angle + self.effects.effect_angle()
        if abs(angle) >= 1e-6:
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.translate(center)
            painter.rotate(angle)
            painter.translate(-center)
        if self.effects.squash_active:
            x, y, width, height = self.effects.squash_rect()
            painter.drawPixmap(QRect(x, y, width, height), self._pixmap)
        else:
            painter.drawPixmap(0, 0, self._pixmap)
        self.slingshot.paint(painter)
        painter.end()

    def mousePressEvent(self, event) -> None:
        self._last_cursor_local = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            self._click_sound_pair.cancel(self._click_sound_token)
            self._click_sound_token = None
            if self.slingshot.maybe_enter(event.position(), event.position()):
                self._suppress_context_menu = True
                self._press_global = None
                self._press_pos = None
                event.accept()
                return
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # 左键（弹弓发射/普通点击）之后紧跟的右键不再是「进瞄准那一下」。
            self._suppress_context_menu = False
            self._press_global = event.globalPosition().toPoint()
            self._press_pos = self.pos()
            self.dragging = False
            self._click_sound_pair.cancel(self._click_sound_token)
            self._click_sound_token = (
                self._click_sound_pair.begin()
                if bool(self.config.get("click_sound"))
                else None
            )

    def mouseMoveEvent(self, event) -> None:
        self._last_cursor_local = event.position()
        if self.slingshot.aiming:
            self.slingshot.update(event.position())
            return
        if self._press_global is None or self._press_pos is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self.dragging and delta.manhattanLength() < DRAG_THRESHOLD:
            return
        if not self.dragging:
            if bool(self.config.get("lock_position")):
                return
            if bool(self.config.get("shift_drag")) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                return
            self.dragging = True
            self.state.dragging = True
            self._probe_drag_throw = self._edge_probe.on_drag_started()
            self._cancel_animation_gap()
            self._cancel_move_plan()
            self.motion.begin_drag(self.x(), self.y())
            spec = self.catalog.find_for(GraphType.RAISED_STATIC, AnimatType.SINGLE)
            if spec is not None:
                self._play_spec(spec, "drag")
        x, y = self._clamp_position(
            self._press_pos.x() + delta.x(), self._press_pos.y() + delta.y()
        )
        self.motion.drag_to(x, y)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        probe_throw = self._probe_drag_throw
        self._probe_drag_throw = False
        if self.slingshot.aiming:
            launched = self.slingshot.launch()
            self.dragging = False
            self.state.dragging = False
            self._press_global = None
            self._press_pos = None
            self._remember_geometry()
            self._edge_probe.on_release(True)
            self._click_sound_pair.cancel(self._click_sound_token)
            self._click_sound_token = None
            if launched:
                if probe_throw:
                    self.effects.arm_throw_egg()
                self._play_throw_animation()
            else:
                self._play_idle()
            return
        dragged = self.dragging
        self.dragging = False
        self.state.dragging = False
        self._press_global = None
        self._press_pos = None
        if dragged:
            self._click_sound_pair.cancel(self._click_sound_token)
            self._click_sound_token = None
            self.motion.release()
            if self.motion.thrown:
                if probe_throw:
                    # 从探头姿态拖出去甩飞：同样开启头部跟随速度的旋转。
                    self.effects.arm_throw_egg()
            else:
                self._play_idle()
            self._remember_geometry()
            self._edge_probe.on_release(True)
        elif self._edge_probe.on_clicked():
            self._click_sound_pair.cancel(self._click_sound_token)
            self._click_sound_token = None
            return
        else:
            played = self._click_sound_pair.release(
                self._click_sound_token, self._click_sound_candidates()
            )
            self._click_sound_token = None
            self._on_click(sound_already_played=played)

    def _play_throw_animation(self) -> None:
        spec = self.catalog.find_for(GraphType.RAISED_DYNAMIC, AnimatType.B_LOOP)
        if spec is None:
            spec = self.catalog.find_for(GraphType.RAISED_DYNAMIC, AnimatType.SINGLE)
        if spec is None:
            # 主分支回退到 drag 悬空素材；没有才回 idle。
            spec = self.catalog.find_for(GraphType.RAISED_STATIC, AnimatType.SINGLE)
        if spec is not None:
            self._play_spec(spec, "throw" if spec.graph is GraphType.RAISED_DYNAMIC else "drag")
        else:
            self._play_idle()

    def _on_thrown(self) -> None:
        """进入抛掷接管态：停 gap/移动计划，绑定飞行（或拖拽）动画。"""
        self._cancel_animation_gap()
        self._cancel_move_plan()
        self._play_throw_animation()

    def _on_click(self, *, sound_already_played: bool = False) -> None:
        if self.motion.thrown or self.effects.throw_egg_active:
            # 主分支 on_sprite_clicked：非 normal 状态不消费点击。飞行中换素材
            # 会与 16ms 位移叠加成「两个位置的桌宠在闪」。
            return
        self._cancel_animation_gap()
        self._cancel_move_plan()
        if bool(self.config.get("golden_spin_on_click")):
            if bool(self.config.get("golden_spin_direct")):
                self.effects.start_spin(direct=True)
                self._notify_click()
                return
            self.effects.arm_spin_after_click()
        spec = self.catalog.find_for(GraphType.TOUCH_BODY, AnimatType.SINGLE)
        if spec is not None:
            self._play_spec(spec, "click")
        # 点击素材可能同步解码；Q 弹在切换之后再起表，保证 220ms 真的可见。
        self.effects.start_squash(int(self.config.get("click_squash_ms") or 220))
        if bool(self.config.get("click_sound")) and not sound_already_played:
            QTimer.singleShot(0, self._play_click_sound)
        self._notify_click()

    def _play_click_sound(self) -> None:
        candidates = self._click_sound_candidates()
        chosen = choose_click_sound(candidates, rng=self.director.rng)
        if chosen is None:
            return
        self.sound.play(chosen)

    def show_easter_egg(self) -> bool:
        """彩蛋入口：默认用气泡显示图片，``easter_egg_display="window"`` 用弹窗。"""
        mode = str(self.config.get("easter_egg_display") or "bubble").strip().lower()
        if mode == "window":
            if self.easter.show():
                return True
            return self._show_easter_egg_in_bubble()
        if self._show_easter_egg_in_bubble():
            return True
        # 气泡失败（关掉了/目录为空/图片坏了）时交给弹窗路径报告原因。
        return bool(self.easter.show())

    def _show_easter_egg_in_bubble(self) -> bool:
        if not bool(self.config.get("easter_egg_enabled", True)):
            return False
        images = self.easter.images()
        if not images:
            return False
        image_path = self.easter.selected_image(images)
        if image_path is None:
            return False
        title = str(self.config.get("easter_egg_title") or DEFAULT_EASTER_EGG_TITLE)
        # 气泡已有点击关闭行为；hint 只用于独立彩蛋窗口，保持旧气泡文案契约。
        caption = title
        return self.show_image(
            image_path,
            caption,
            image_scale=self._image_scale_factor("easter_egg_image_scale"),
        )

    def _notify_click(self) -> None:
        for listener in tuple(self._click_listeners):
            try:
                listener(self)
            except Exception:
                logger.debug("click listener failed", exc_info=True)

    def add_click_listener(self, listener) -> None:
        if listener not in self._click_listeners:
            self._click_listeners.append(listener)

    def remove_click_listener(self, listener) -> None:
        if listener in self._click_listeners:
            self._click_listeners.remove(listener)

    def add_drop_listener(self, listener) -> None:
        if listener not in self._drop_listeners:
            self._drop_listeners.append(listener)

    def remove_drop_listener(self, listener) -> None:
        if listener in self._drop_listeners:
            self._drop_listeners.remove(listener)

    def _notify_drop(self, paths) -> None:
        for listener in tuple(self._drop_listeners):
            try:
                listener(paths)
            except Exception:
                logger.debug("drop listener failed", exc_info=True)

    def _on_motion_bounce(self) -> None:
        self.effects.start_squash(int(self.config.get("click_squash_ms") or 220))
        if bool(self.config.get("collision_sound")):
            self._play_click_sound()

    def _on_motion_stopped(self) -> None:
        if not self.dragging:
            self._play_idle()
            self._edge_probe.maybe_enter()

    def contextMenuEvent(self, event) -> None:
        if (
            self.slingshot.suppresses_context_menu()
            or self._suppress_context_menu
        ):
            if self.slingshot.aiming:
                # 保留「瞄准时右键取消」的手感，但不再弹出菜单。
                self.slingshot.cancel()
            self._suppress_context_menu = False
            event.accept()
            return
        menu = self.host.build_menu(self)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.slingshot.aiming:
            self.slingshot.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        self.feeding.handle_drag_enter(event)

    def dragMoveEvent(self, event) -> None:
        if self.feeding.accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not self.feeding.accepts(event):
            event.ignore()
            return
        paths = self.feeding._paths(event.mimeData())
        self._notify_drop(paths)
        self.feeding.handle_drop(event)

    def wheelEvent(self, event) -> None:
        steps = list(SCALE_STEPS)
        current = min(steps, key=lambda item: abs(item - self.state.scale))
        index = steps.index(current)
        index += 1 if event.angleDelta().y() > 0 else -1
        index = max(0, min(len(steps) - 1, index))
        self.set_scale(steps[index])
        event.accept()

    def say(self, text: str, duration_ms: int = 4000, *, subtitle: str = "") -> bool:
        if not self.isVisible():
            # 隐藏的桌宠不该继续冒泡；隐藏时 set_visible(False) 也会收起气泡。
            return False
        # 设置页只写配置，这里在每次新气泡前同步一次字号（未变时是空操作）。
        self.bubble.set_text_scale(self._text_scale_factor())
        self.bubble.show_text(
            text, self.bubble_anchor_rect(), duration_ms, subtitle=subtitle
        )
        return self.bubble.isVisible()

    def _on_bubble_clicked(self) -> None:
        """点气泡 = 打开快速对话（主分支同一条入口）。"""
        opener = getattr(self.host, "open_quick_chat", None)
        if callable(opener):
            opener(self.slot)

    def _text_scale_factor(self) -> float:
        try:
            percent = float(self.config.get("bubble_text_scale") or 100)
        except (TypeError, ValueError):
            percent = 100.0
        return percent / 100.0

    def set_text_scale(self, percent: int, *, persist: bool = True) -> None:
        """设置气泡文字缩放（百分比 50–300），已显示的气泡立即重排。"""
        try:
            value = int(round(float(percent)))
        except (TypeError, ValueError, OverflowError):
            value = 100
        value = max(50, min(300, value))
        self.config.set("bubble_text_scale", value)
        if persist:
            self.config.save()
        self.bubble.set_text_scale(value / 100.0)

    def _image_scale_factor(self, key: str) -> float:
        try:
            percent = float(self.config.get(key) or 100)
        except (TypeError, ValueError):
            percent = 100.0
        return percent / 100.0

    def show_image(
        self,
        path,
        caption: str = "",
        duration_ms: int = 4000,
        image_scale: float | None = None,
    ) -> bool:
        """在气泡里显示一张图；``image_scale`` 缺省用彩蛋图片大小设置。"""
        if not self.isVisible():
            return False
        if image_scale is None:
            image_scale = self._image_scale_factor("easter_egg_image_scale")
        self.bubble.set_text_scale(self._text_scale_factor())
        try:
            shown = self.bubble.show_image(
                path,
                self.bubble_anchor_rect(),
                caption,
                duration_ms,
                image_scale=image_scale,
                dpr=screen_dpr(self),
            )
        except (OSError, ValueError):
            logger.debug("bubble image failed", exc_info=True)
            return False
        if shown and not self.bubble.isVisible():
            logger.warning("bubble image shown but window is not visible: %s", path)
            return False
        return bool(shown)

    def bubble_anchor_rect(self) -> QRect:
        """气泡锚点：角色头部框（回退身体框/整窗），同主分支的可见轮廓锚点。"""
        x, y, width, height = self._head_local or self._body_local
        return QRect(self.x() + x, self.y() + y, width, height)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_bubble_follow()
        self.pet_moved.emit()

    def _schedule_bubble_follow(self) -> None:
        """同一帧内多次 move 只排一次重排（拖拽/抛掷每 16ms 都在动）。"""
        if self._bubble_follow_pending:
            return
        self._bubble_follow_pending = True
        QTimer.singleShot(0, self._follow_bubble)

    def _follow_bubble(self) -> None:
        self._bubble_follow_pending = False
        try:
            if not self.bubble.isVisible():
                return
            self.bubble.reposition(self.bubble_anchor_rect())
        except RuntimeError:
            # 窗口已销毁（关闭/退出）时 singleShot 仍可能落地。
            return

    def play_animation(self, name: str, *, loop: bool = False) -> bool:
        self._cancel_animation_gap()
        spec = (
            self.catalog.find(name, AnimatType.SINGLE)
            or self.catalog.find(name, AnimatType.B_LOOP)
            or self.catalog.find(name, AnimatType.A_START)
        )
        if spec is None:
            return False
        self._play_spec(spec, self._kind_for_spec(spec))
        self._loop_active = bool(loop)
        return True

    def release_loop(self) -> bool:
        """解除 ``play_animation(loop=True)``；当前这圈播完就回行为链。"""
        was = bool(getattr(self, "_loop_active", False))
        self._loop_active = False
        return was

    @staticmethod
    def _kind_for_spec(spec: AnimationSpec) -> str:
        if spec.graph is GraphType.IDEL:
            return "idle"
        if spec.graph is GraphType.MOVE:
            return "turn" if spec.locate == "in_place" else "move"
        if spec.graph is GraphType.TOUCH_BODY:
            return "click"
        return "act"

    def play_event(self, group: str, variant: str | int | None = None) -> bool:
        """播放 ``events/<group>/`` 下的语义事件动画（余额档位等）。

        事件动画不进随机动作池；``variant`` 支持名字（可带 ``folder/`` 前缀）
        或按名字排序的索引，留空随机。
        """
        specs = list(self.catalog.specs_for_event(group))
        if not specs:
            return False
        spec: AnimationSpec | None = None
        if isinstance(variant, str) and variant:
            spec = next((item for item in specs if item.name == variant), None)
            if spec is None:
                tail = variant.rsplit("/", 1)[-1]
                spec = next(
                    (
                        item
                        for item in specs
                        if item.name == tail or item.name.endswith(variant)
                    ),
                    None,
                )
        elif isinstance(variant, int) and not isinstance(variant, bool):
            ordered = sorted(specs, key=lambda item: item.name)
            if 0 <= variant < len(ordered):
                spec = ordered[variant]
        if spec is None:
            spec = self.director.rng.choice(specs)
        self._cancel_animation_gap()
        self._play_spec(spec, "act")
        return True

    def _corner_position(self, screen) -> tuple[int, int]:
        bx, by, bw, bh = self._body_local
        if (bw, bh) == (self.width(), self.height()):
            x = screen.x + screen.width - self.width() - CORNER_MARGIN
            y = screen.y + screen.height - self.height() - CORNER_MARGIN
        else:
            x = screen.x + screen.width - CORNER_MARGIN - bx - bw
            y = screen.y + screen.height - by - bh
        return clamp_to_screen(x, y, screen.rect, self._body_local)

    def move_to_primary(self) -> None:
        self._layout = screen_mod.snapshot_from_qt()
        primary = self._layout.by_name(self._layout.primary)
        if primary is None:
            return
        x, y = self._corner_position(primary)
        self.move(x, y)
        self._remember_geometry(primary.name)

    def return_corner(self) -> None:
        self._layout = screen_mod.snapshot_from_qt()
        name = self.config.get("screen_name")
        screen = self._layout.by_name(name) if name else None
        if screen is None:
            screen = self._layout.by_name(self._layout.primary)
        if screen is None:
            return
        x, y = self._corner_position(screen)
        self.move(x, y)
        self._remember_geometry(screen.name)

    def reset_position(self) -> None:
        self.move_to_primary()
        self.set_scale(float(self.config.get("scale") or 0.72))

    def set_config_flag(self, key: str, value, *, persist: bool = True) -> None:
        self.config.set(key, value)
        if persist:
            self.config.save()

    def toggle_config_flag(self, key: str) -> None:
        self.set_config_flag(key, not bool(self.config.get(key)))

    def set_playback_speed(self, speed: float, *, persist: bool = True) -> None:
        self.set_config_flag("playback_speed", max(0.5, min(2.0, float(speed))), persist=persist)
        if self._clip is not None:
            self._clip.set_playback_speed(float(self.config.get("playback_speed") or 1.0))

    def trigger_golden_spin(self) -> None:
        self.effects.start_spin(direct=True)

    def spawn_pet(self) -> None:
        if self.host.pets is not None:
            self.host.pets.spawn()

    def clear_spawned_pets(self) -> None:
        if self.host.pets is not None:
            self.host.pets.close_secondary()

    def open_settings(self, initial_page: str | None = None) -> None:
        self.host.open_settings(initial_page, window=self)

    def toggle_dynamic_island(self) -> None:
        toggler = getattr(self.host, "toggle_dynamic_island", None)
        if callable(toggler):
            toggler()

    def reload_mods(self) -> None:
        self.host.reload_mods()

    def open_data_dir(self) -> None:
        self.host.open_data_dir()

    def quit_app(self) -> None:
        self.host.quit_app()

    def run_ai_command(self, command_id: str) -> bool:
        """菜单/热键共用的 AI 入口；扩展缺失时由 core 负责提示。"""
        runner = getattr(self.host, "run_feature_command", None)
        if callable(runner):
            return bool(runner("ai.chat", command_id, slot=self.slot))
        self.say("AI 扩展未安装：可在「扩展管理 → 插件市场」安装")
        return False

    def quit_from_menu(self) -> None:
        """右键「退出」：主宠退整个应用，子宠只收回自己。"""
        if self.slot == 0:
            self.host.quit_app()
            return
        manager = getattr(self.host, "pets", None)
        if manager is None:
            logger.debug("no pet manager for slot %s; closing window only", self.slot)
            self.close()
            return
        if not manager.close_slot(self.slot):
            return
        primary = getattr(manager, "primary", None)
        if primary is not None and primary is not self:
            primary.say("已收回这只子宠。")
        tray = getattr(self.host, "tray", None)
        refresh = getattr(tray, "refresh", None)
        if callable(refresh):
            QTimer.singleShot(0, refresh)

    def closeEvent(self, event) -> None:
        self._click_sound_pair.cancel_all()
        self._click_sound_token = None
        self.sound.stop_all()
        self._stop_clip()
        self.library.close_all()
        if self._input_controller is not None:
            self._input_controller.stop()
        super().closeEvent(event)

    def reload_characters(self, character: CharacterSpec) -> None:
        self._activate(character)
        self._restore_geometry()
        self.show()
        self._play_idle()

    def shutdown(self) -> None:
        self._click_sound_pair.cancel_all()
        self._click_sound_token = None
        self.sound.stop_all()
        self._edge_probe.shutdown()
        self.motion.shutdown()
        self.effects.shutdown()
        self.easter.close_all()
        self._cancel_animation_gap()
        self._move_timer.stop()
        self._stop_clip()
        self.library.close_all()
        if self._input_controller is not None:
            self._input_controller.stop()
        self.bubble.close()
