"""灵动岛停靠（dock）与几何动画：主分支 `pet/dynamic_island.py` 的口径。

用户可见的回归都在这里钉住：
1. **拖不动**：旧实现调用不存在的 `QWidget.startDragDistance()`，每次拖拽都在
   第一帧抛 `AttributeError`，退化成单击；
2. **边缘吸附**：松手距边 ≤40px 收成 16px 细条，悬停滑出、离开 800ms 收回；
3. **细条不采样**：16px 里内容一个像素都不画，「看不清就不采」；
4. **落点按松手光标选屏**，不按窗口左上角；
5. **几何动画**：180ms ease-out-cubic，只在动画期间跑 16ms 表。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

from petcore.config import Config
from petcore.island import layout
from petcore.platform import netmon, sysmon
from petcore.ui import island as island_ui

app = QApplication.instance() or QApplication([])

SCREEN = (0, 0, 1920, 1080)


class _Event:
    """最小鼠标事件替身：press/release 只用 button/globalPosition，move 还要 buttons。"""

    def __init__(self, point: QPoint, button=Qt.MouseButton.LeftButton, buttons=None) -> None:
        self._point = point
        self._button = button
        self._buttons = (
            Qt.MouseButton.LeftButton if buttons is None else buttons
        )

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def globalPosition(self) -> QPointF:
        return QPointF(self._point)

    def accept(self) -> None:
        return None


@pytest.fixture()
def make_island(tmp_path):
    created = []

    def factory(values=None, *, character_name="深深"):
        config = Config(
            tmp_path,
            {
                "island_enabled": True,
                "island_metrics": ["cpu", "mem"],
                **(values or {}),
            },
        )
        widget = island_ui.DynamicIsland(config, character_name=character_name)
        # 用真实屏幕几何替身，避免 offscreen 平台 800×800 影响停靠判定。
        widget._screen_at = lambda _point=None: _FakeScreen(SCREEN)  # noqa: SLF001
        widget._screen = lambda: _FakeScreen(SCREEN)  # noqa: SLF001
        created.append(widget)
        return widget

    yield factory
    for widget in created:
        widget.stop()
        assert widget.sys_monitor.wait_stopped(5)
        assert widget.net_monitor.wait_stopped(5)
        widget.close()
        widget.deleteLater()


class _FakeScreen:
    def __init__(self, area) -> None:
        self._area = QRect(*area)

    def availableGeometry(self) -> QRect:  # noqa: N802 - Qt 命名
        return QRect(self._area)

    def geometry(self) -> QRect:  # noqa: N802
        return QRect(self._area)


# ---------------------------------------------------------------- 纯函数口径


def test_dock_edge_uses_40px_threshold_on_all_four_edges():
    area = SCREEN
    assert layout.dock_edge_for((0, 300, 200, 44), area) == "left"
    assert layout.dock_edge_for((1720, 300, 200, 44), area) == "right"
    assert layout.dock_edge_for((800, 0, 200, 44), area) == "top"
    assert layout.dock_edge_for((800, 1036, 200, 44), area) == "bottom"
    # 41px 就不断言停靠（阈值是 40，且比较的是绝对距离）
    assert layout.dock_edge_for((800, 41, 200, 44), area) == "none"
    assert layout.dock_edge_for((800, 40, 200, 44), area) == "top"
    assert layout.dock_edge_for((800, 500, 200, 44), area) == "none"


def test_strip_rect_uses_half_of_top_plus_height_for_centering():
    area = (0, 0, 1920, 1080)
    # 左右停靠：16 厚、64 长、竖直中心 = rect.top() + h//2
    x, y, w, h = layout.strip_rect_for((500, 300, 200, 44), "left", area)
    assert (x, w, h) == (0, 16, 64)
    assert y == 300 + 44 // 2 - 64 // 2
    x, y, w, h = layout.strip_rect_for((500, 300, 200, 44), "right", area)
    assert (x, w, h) == (1920 - 16, 16, 64)
    # 上下停靠：厚度 16，宽度沿用胶囊
    assert layout.strip_rect_for((500, 300, 243, 44), "top", area) == (500, 0, 243, 16)
    assert layout.strip_rect_for((500, 300, 243, 44), "bottom", area) == (500, 1064, 243, 16)


def test_strip_length_is_clipped_to_screen_height():
    short = (0, 0, 1920, 40)
    assert layout.strip_rect_for((0, 10, 200, 44), "left", short)[3] == 40


def test_ease_out_cubic_endpoints():
    assert layout.ease_out_cubic(0.0) == 0.0
    assert layout.ease_out_cubic(1.0) == 1.0
    assert 0.5 < layout.ease_out_cubic(0.5) < 1.0


# ---------------------------------------------------------------- 拖动（旧 bug）


def test_drag_actually_moves_the_window(make_island):
    """旧实现 `self.startDragDistance()` 抛 AttributeError：拖拽永远不生效。"""
    island = make_island()
    island.move(400, 300)
    island.mousePressEvent(_Event(QPoint(405, 305)))
    island.mouseMoveEvent(_Event(QPoint(405 + 60, 305 + 30)))
    assert island.pos() == QPoint(460, 330)
    assert island._dragging is True  # noqa: SLF001


def test_small_jitter_is_still_a_click(make_island):
    island = make_island()
    island.move(400, 300)
    island.mousePressEvent(_Event(QPoint(405, 305)))
    island.mouseMoveEvent(_Event(QPoint(407, 306)))  # 小于平台拖拽阈值
    assert island.pos() == QPoint(400, 300)
    island.mouseReleaseEvent(_Event(QPoint(407, 306)))
    assert island.is_expanded() is True


def test_release_near_an_edge_docks_into_a_strip(make_island):
    island = make_island()
    island.move(1500, 400)
    island.mousePressEvent(_Event(QPoint(1505, 405)))
    island.mouseMoveEvent(_Event(QPoint(1505 + 200, 405)))  # 拖到右边缘
    island.mouseReleaseEvent(_Event(QPoint(1715, 405)))
    state = island.dock_state()
    assert state["edge"] == "right"
    assert state["strip"] is True
    assert island.width() == island_ui.STRIP_THICKNESS
    assert island.config.get("island_dock_edge") == "right"


def test_release_in_the_middle_does_not_dock(make_island):
    island = make_island()
    island.move(600, 400)
    island.mousePressEvent(_Event(QPoint(605, 405)))
    island.mouseMoveEvent(_Event(QPoint(700, 420)))
    island.mouseReleaseEvent(_Event(QPoint(700, 420)))
    assert island.dock_state()["edge"] == "none"
    assert island.dock_state()["strip"] is False
    assert island.config.get("island_dock_edge") == "none"


def test_edge_dock_switch_off_keeps_the_dragged_position(make_island):
    island = make_island({"island_edge_dock": False})
    island.move(1500, 400)
    island.mousePressEvent(_Event(QPoint(1505, 405)))
    island.mouseMoveEvent(_Event(QPoint(1715, 405)))
    island.mouseReleaseEvent(_Event(QPoint(1715, 405)))
    assert island.dock_state()["edge"] == "none"
    assert island.is_expanded() is False


def test_turning_the_dock_switch_off_releases_the_strip(make_island):
    """关掉「贴边停靠」必须立刻退出 16px 细条，否则岛看起来像消失了。"""
    island = make_island({"island_dock_edge": "left"})
    island.move(0, 400)
    island._apply_position(initial=True)  # noqa: SLF001
    assert island.dock_state()["strip"] is True
    island.config.set("island_edge_dock", False)
    island.refresh_from_config()
    assert island.dock_state()["strip"] is False
    assert island.width() > island_ui.STRIP_THICKNESS
    assert island.height() == island_ui.CAPSULE_HEIGHT


def test_dragging_out_of_a_dock_restores_the_capsule(make_island):
    island = make_island({"island_dock_edge": "right"})
    island.move(1700, 400)
    island._apply_position(initial=True)  # noqa: SLF001 - 读回停靠边
    assert island.dock_state()["strip"] is True
    island.mousePressEvent(_Event(QPoint(island.x() + 4, island.y() + 20)))
    island.mouseMoveEvent(_Event(QPoint(900, 500)))
    assert island.dock_state()["docked"] is False
    island.mouseReleaseEvent(_Event(QPoint(900, 500)))
    assert island.width() > island_ui.STRIP_THICKNESS


# ---------------------------------------------------------------- 悬停滑出


def test_hovering_the_strip_peeks_and_dock_back_returns(make_island, monkeypatch):
    island = make_island({"island_dock_edge": "left"})
    island.move(0, 400)
    island._apply_position(initial=True)  # noqa: SLF001
    assert island.dock_state()["strip"] is True
    monkeypatch.setattr(island, "_cursor_in_hover_zone", lambda: False)
    island.enterEvent(
        QEnterEvent(QPointF(1, 400), QPointF(1, 400), QPointF(1, 400))
    )
    assert island.dock_state()["peek"] is True
    assert island.width() > island_ui.STRIP_THICKNESS
    island.leaveEvent(QEvent(QEvent.Type.Leave))
    island._dock_back()  # noqa: SLF001 - 800ms 后到点
    assert island.dock_state()["strip"] is True


def test_dock_back_waits_while_the_cursor_is_in_the_hover_zone(make_island, monkeypatch):
    """光标还在滑出胶囊/细条死区里时收回 → 细条盖回光标 → 1s 自持振荡。"""
    island = make_island({"island_dock_edge": "left"})
    island.move(0, 400)
    island._apply_position(initial=True)  # noqa: SLF001
    island._hover_peek = True  # noqa: SLF001
    monkeypatch.setattr(island, "_cursor_in_hover_zone", lambda: True)
    island._dock_back()  # noqa: SLF001
    assert island.dock_state()["peek"] is True
    assert island._dock_back_timer.isActive()  # noqa: SLF001


def test_strip_stops_sampling_and_peek_restarts_it(make_island):
    island = make_island({"island_dock_edge": "left"})
    island.move(0, 400)
    island.show()
    try:
        island._apply_position(initial=True)  # noqa: SLF001
        island._clock.start()  # noqa: SLF001
        island._sync_sampling()  # noqa: SLF001
        # 细条态：内容不可见 → 采样全停
        assert island.sys_monitor.running() is False
        assert island.net_monitor.running() is False
        island._hover_peek = True  # noqa: SLF001
        island._sync_sampling()  # noqa: SLF001
        assert island.sys_monitor.running() is True
    finally:
        island._clock.stop()  # noqa: SLF001


# ---------------------------------------------------------------- 几何动画


def test_geometry_animation_interpolates_then_settles(make_island, monkeypatch):
    island = make_island()
    island.show()
    try:
        island.move(300, 200)
        target = QRect(700, 500, island.width(), island.height())
        island._animate_to(target)  # noqa: SLF001
        assert island._anim_timer.isActive()  # noqa: SLF001
        clock = [100.0]

        def fake_monotonic():
            clock[0] += island_ui.GEO_ANIM_SECONDS / 4.0
            return clock[0]

        monkeypatch.setattr(island_ui.time, "monotonic", fake_monotonic)
        island._anim_last = 100.0  # noqa: SLF001
        island._on_anim_tick()  # noqa: SLF001
        midway = island.geometry()
        assert island.x() > 300 and island.x() < 700
        for _ in range(8):
            island._on_anim_tick()  # noqa: SLF001
        assert island.geometry() == target
        assert island._anim_timer.isActive() is False  # noqa: SLF001
    finally:
        island.hide()


def test_hidden_island_snaps_instead_of_animating(make_island):
    island = make_island()
    target = QRect(500, 300, island.width(), island_ui.CAPSULE_HEIGHT)
    island._animate_to(target)  # noqa: SLF001 - 未 show() = 不可见
    assert island.geometry() == target
    assert island._anim_timer.isActive() is False  # noqa: SLF001


def test_update_size_is_frozen_while_dragging(make_island):
    island = make_island()
    before = island.width()
    island._dragging = True  # noqa: SLF001
    island.config.set("island_metrics", ["network", "cpu", "mem", "gpu"])
    island.settings = island_ui.IslandConfig.from_config(island.config)
    island._rebuild_row()  # noqa: SLF001
    island._update_size()  # noqa: SLF001
    assert island.width() == before


# ---------------------------------------------------------------- 采样器收口


def test_monitors_are_real_objects(make_island):
    island = make_island()
    assert isinstance(island.net_monitor, netmon.NetMonitor)
    assert isinstance(island.sys_monitor, sysmon.SysMonitor)
