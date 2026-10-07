# -*- coding: utf-8 -*-
"""GPU 能力占位（P3 Slice F1）的契约测试：已知 id + 不可用态 + 不占位 + 卡片原因行。

**本 slice 不实现数据源**，所以 gpu 是"已注册但恒不可用"的段——这里的断言就是
把这句话钉死，免得将来有人以为它只是"还没接上"的临时缺口：

1. **config 白名单放行**：``gpu`` 是合法 ``island_metrics`` 成员，落盘 → 重启往返
   不被归一化丢掉（与 network/cpu/mem 同一口径）。
2. **胶囊不占位**：段列表里没有它、行计划看不见它（也折不到 +N）、自然宽/高/停靠
   尺寸与"配置里根本没有这个 id"逐像素相同。
3. **卡片有原因行**：B 区一行「该指标不可用 + 原因」，段名走 ``_CARD_METRIC_NAMES``。
4. **不采样**：它不在设备槽订阅集合里（没有数据源就不能占采样线程）。

E5 的机制（``_unavailable_reasons`` + ``_compose_info_segments`` 跳过）已经铺好，
本文件验的是 **F1 把它真的接上了**——而不是机制还在原地空转。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
from pet import island_segments as isl
from pet.config import Config
from pet.island_segments import CPU, GPU, MEM, NETWORK
from tests.test_island_segment_render import _config, _island

app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- config 放行
def test_gpu_is_a_known_metric_id_that_survives_a_restart(tmp_path):
    """白名单放行：gpu 落盘 → 重启加载后仍在列表里（不是"脏值被丢弃"）。"""
    cfg = Config(base=tmp_path)
    cfg.set("island_metrics", [CPU, GPU])
    assert cfg.get("island_metrics") == [CPU, GPU]
    assert cfg.save() is True
    restored = Config(base=tmp_path)
    assert restored.get("island_metrics") == [CPU, GPU]
    assert isl.GPU == "gpu", "常量是唯一来源（config 白名单引用它，不抄字面量）"


def test_gpu_sits_after_the_three_builtin_ids(tmp_path):
    """四个合法 id 的相对次序原样保留（列表序 = 用户优先级）。"""
    cfg = Config(base=tmp_path)
    cfg.set("island_metrics", [MEM, NETWORK, CPU, GPU])
    assert cfg.get("island_metrics") == [MEM, NETWORK, CPU, GPU]


# ---------------------------------------------------------------- 占位四面
def test_gpu_is_registered_as_unavailable_with_a_truthful_reason(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cfg.set("island_metrics", [CPU, GPU])
    island, _made = _island(cfg, monkeypatch)
    try:
        unavailable = island._unavailable_segments()
        assert set(unavailable) == {GPU}
        reason = unavailable[GPU]
        assert reason == isl.GPU_UNAVAILABLE_REASON
        assert "未接入" in reason or "占位" in reason, \
            "原因必须如实说「本版本没实现」，不许声称探测过本机硬件"
    finally:
        island.close()


def test_gpu_never_takes_a_capsule_slot(tmp_path, monkeypatch):
    """胶囊四面都对不上它：段列表、行计划、折叠、几何尺寸。"""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_gpu, _m1 = _island(_config(tmp_path / "a"), monkeypatch)
    without_gpu, _m2 = _island(_config(tmp_path / "b"), monkeypatch)
    try:
        with_gpu.config.set("island_metrics", [CPU, GPU])
        without_gpu.config.set("island_metrics", [CPU])
        assert [seg.seg_id for seg in with_gpu._compose_info_segments()] == ["primary", CPU]
        assert GPU not in with_gpu._row_plan().visible
        assert GPU not in with_gpu._row_plan().folded, "不占位段连 +N 都折不到"
        assert with_gpu._capsule_width() == without_gpu._capsule_width()
        assert with_gpu.height() == without_gpu.height()
        assert with_gpu._rest_size() == without_gpu._rest_size()
    finally:
        with_gpu.close()
        without_gpu.close()


def test_gpu_gets_a_reason_row_in_the_card(tmp_path, monkeypatch):
    """卡片 B 区：一行写明「该指标不可用 + 原因」，与 E5 的不可用段同一写法。"""
    cfg = _config(tmp_path)
    cfg.set("island_metrics", [CPU, GPU])
    island, _made = _island(cfg, monkeypatch)
    try:
        rows = {row.seg_id: row for row in island._card_metric_rows()}
        assert set(rows) == {CPU, GPU}
        row = rows[GPU]
        assert row.name == "GPU", "卡片段名走 _CARD_METRIC_NAMES"
        assert row.state == isl.STATE_UNSUPPORTED
        assert row.value == isl.UNKNOWN_TEXT
        assert row.note == f"该指标不可用：{isl.GPU_UNAVAILABLE_REASON}"
        assert row.detail == row.note
    finally:
        island.close()


def test_gpu_row_keeps_the_configuration_order_in_the_card(tmp_path, monkeypatch):
    """卡片行序 = 配置序（不可用段按它本该在的位置插进去，不飘到末尾）。"""
    cfg = _config(tmp_path)
    cfg.set("island_metrics", [GPU, CPU])
    island, _made = _island(cfg, monkeypatch)
    try:
        assert [row.seg_id for row in island._card_metric_rows()] == [GPU, CPU]
    finally:
        island.close()


def test_gpu_takes_no_sampling_subscription(tmp_path, monkeypatch):
    """没有数据源就不许占采样线程：设备槽订阅集合里只有真正可采的段。"""
    cfg = _config(tmp_path)
    cfg.set("island_metrics", [CPU, GPU, MEM])
    island, made = _island(cfg, monkeypatch)
    try:
        island.show()
        app.processEvents()
        subscribed = set().union(*(monitor.subscribed for monitor in made))
        assert isl.CPU in subscribed or isl.MEM in subscribed
        assert GPU not in subscribed
        assert GPU not in island_mod._DEVICE_LABELS
        assert GPU not in island_mod._SYS_METRIC_IDS
    finally:
        island.close()


def test_turning_gpu_on_alone_still_renders_the_capsule(tmp_path, monkeypatch):
    """只勾 GPU：胶囊照画（只剩主信息段），卡片多一行原因，不崩不空窗。"""
    cfg = _config(tmp_path)
    cfg.set("island_metrics", [GPU])
    island, _made = _island(cfg, monkeypatch)
    try:
        island.show()
        app.processEvents()
        assert [seg.seg_id for seg in island._compose_info_segments()] == ["primary"]
        assert island._capsule_width() > 0
        assert [row.seg_id for row in island._card_metric_rows()] == [GPU]
    finally:
        island.close()
