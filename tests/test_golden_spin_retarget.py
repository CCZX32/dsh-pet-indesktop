# -*- coding: utf-8 -*-
"""黄金回旋换目标：控制器全壳共享、目标独占（R06）。

全壳共用一条 ``GoldenSpinController``（角度状态机），角度却落在**各 sprite 自己
身上**（``PetSprite.set_throw_rotation``），每拍只写给当前目标。A 转到一半对 B
触发时，此前只把 ``_golden_spin_target`` 换成 B：A 再没人给它写 0，永远停在那一刻
的倾斜角上（归零只发生在控制器对**当前**目标走完最后一圈）；菜单路径还会因为
``start()`` 的 active 拒绝而整个静默，点击路径则把 A 那圈快速收尾后接着写给 B。

纪律：offscreen；时钟用控制器 ``_update(now)`` 同步驱动，不起真 QTimer、不 sleep
赌时序；点击走真实 overlay 鼠标事件（沿用 ``test_overlay_golden_spin_click`` 的
装配）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication

from pet.golden_spin import GOLDEN_SPIN_DURATION_MS
from tests.test_overlay_dead_switches import (
    _hit_pos,
    _make_shell,
    _mouse_event,
)
from tests.test_sprite_menu_facade import RichLibrary

app = QApplication.instance() or QApplication([])


def _make_two_pet_shell(tmp_path, values=None):
    """真壳 + 主宠 + 一只子宠；两只都摆到互不重叠的位置（点击要能分辨）。"""
    shell, _lib = _make_shell(tmp_path, values)
    # 子宠建库同样走 facade 的假素材库（CapLibrary 没有 ``movie``，绑不了 clip）
    shell._create_main_library = RichLibrary
    shell.spawn_pet()
    assert len(shell.overlay.sprites) == 2, "前提：壳里必须有两只能各自旋转的宠"
    main, child = shell.sprite, shell._spawned[0]
    main.set_pos(QPointF(100.0, 300.0))
    child.set_pos(QPointF(700.0, 300.0))
    for sprite in (main, child):
        sprite.bind_clip("idle1")
        sprite._rebuild_pixmap()
    return shell, main, child


def _advance(spin, ms: float) -> None:
    """把共享会话推进 ``ms`` 毫秒（同步直调；控制器只按 ``_rev_started_at`` 算进度）。"""
    spin._update(spin._rev_started_at + float(ms) / 1000.0)


def test_retarget_menu_trigger_settles_previous_pet_and_spins_new_one(tmp_path):
    """A 转到中途 → 对 B 触发：A 角度归零、B 从自然角开始转。"""
    shell, a, b = _make_two_pet_shell(tmp_path)
    try:
        shell.trigger_golden_spin(a)
        spin = shell._golden_spin
        assert spin is not None and spin.active
        _advance(spin, GOLDEN_SPIN_DURATION_MS / 2)
        assert a.throw_rotation < 0.0, "前提：A 已经转到中途"

        shell.trigger_golden_spin(b)

        assert shell._golden_spin_target is b
        assert a.throw_rotation == 0.0, "旧目标必须回正——否则永远停在倾斜角上"
        assert b.throw_rotation == 0.0
        assert spin.active and spin.queued_turns == 1, "新目标要开始转（不是被直接拒绝）"

        _advance(spin, GOLDEN_SPIN_DURATION_MS / 2)
        assert b.throw_rotation < 0.0, "B 开始转"
        assert a.throw_rotation == 0.0, "A 已脱离控制器，不再被写角"
    finally:
        shell._delete_runtime_marker()


def test_retarget_click_direct_settles_previous_pet(tmp_path):
    """点击直连（``golden_spin_direct``）：对另一只点击同样结清旧目标。"""
    shell, a, b = _make_two_pet_shell(
        tmp_path, {"golden_spin_on_click": True, "golden_spin_direct": True})
    try:
        shell.trigger_golden_spin(a)
        spin = shell._golden_spin
        _advance(spin, GOLDEN_SPIN_DURATION_MS / 2)
        assert a.throw_rotation < 0.0, "前提：A 已经转到中途"

        pos = _hit_pos(b)
        shell.overlay.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, pos))
        shell.overlay.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, pos))

        assert shell._golden_spin_target is b
        assert a.throw_rotation == 0.0, "旧目标必须回正"
        assert spin.active and spin.queued_turns == 1, "B 重新起转，不接 A 的会话"
        _advance(spin, GOLDEN_SPIN_DURATION_MS / 2)
        assert b.throw_rotation < 0.0 and a.throw_rotation == 0.0
    finally:
        shell._delete_runtime_marker()


def test_same_pet_repeated_trigger_keeps_single_session(tmp_path):
    """同一只连续触发（菜单/点击）：忽略重复启动，当前圈不被打断重开。"""
    shell, a, _b = _make_two_pet_shell(tmp_path)
    try:
        shell.trigger_golden_spin(a)
        spin = shell._golden_spin
        _advance(spin, GOLDEN_SPIN_DURATION_MS / 2)
        mid = a.throw_rotation
        assert mid < 0.0

        shell.trigger_golden_spin(a)

        assert shell._golden_spin_target is a
        assert spin.queued_turns == 1, "同一只连触发不叠圈、不重开"
        assert a.throw_rotation == mid, "当前圈必须接着转，不被打断回正"
    finally:
        shell._delete_runtime_marker()


def test_retarget_after_finish_starts_clean_session(tmp_path):
    """A 转完（自然归零）再对 B 触发：B 从不残留的角度起转。"""
    shell, a, b = _make_two_pet_shell(tmp_path)
    try:
        shell.trigger_golden_spin(a)
        spin = shell._golden_spin
        _advance(spin, GOLDEN_SPIN_DURATION_MS)
        assert not spin.active and a.throw_rotation == 0.0

        shell.trigger_golden_spin(b)

        assert shell._golden_spin_target is b
        assert spin.active
        assert b.throw_rotation == 0.0 and a.throw_rotation == 0.0
    finally:
        shell._delete_runtime_marker()
