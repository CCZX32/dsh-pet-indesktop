# -*- coding: utf-8 -*-
"""R1 评审修复的回归守卫：包络外网络读数不得引起计划/订阅/几何振荡。

astra 终审阻塞 1（2026-10-07）：``7947a18`` 让网络段盒宽取 max(样本, 现文案)，
采样值经 ``box_text`` 变相进 ``_plan_inputs`` 键；临界收缩预算下会形成
「超包络读数 → 计划变宽 → 折叠网络段 → 清样本 → 计划变窄 → 展开 → 再采样 →
再超包络」的反馈循环（每秒重建采样线程 + 反复播淡化），且新计划宽度与窗口
几何长期不一致（tick 只 update() 不提交几何）。修复后盒宽恒为声明样本，
本文件把「临界预算 + 持续超包络输入」下的稳定性钉死。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
from pet import net_monitor
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.island_segments import NETWORK

app = QApplication.instance() or QApplication([])


class _StubMonitor:
    """可控样本的网络采样器替身（只喂样本，不发探测包）。"""

    def __init__(self, interval):
        self.interval = interval
        self.sample = None
        self.starts = 0
        self.closes = 0

    def set_interval(self, interval):
        self.interval = interval

    def snapshot(self):
        return self.sample

    def subscribe(self, key):
        pass

    def unsubscribe(self, key):
        pass

    def start(self):
        self.starts += 1

    def stop(self, wait=False):
        pass

    def close(self):
        self.closes += 1


class _FakeScreen:
    def __init__(self, width):
        self._rect = QRect(0, 0, width, 768)

    def availableGeometry(self):
        return self._rect


def _sample(down, up, latency):
    return net_monitor.NetSample(
        down_bps=down, up_bps=up, latency_ms=latency,
        latency_lost=False, sampled_at=1.0)


def _island(monkeypatch, screen_width):
    made = []

    def net_factory(_self, interval):
        monitor = _StubMonitor(interval)
        made.append(monitor)
        return monitor

    monkeypatch.setattr(island_mod.DynamicIsland, "_make_net_monitor", net_factory)
    monkeypatch.setattr(island_mod.DynamicIsland, "_make_sys_monitor", net_factory)
    screen = _FakeScreen(screen_width)
    monkeypatch.setattr(island_mod.DynamicIsland, "_current_screen", lambda self: screen)
    cfg = Config(base=tempfile.mkdtemp())
    cfg.set("dynamic_island", {
        "enabled": True, "show_icon": True, "show_name": True, "show_info": True,
        "info_mode": "time", "custom_text": "", "show_status": True,
        "style": "dark", "x": 40, "y": 300})
    cfg.set("island_metrics", [NETWORK])
    return DynamicIsland(cfg), made[0] if made else None, made, screen


def _critical_width(island, screen):
    """实测搜索「网络段刚好不被折叠」的最窄屏宽（真实字体，不写死 px）。"""
    for width in range(1500, 150, -2):
        screen._rect = QRect(0, 0, width, 768)
        island.refresh_from_config()
        if not island._row_plan().folded:
            return width
    raise AssertionError("找不到网络段不被折叠的屏宽")


def test_beyond_envelope_readings_never_change_the_plan(monkeypatch):
    """包络外读数推进 50 拍：计划键/岛宽/折叠态/订阅全程不变（宽度不变量）。"""
    island, _m, made, screen = _island(monkeypatch, 800)
    try:
        island.show()
        app.processEvents()
        monitor = made[0]
        width0 = _critical_width(island, screen)
        monitor.sample = _sample(2048.0, 512.0, 23.0)
        island._tick_network()
        app.processEvents()
        key_ok = island._plan_inputs()
        folded_ok = island._row_plan().folded
        width_px = island.width()
        starts0, closes0 = monitor.starts, monitor.closes

        # 持续超包络输入（G 级速率 + 四位毫秒）50 拍
        monitor.sample = _sample(1023 * 1024 ** 3, 1023 * 1024 ** 3, 1000.0)
        for _ in range(50):
            island._tick_network()
            app.processEvents()
        assert island._plan_inputs() == key_ok, (
            "超包络读数改变了计划键——采样值穿透宽度白名单（R1 阻塞回归）")
        assert island._row_plan().folded == folded_ok, "折叠态不应随读数翻转"
        assert island.width() == width_px, "岛宽不应随读数变化"
        assert (monitor.starts, monitor.closes) == (starts0, closes0), (
            "采样器不应因读数变化被重建（振荡已消除）")

        # 包络内外来回跳同样稳定（K↔G 跨档不触发任何结构变化）
        for down, up, ms in ((2048.0, 512.0, 23.0),
                             (1023 * 1024 ** 3, 1023 * 1024 ** 3, 1000.0)) * 5:
            monitor.sample = _sample(down, up, ms)
            island._tick_network()
            app.processEvents()
        assert island._plan_inputs() == key_ok
        assert island._row_plan().folded == folded_ok
        assert island.width() == width_px
        assert (monitor.starts, monitor.closes) == (starts0, closes0)
    finally:
        island.close()


def test_plan_and_geometry_stay_consistent_across_ticks(monkeypatch):
    """临界预算下读数任意跳：窗口宽始终 == 当刻行计划宽（几何不会落后于计划）。"""
    island, _m, made, screen = _island(monkeypatch, 800)
    try:
        island.show()
        app.processEvents()
        monitor = made[0]
        _critical_width(island, screen)
        for down, up, ms in ((2048.0, 512.0, 23.0),
                             (1023 * 1024 ** 3, 1023 * 1024 ** 3, 1000.0),
                             (900 * 1024, 800 * 1024, 120.0),
                             (5 * 1024 ** 2, 3 * 1024 ** 2, 300.0)):
            monitor.sample = _sample(down, up, ms)
            island._tick_network()
            app.processEvents()
            assert island.width() == island._row_plan().width, (
                f"读数 {down}/{up}/{ms} 后窗口宽与计划宽不一致")
    finally:
        island.close()
