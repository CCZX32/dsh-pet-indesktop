# -*- coding: utf-8 -*-
"""灵动岛网络槽（``island_network_enabled``）的接线契约。

覆盖：默认关（零线程零定时器）→ 开启后由后台采样器提供文本 → 隐藏即休眠、
显示恢复 → 关闭/改间隔即时生效 → 文案定宽。

采样器在测试里一律替换成替身（``DynamicIsland._make_net_monitor`` 替换点）：
**测试不发真实探测包、不碰 psutil**，活体行为由实机验证覆盖。时序断言不赌
真定时器节奏，全部同步直调。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
from pet import net_monitor
from pet.config import Config
from pet.dynamic_island import DynamicIsland

app = QApplication.instance() or QApplication([])


class StubMonitor:
    """采样器替身：只记录生命周期调用，样本由测试塞进去。"""

    def __init__(self, interval: float = net_monitor.DEFAULT_INTERVAL_SECONDS):
        self.interval = net_monitor.clamp_interval(interval)
        self.sample = None
        self.starts = 0
        self.stops = 0
        self.closed = False
        self.started = False

    # DynamicIsland 用到的面
    def start(self) -> bool:
        self.starts += 1
        self.started = True
        return True

    def stop(self, **_kwargs) -> None:
        self.stops += 1
        self.started = False

    def close(self) -> None:
        self.closed = True
        self.started = False

    def set_interval(self, interval: float) -> float:
        self.interval = net_monitor.clamp_interval(interval)
        return self.interval

    def snapshot(self):
        return self.sample


def _config(tmp_path, **network) -> Config:
    cfg = Config(base=tmp_path)
    cfg.set("dynamic_island", {
        "enabled": True, "show_icon": True, "show_name": True,
        "show_info": True, "info_mode": "time", "custom_text": "",
        "show_status": True, "style": "dark", "x": 400, "y": 300,
    })
    for key, value in network.items():
        cfg.set(key, value)
    return cfg


def _island(tmp_path, monkeypatch, **network) -> tuple[DynamicIsland, list[StubMonitor]]:
    made: list[StubMonitor] = []

    def factory(_self, interval):
        monitor = StubMonitor(interval)
        made.append(monitor)
        return monitor

    monkeypatch.setattr(island_mod.DynamicIsland, "_make_net_monitor", factory)
    return DynamicIsland(_config(tmp_path, **network)), made


def _sample(down=2048.0, up=512.0, latency=23.0, lost=False):
    return net_monitor.NetSample(
        down_bps=down, up_bps=up, latency_ms=latency, latency_lost=lost, sampled_at=1.0,
    )


# ---------------------------------------------------------------- 默认关
def test_network_slot_off_by_default_uses_info_mode_and_starts_nothing(tmp_path, monkeypatch):
    island, made = _island(tmp_path, monkeypatch)
    try:
        island.show()
        app.processEvents()
        assert made == [], "默认关不得创建采样器（更别提起线程/发包）"
        assert island._net_timer.isActive() is False
        assert island._info_text() == island._info_text()  # 走 info_mode 分支
        assert "↓" not in island._info_text()
    finally:
        island.close()


# ---------------------------------------------------------------- 开启
def test_network_slot_on_starts_worker_and_shows_sample(tmp_path, monkeypatch):
    island, made = _island(
        tmp_path, monkeypatch, island_network_enabled=True,
        network_probe_interval_seconds=2.0,
    )
    try:
        island.show()
        app.processEvents()
        assert len(made) == 1
        assert made[0].started is True
        assert island._net_timer.isActive() is True
        assert island._net_timer.interval() == 2000

        # 采样器还没出结果：槽位显示占位（0B / --），不空着也不编造
        assert island._info_text() == net_monitor.format_network_slot(0.0, 0.0, None)

        made[0].sample = _sample()
        island._tick_network()
        text = island._info_text()
        assert text.startswith("↓")
        assert "↓" in text and "↑" in text and "23ms" in text
        assert "2K" in text and "512B" in text
    finally:
        island.close()


def test_network_slot_tick_keeps_text_width_stable(tmp_path, monkeypatch):
    """文案定宽：速率/延迟变化不得改文本宽度（否则胶囊每秒左右抖）。"""
    island, made = _island(tmp_path, monkeypatch, island_network_enabled=True)
    try:
        island.show()
        app.processEvents()
        widths = set()
        for sample in (
            _sample(0.0, 0.0, None, lost=True),
            _sample(12 * 1024 * 1024, 300 * 1024, 8.0),
            _sample(987654321.0, 1024.0, 123.4),
        ):
            made[0].sample = sample
            island._tick_network()
            widths.add(len(island._info_text()))
        assert len(widths) == 1, widths
    finally:
        island.close()


def test_network_slot_lost_probe_shows_dashes(tmp_path, monkeypatch):
    island, made = _island(tmp_path, monkeypatch, island_network_enabled=True)
    try:
        island.show()
        app.processEvents()
        made[0].sample = _sample(latency=None, lost=True)
        island._tick_network()
        assert island._info_text().endswith("--")
    finally:
        island.close()


def test_network_slot_ignores_tick_before_first_sample(tmp_path, monkeypatch):
    island, made = _island(tmp_path, monkeypatch, island_network_enabled=True)
    try:
        island.show()
        app.processEvents()
        island._tick_network()  # 快照还是 None：不抛、不改状态
        assert island._net_sample is None
    finally:
        island.close()


# ---------------------------------------------------------------- 休眠/恢复
def test_network_slot_sleeps_when_hidden_and_resumes_on_show(tmp_path, monkeypatch):
    island, made = _island(tmp_path, monkeypatch, island_network_enabled=True)
    try:
        island.show()
        app.processEvents()
        assert island._net_timer.isActive() is True

        island.hide()
        app.processEvents()
        assert island._net_timer.isActive() is False
        assert made[0].stops >= 1, "隐藏即休眠：采样线程必须停"

        island.show()
        app.processEvents()
        assert island._net_timer.isActive() is True
        assert made[0].started is True, "显示后应恢复采样"
    finally:
        island.close()


# ---------------------------------------------------------------- 配置变更
def test_network_slot_disabled_by_config_change_closes_worker(tmp_path, monkeypatch):
    island, made = _island(tmp_path, monkeypatch, island_network_enabled=True)
    try:
        island.show()
        app.processEvents()
        island._net_sample = _sample()
        island.config.set("island_network_enabled", False)
        island.refresh_from_config()
        assert made[0].closed is True
        assert island._net_monitor is None
        assert island._net_sample is None
        assert island._net_timer.isActive() is False
        assert "↓" not in island._info_text(), "关掉后信息槽必须回到 info_mode 内容"
    finally:
        island.close()


def test_network_slot_interval_change_applies_without_rebuild(tmp_path, monkeypatch):
    island, made = _island(
        tmp_path, monkeypatch, island_network_enabled=True,
        network_probe_interval_seconds=1.0,
    )
    try:
        island.show()
        app.processEvents()
        island.config.set("network_probe_interval_seconds", 5.0)
        island.refresh_from_config()
        assert len(made) == 1, "改间隔不该重建采样器"
        assert made[0].interval == 5.0
        assert made[0].closed is False
        assert island._net_timer.interval() == 5000
    finally:
        island.close()


def test_network_slot_dirty_interval_is_clamped(tmp_path, monkeypatch):
    island, made = _island(
        tmp_path, monkeypatch, island_network_enabled=True,
        network_probe_interval_seconds=0.01,
    )
    try:
        island.show()
        app.processEvents()
        assert made[0].interval == net_monitor.MIN_INTERVAL_SECONDS
        assert island._net_timer.interval() == 500
    finally:
        island.close()
