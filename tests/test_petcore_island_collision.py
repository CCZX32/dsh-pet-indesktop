"""灵动岛 × 桌宠碰撞（`petcore/ui/island_collision.py`）的 offscreen 测试。

覆盖三层：
1. 协调器（副本地推 / 真撞冲量 / 三档反馈节流 / 闸门）；
2. 岛速采样（配对上报、松手闸、动画不采样、瞬移守卫）；
3. 三个真实挂接点（`PetWindow._clamp_position`、`MotionController._tick_throw`）。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.engine import island_field as field
from petcore.ui import island as island_ui
from petcore.ui.island_collision import IslandField

app = QApplication.instance() or QApplication([])

ISLAND_RECT = (400, 100, 300, 44)  # 胶囊：轴 [422, 678]、轴高 122、半径 22


# ---------------------------------------------------------------- 替身
class _FakeMotion:
    def __init__(self) -> None:
        self.mode = "normal"
        self._v = (0.0, 0.0)
        self.set_calls: list[tuple[float, float]] = []

    @property
    def thrown(self) -> bool:
        return self.mode == "thrown"

    def velocity(self):
        return self._v

    def set_velocity(self, vx, vy) -> None:
        self.set_calls.append((vx, vy))
        self._v = (vx, vy)
        self.mode = "thrown"


class _FakeEffects:
    def __init__(self) -> None:
        self.squashes = 0

    def start_squash(self, *_args, **_kwargs) -> None:
        self.squashes += 1


class _FakePet:
    """只要碰撞侧用到的那几个成员；``_clamp_position`` 由测试接到协调器上。"""

    def __init__(self, x: float, y: float, *, body=(0, 0, 80, 80), visible: bool = True):
        self._x = float(x)
        self._y = float(y)
        self.body = body
        self.visible = visible
        self.probe_active = False
        self.dragging = False
        self.motion = _FakeMotion()
        self.effects = _FakeEffects()
        self.config = {"click_squash_ms": 220, "collision_sound": True, "throw_strength": "standard"}
        self.sounds = 0
        self._move_plan = None
        self.aborted = 0
        self.moves = 0
        self.field = None

    def isVisible(self) -> bool:
        return self.visible

    def body_local_rect(self):
        return self.body

    def x(self) -> int:
        return int(round(self._x))

    def y(self) -> int:
        return int(round(self._y))

    def move(self, x, y) -> None:
        self._x = float(x)
        self._y = float(y)
        self.moves += 1

    def _play_click_sound(self) -> None:
        self.sounds += 1

    def island_hit_feedback(self) -> None:
        """与真窗口同口径：挤压 + 碰撞音效（节流在碰撞层）。"""
        self.effects.start_squash(self.config.get("click_squash_ms") or 220)
        if self.config.get("collision_sound"):
            self._play_click_sound()

    def abort_move_plan(self) -> None:
        self.aborted += 1
        self._move_plan = None

    def _clamp_position(self, x, y):
        if self.field is None:
            return int(x), int(y)
        return self.field.clamp(self, int(x), int(y))

    def body_rect(self):
        bx, by, bw, bh = self.body
        return self._x + bx, self._y + by, bw, bh


# ---------------------------------------------------------------- 夹具
@pytest.fixture()
def make_island(tmp_path):
    created = []

    def factory(values=None, *, size=(ISLAND_RECT[2], ISLAND_RECT[3])):
        config = Config(
            tmp_path,
            {"island_enabled": True, "island_metrics": [], **(values or {})},
        )
        widget = island_ui.DynamicIsland(config, character_name="深深")
        widget.show()
        # 1Hz 心跳会按内容重算宽度、showEvent 会重新锁尺寸：测试要固定几何，
        # 于是停掉心跳再钉一次（碰撞侧只认 collision_rect()）。
        widget._clock.stop()
        widget.setFixedSize(*size)
        widget.move(ISLAND_RECT[0], ISLAND_RECT[1])
        created.append((widget, config))
        return widget, config

    yield factory
    for widget, _config in created:
        widget.stop()
        widget.sys_monitor.wait_stopped(5)
        widget.net_monitor.wait_stopped(5)
        widget.hide()
        widget.close()
        widget.deleteLater()


@pytest.fixture()
def clock():
    ticks = [100.0]

    def now() -> float:
        return ticks[0]

    def advance(seconds: float) -> None:
        ticks[0] += seconds

    now.advance = advance  # type: ignore[attr-defined]
    return now


def _field(island, config, pets, clock):
    return IslandField(island, config, lambda: pets, clock=clock)


def _inside(pet: _FakePet, stadium: field.Stadium) -> bool:
    return field.push_out(pet.body_rect(), stadium) is not None


# ---------------------------------------------------------------- 墙的闸门
def test_clamp_is_a_noop_when_the_island_is_hidden(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    field_ = _field(island, config, [pet], clock)
    pet.field = field_
    island.hide()
    assert field_.clamp(pet, 500, 100) == (500, 100)


def test_clamp_is_a_noop_when_collision_is_disabled(make_island, clock):
    island, config = make_island({"island_collision": False})
    pet = _FakePet(500, 100)
    field_ = _field(island, config, [pet], clock)
    assert field_.stadium() is None
    assert field_.clamp(pet, 500, 100) == (500, 100)


def test_clamp_is_a_noop_in_the_docked_strip_and_during_geometry_animation(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    field_ = _field(island, config, [pet], clock)

    island._docked = True
    island._dock_edge = "top"
    assert island._strip_visible()
    assert field_.clamp(pet, 500, 100) == (500, 100)

    island._docked = False
    island._dock_edge = "none"
    island._geo_to = QRect(400, 100, 300, 44)
    assert field_.clamp(pet, 500, 100) == (500, 100)
    island._geo_to = None
    assert field_.clamp(pet, 500, 100) != (500, 100)


def test_probe_pose_is_exempt(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    pet.probe_active = True
    field_ = _field(island, config, [pet], clock)
    assert field_.clamp(pet, 500, 100) == (500, 100)


def test_invisible_pet_is_not_clamped(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100, visible=False)
    field_ = _field(island, config, [pet], clock)
    assert field_.clamp(pet, 500, 100) == (500, 100)


# ---------------------------------------------------------------- 推出
def test_clamp_pushes_the_body_out_of_the_capsule(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)  # 中心 (540, 140)：压在胶囊下沿里
    field_ = _field(island, config, [pet], clock)
    stadium = field_.stadium()
    assert stadium is not None
    assert _inside(pet, stadium)

    x, y = field_.clamp(pet, 500, 100)
    assert (x, y) != (500, 100)
    pet.move(x, y)
    assert not _inside(pet, stadium)


def test_pushed_position_is_stable(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    field_ = _field(island, config, [pet], clock)
    x, y = field_.clamp(pet, 500, 100)
    pet.move(x, y)
    assert field_.clamp(pet, x, y) == (x, y)


def test_slow_walking_pet_is_pushed_but_not_thrown(make_island, clock):
    """漫游实测步速 4.5–24 px/s：只被挡住 + 收掉移动计划，不许被弹飞。"""
    island, config = make_island()
    pet = _FakePet(500, 60)
    pet._move_plan = {"spec": "walk"}
    field_ = _field(island, config, [pet], clock)
    stadium = field_.stadium()
    assert stadium is not None

    y = 60.0
    for _ in range(20):
        clock.advance(0.016)
        y += 0.2  # 12.5 px/s
        x, new_y = field_.clamp(pet, 500, int(y))
        pet.move(x, new_y)
    assert not pet.motion.thrown
    assert pet.motion.set_calls == []
    assert pet.sounds == 0
    assert pet.aborted >= 1
    assert not _inside(pet, stadium)


def test_fast_pet_is_thrown_with_all_three_feedback_channels(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 40)
    field_ = _field(island, config, [pet], clock)

    x, y = field_.clamp(pet, 500, 40)  # 建立接触基线
    pet.move(x, y)
    clock.advance(0.016)
    x, y = field_.clamp(pet, 500, 48)  # 8px/16ms = 500 px/s 撞进去
    assert pet.motion.thrown
    vx, vy = pet.motion.velocity()
    assert vy < -100.0  # 法线朝上 → 被向上弹开
    assert pet.effects.squashes == 1
    assert pet.sounds == 1
    assert island._squish_v < 0.0  # 岛果冻被顶了一下
    assert pet.moves >= 1


def test_hit_feedback_is_throttled_by_the_cooldown(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 40)
    field_ = _field(island, config, [pet], clock)
    pet.field = field_

    field_.clamp(pet, 500, 40)
    clock.advance(0.016)
    pet.motion.mode = "normal"  # 手动复位，模拟下一次独立接近
    field_.clamp(pet, 500, 48)
    assert pet.sounds == 1
    clock.advance(0.02)  # 冷却内
    pet.motion.mode = "normal"
    field_.clamp(pet, 500, 50)
    assert pet.sounds == 1
    assert pet.effects.squashes == 1


def test_dragged_pet_is_only_pushed(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 40)
    pet.dragging = True
    field_ = _field(island, config, [pet], clock)

    field_.clamp(pet, 500, 40)
    clock.advance(0.016)
    x, y = field_.clamp(pet, 500, 60)
    assert (x, y) != (500, 60)
    assert pet.motion.set_calls == []
    assert pet.sounds == 0


def test_thrown_pet_is_pushed_without_a_second_velocity_write(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    pet.motion.mode = "thrown"
    field_ = _field(island, config, [pet], clock)
    x, y = field_.clamp(pet, 500, 100)
    assert (x, y) != (500, 100)
    assert pet.motion.set_calls == []


# ---------------------------------------------------------------- 抛掷反射
def test_thrown_pet_reflects_off_the_wall(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    # 从上方砸下来：位置压在胶囊里、速度向下（撞上壁后向上反弹）
    resolution = field_.reflect_throw(pet, 500, 30, 0.0, 900.0)
    assert resolution.hit is True
    assert resolution.rested is False
    assert resolution.vy == pytest.approx(-900.0 * field.RESTITUTION)
    assert abs(resolution.vy) < 900.0
    assert (resolution.nx, resolution.ny) == (pytest.approx(0.0), pytest.approx(-1.0))
    pet.move(resolution.px, resolution.py)
    assert not _inside(pet, field_.stadium())


def test_reflect_is_a_noop_outside_the_wall(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    resolution = field_.reflect_throw(pet, 0, 0, 100.0, 0.0)
    assert (resolution.px, resolution.py) == (0, 0)
    assert (resolution.vx, resolution.vy) == (100.0, 0.0)
    assert resolution.hit is False and resolution.rested is False


def test_landing_on_the_island_top_settles_instead_of_bouncing_forever(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    resolution = field_.reflect_throw(pet, 500, 30, 0.0, 60.0)
    assert resolution.hit is True
    assert resolution.rested is True
    assert (resolution.vx, resolution.vy) == (0.0, 0.0)


def test_skimming_the_island_top_does_not_stop_a_fast_horizontal_throw(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    resolution = field_.reflect_throw(pet, 500, 30, 600.0, 60.0)
    assert resolution.rested is False
    assert abs(resolution.vx) > 300.0


# ---------------------------------------------------------------- 岛速采样
def test_island_swept_into_a_resting_pet_throws_it(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 150)  # 中心 (540, 190)：岛下移后被压到
    field_ = _field(island, config, [pet], clock)
    pet.field = field_

    island._dragging = True
    field_.on_geometry_changed()  # 基线
    clock.advance(0.016)
    island.move(ISLAND_RECT[0], ISLAND_RECT[1] + 30)
    field_.on_geometry_changed()

    assert field_.island_velocity()[1] > 0.0  # 向下甩
    assert pet.motion.thrown
    assert pet.motion.velocity()[1] > 0.0  # 法线朝下 → 被向下拍

    island._dragging = False


def test_geometry_animation_frames_do_not_sample_island_speed(make_island, clock):
    """展开/停靠动画峰值上千 px/s：一拍都不许拿来当撞击燃料。"""
    island, config = make_island()
    pet = _FakePet(500, 150)
    field_ = _field(island, config, [pet], clock)
    pet.field = field_

    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0], ISLAND_RECT[1] + 30)
    island._geo_to = QRect(island.geometry())
    field_.on_geometry_changed()
    assert field_.island_velocity() == (0.0, 0.0)
    assert not pet.motion.thrown
    island._geo_to = None


def test_paired_same_rect_reports_keep_the_drag_speed(make_island, clock):
    """一次 mouseMoveEvent 里 move() 与显式上报会喂两遍同一 rect。"""
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)

    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0] + 16, ISLAND_RECT[1])
    field_.on_geometry_changed()
    measured = field_.island_velocity()
    assert measured[0] > 0.0

    clock.advance(0.001)  # 同一帧的第二遍上报
    field_.on_geometry_changed()
    assert field_.island_velocity() == measured
    island._dragging = False


def test_a_stopped_island_zeroes_its_speed(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)

    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0] + 16, ISLAND_RECT[1])
    field_.on_geometry_changed()
    assert field_.island_velocity()[0] > 0.0

    island._dragging = False
    clock.advance(0.05)
    field_.on_geometry_changed()  # 同 rect 的非拖拽上报 = 停了
    assert field_.island_velocity() == (0.0, 0.0)


def test_the_release_sample_never_resurrects_speed(make_island, clock):
    """松手那一拍的位移是夹回/落位：不许算成一次撞击。

    位移取 12px/16ms（750 px/s）：低于超速闸，所以只有「松手闸」能把它清零，
    否则这只静止桌宠会被落位位移拍飞（幽灵撞击）。
    """
    island, config = make_island()
    pet = _FakePet(510, 132)  # 中心 (550, 172)：岛下移 12px 后压在它身上
    field_ = _field(island, config, [pet], clock)
    pet.field = field_

    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island._dragging = False
    island.move(ISLAND_RECT[0], ISLAND_RECT[1] + 12)
    field_.on_geometry_changed()
    assert field_.island_velocity() == (0.0, 0.0)
    assert not pet.motion.thrown


def test_a_long_pause_does_not_resurrect_speed(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(9.0)
    island.move(ISLAND_RECT[0] + 16, ISLAND_RECT[1])
    field_.on_geometry_changed()
    assert field_.island_velocity() == (0.0, 0.0)
    island._dragging = False


def test_a_teleport_is_not_sampled_as_speed(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0] + 3000, ISLAND_RECT[1])
    field_.on_geometry_changed()
    assert field_.island_velocity() == (0.0, 0.0)
    island._dragging = False


def test_overspeed_is_clamped_only_while_dragging(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0] + 40, ISLAND_RECT[1])  # 2500 px/s
    field_.on_geometry_changed()
    vx, _vy = field_.island_velocity()
    assert vx == pytest.approx(field.MAX_ISLAND_SPEED)
    island._dragging = False


def test_reset_clears_velocity_and_contacts(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 100)
    field_ = _field(island, config, [pet], clock)
    pet.field = field_
    island._dragging = True
    field_.on_geometry_changed()
    clock.advance(0.016)
    island.move(ISLAND_RECT[0] + 16, ISLAND_RECT[1])
    field_.on_geometry_changed()
    field_.clamp(pet, 500, 100)
    field_.reset()
    assert field_.island_velocity() == (0.0, 0.0)
    assert field_._contact == {}
    island._dragging = False


# ---------------------------------------------------------------- 无定时器 / 岛动效
def test_the_collision_layer_creates_no_timer(make_island, clock, tmp_path):
    island, config = make_island()
    before = len(island.findChildren(QTimer))
    field_ = IslandField(island, config, lambda: [], clock=clock)
    assert len(island.findChildren(QTimer)) == before
    assert not any(isinstance(value, QTimer) for value in vars(field_).values())


def test_island_bump_stays_clamped_and_settles(make_island):
    island, _config = make_island()
    for _ in range(20):
        island.bump(9.0, 1.0, 1.0)
    assert -island_ui.SQUISH_V_MAX <= island._squish_v <= island_ui.SQUISH_V_MAX
    assert abs(island._kick_x) <= island_ui.KICK_MAX_PX + 1e-6
    assert abs(island._kick_y) <= island_ui.KICK_MAX_PX + 1e-6
    for _ in range(400):
        island._anim_last -= 0.016  # 手工推进 dt：紧循环里真实 dt 会是 0
        island._on_anim_tick()
        if not island._anim_timer.isActive():
            break
    assert not island._anim_timer.isActive()
    assert island._kick_x == 0.0 and island._kick_y == 0.0
    assert island_ui.SQUISH_MIN <= island._squish <= island_ui.SQUISH_MAX


def test_bump_is_ignored_while_expanded_or_in_the_strip(make_island):
    island, _config = make_island()
    island._expanded = True
    island.bump(2.0, 1.0, 0.0)
    assert island._squish_v == 0.0
    island._expanded = False
    island._docked = True
    island._dock_edge = "top"
    island.bump(2.0, 1.0, 0.0)
    assert island._squish_v == 0.0
    island._docked = False
    island._dock_edge = "none"


# ---------------------------------------------------------------- 真实挂接点
class _Host:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = Config(root)
        self.pets = None
        self.island_field = None
        self.characters = lambda: []
        self.character_for = lambda _id: None

    def build_menu(self, parent=None):
        return None

    def open_settings(self, *args, **kwargs):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        return None


def _real_window(tmp_path, host, character):
    from petcore.ui.pet_window import PetWindow

    config = Config(tmp_path, {"character": character.id, "scale": 0.5, "no_move": True})
    window = PetWindow(config, tmp_path, host, slot=0)
    window.start(character)
    window.show()
    return window


def test_real_window_position_exit_is_blocked_by_the_island(make_island, clock, tmp_path):
    from petcore.content.legacy import load_character

    character = load_character("shenshen", frameseq_mode="off")
    assert character is not None
    host = _Host(tmp_path)
    window = _real_window(tmp_path, host, character)
    island, config = make_island()
    field_ = IslandField(island, config, lambda: [window], clock=clock)
    host.island_field = field_
    try:
        bx, by, bw, bh = window.body_local_rect()
        stadium = field_.stadium()
        assert stadium is not None
        # 把窗口摆到胶囊正中：身体框一定压进墙里
        target_x = int(round(stadium.x0 + (stadium.x1 - stadium.x0) / 2 - bw / 2 - bx))
        target_y = int(round(stadium.axis_y - bh / 2 - by))
        x, y = window._clamp_position(target_x, target_y)
        assert (x, y) != (target_x, target_y)
        window.move(x, y)
        assert not _inside_pet(window, stadium)
    finally:
        window.shutdown()
        window.close()


def test_real_window_without_a_field_keeps_the_old_exit(make_island, clock, tmp_path):
    from petcore.content.legacy import load_character

    character = load_character("shenshen", frameseq_mode="off")
    host = _Host(tmp_path)
    window = _real_window(tmp_path, host, character)
    try:
        # 宿主没有 island_field：位置出口与改动前逐像素一致
        assert window._clamp_position(500, 100) == window._clamp_to_screen(500, 100)
    finally:
        window.shutdown()
        window.close()


def test_real_throw_tick_reflects_off_the_island(make_island, clock, tmp_path):
    from petcore.content.legacy import load_character

    character = load_character("shenshen", frameseq_mode="off")
    host = _Host(tmp_path)
    window = _real_window(tmp_path, host, character)
    island, config = make_island()
    field_ = IslandField(island, config, lambda: [window], clock=clock)
    host.island_field = field_
    try:
        bx, by, bw, bh = window.body_local_rect()
        stadium = field_.stadium()
        assert stadium is not None
        # 把桌宠放在胶囊左侧、以 900px/s 向右抛 → 撞上左端半圆应反号
        window.move(
            int(round(stadium.x0 - bw - bx - 80)),
            int(round(stadium.axis_y - bh / 2 - by)),
        )
        window.motion.begin_throw(900.0, 0.0)
        seen_flip = False
        for _ in range(40):
            clock.advance(0.016)
            window.motion._tick_throw(0.016, clock())
            vx, _vy = window.motion.velocity()
            if vx < 0.0:
                seen_flip = True
                break
        assert seen_flip, "抛掷中的桌宠没有在岛墙上反射"
        window.move(int(window.x()), int(window.y()))
        assert not _inside_pet(window, stadium)
    finally:
        window.motion.stop()
        window.shutdown()
        window.close()


def _inside_pet(window, stadium) -> bool:
    bx, by, bw, bh = window.body_local_rect()
    body = (
        float(window.x() + bx),
        float(window.y() + by),
        float(bw),
        float(bh),
    )
    return field.push_out(body, stadium) is not None


# ---------------------------------------------------------------- 复核修复项
def test_settle_false_only_moves_the_body(make_island, clock):
    """发起漫游时会先钳一次 60–240px 外的目标点：那不是"移动"，不许结算。"""
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    x, y = field_.clamp(pet, 500, 100, settle=False)
    assert (x, y) != (500, 100)  # 几何照样钳出
    assert pet.motion.set_calls == []
    assert pet.sounds == 0
    assert field_._contact == {}  # 也不留接触记录（否则下一次真移动会拿到假基线）


def test_a_far_target_clamp_never_throws_a_standing_pet(make_island, clock):
    """桌宠站着不动，只把 240px 外的目标点喂进位置出口：不许变 thrown。"""
    island, config = make_island()
    pet = _FakePet(100, 100)
    field_ = _field(island, config, [pet], clock)
    pet.field = field_
    field_.clamp(pet, 100, 100)  # 建立基线
    clock.advance(0.25)  # 0.25s 后给出 240px 外的目标（≈960px/s 的"假速度"）
    target = (int(round(field_.stadium().x0 + 60)), int(round(field_.stadium().axis_y - 40)))
    x, y = field_.clamp(pet, *target, settle=False)
    assert (x, y) != target  # 目标落在胶囊里 → 几何上被钳出
    assert not pet.motion.thrown
    assert pet.motion.set_calls == []


def test_geometry_animation_keeps_the_feedback_throttle(make_island, clock):
    """动画每帧都会 reset：只许清速度/接触，不许把 0.25s 单闸清掉。"""
    island, config = make_island()
    pet = _FakePet(500, 40)
    field_ = _field(island, config, [pet], clock)
    field_.clamp(pet, 500, 40)
    clock.advance(0.016)
    field_.clamp(pet, 500, 48)
    assert pet.sounds == 1
    island._geo_to = QRect(island.geometry())
    field_.on_geometry_changed()  # 动画帧：reset_velocity
    island._geo_to = None
    pet.motion.mode = "normal"
    clock.advance(0.05)  # 仍在 0.25s 反馈闸内
    field_.clamp(pet, 500, 50)
    assert pet.sounds == 1
    assert pet.effects.squashes == 1


def test_reset_clears_every_table(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 40)
    field_ = _field(island, config, [pet], clock)
    field_.clamp(pet, 500, 40)
    clock.advance(0.016)
    field_.clamp(pet, 500, 48)
    field_.reset()
    assert field_._contact == {} and field_._cooldown == {}
    assert field_._feedback_at == {} and field_._resting == {}


def test_dropping_off_the_island_falls_instead_of_floating(make_island, clock):
    """岛走开后，原本停在胶囊顶上的桌宠要自由落体（normal 态没有重力）。"""
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    resolution = field_.reflect_throw(pet, 500, 30, 0.0, 60.0)
    assert resolution.rested is True
    pet.move(int(round(resolution.px)), int(round(resolution.py)))
    assert field_._resting

    island._dragging = True
    field_.on_geometry_changed()  # 基线
    clock.advance(0.016)
    island.move(ISLAND_RECT[0], ISLAND_RECT[1] + 200)  # 岛走开
    field_.on_geometry_changed()
    island._dragging = False
    assert pet.motion.set_calls, "落岛的桌宠在岛走开后必须补一次下落"
    assert pet.motion.velocity()[1] > 0.0


def test_a_pet_that_walked_off_by_itself_is_not_dropped(make_island, clock):
    island, config = make_island()
    pet = _FakePet(0, 0)
    field_ = _field(island, config, [pet], clock)
    resolution = field_.reflect_throw(pet, 500, 30, 0.0, 60.0)
    pet.move(int(round(resolution.px)), int(round(resolution.py)))
    pet.move(pet.x(), pet.y() - 40)  # 用户自己把它挪走了
    island.move(ISLAND_RECT[0], ISLAND_RECT[1] + 200)
    field_.on_geometry_changed()
    assert pet.motion.set_calls == []


def test_stale_slot_keys_are_pruned(make_island, clock):
    island, config = make_island()
    pet = _FakePet(500, 40)
    pets = [pet]
    field_ = IslandField(island, config, lambda: list(pets), clock=clock)
    pet.field = field_
    field_.clamp(pet, 500, 40)
    pets.clear()  # 桌宠被关掉
    field_.on_geometry_changed()
    assert field_._contact == {}


def test_thrown_pet_keeps_the_island_impulse_when_pets_separate(tmp_path):
    """宠-宠分离不许覆盖撞岛刚写下的冲量（两处改速度打架）。"""
    from petcore.ui.pet_manager import PetManager

    class _Host:
        def __init__(self):
            self.root = tmp_path
            self.config = Config(tmp_path)
            self.pets = None

    manager = PetManager(_Host(), tmp_path, Config(tmp_path))
    pet = _FakePet(0, 0)
    pet.motion.set_velocity(0.0, -900.0)
    assert pet.motion.thrown
    calls_before = len(pet.motion.set_calls)
    try:
        manager._apply_body(pet, 10.0, 10.0, 500.0, 0.0, impact_speed=800.0)
        assert len(pet.motion.set_calls) == calls_before
    finally:
        manager.shutdown()
