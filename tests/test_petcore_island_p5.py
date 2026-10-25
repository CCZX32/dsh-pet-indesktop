from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from petcore.account.service import BalanceResult
from petcore.island import segments as isl
from petcore.island.segments import SegmentSnapshot
from petcore.ui.island import DynamicIsland


class _Config:
    def __init__(self):
        self.data = {
            "island_enabled": True,
            "island_metrics": ["cpu", "gpu", "fps"],
            "island_show_icon": True,
            "island_show_name": True,
            "island_show_status": True,
            "island_info_mode": "full",
            "island_custom_text": "",
            "island_style": "dark",
            "island_opacity": 1.0,
            "island_accent": "blue",
            "island_x": None,
            "island_y": None,
        }
        self.saved = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saved += 1


def _app():
    return QApplication.instance() or QApplication([])


def test_island_card_contains_balance_messages_extensions_and_unavailable_probes():
    _app()
    island = DynamicIsland(_Config(), character_name="测试宠物")
    island.show_balance(BalanceResult("svc", "3.00", "", ""))
    island.add_message("最近一条消息")
    island.register_segment(SegmentSnapshot("third-party", "扩展", "在线", "在线"))
    rows = island._card_rows()
    labels = [row[0] for row in rows]
    assert "余额" in labels
    assert "最近消息" in labels
    assert "扩展" in labels
    assert any(row[2] == "当前环境未接入可用 GPU/FPS 探针" for row in rows)
    island.clear_segments()
    island.deleteLater()


def test_island_signals_expose_balance_and_settings_actions():
    _app()
    island = DynamicIsland(_Config())
    balance = []
    settings = []
    island.balance_requested.connect(lambda: balance.append(True))
    island.settings_requested.connect(lambda: settings.append(True))
    island.card._refresh_button.click()
    island.card._settings_button.click()
    assert balance == [True]
    assert settings == [True]
    island.deleteLater()

def test_island_accepts_optional_gpu_probe_snapshot_without_starting_a_sampler():
    _app()
    island = DynamicIsland(_Config())
    island.set_probe_snapshot(
        SegmentSnapshot(
            isl.GPU,
            label="GPU",
            text="73",
            max_text="100",
            detail={"unit": "%", "source": "probe"},
        )
    )
    gpu = next(segment for segment in island._row if segment.seg_id == isl.GPU)
    assert gpu.text == "73"
    assert gpu.box_text == "100"
    assert gpu.unit == "%"
    island.clear_probe_snapshot(isl.GPU)
    gpu = next(segment for segment in island._row if segment.seg_id == isl.GPU)
    assert gpu.state == isl.STATE_ERROR
    assert "未接入" in gpu.detail["error_reason"]
    island.deleteLater()
