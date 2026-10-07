# -*- coding: utf-8 -*-
"""评审修复批的契约测试（2026-10-07，多轮评审合流）。

来源映射（ops5.5 N1：半年后能反推每个用例是哪轮评审加的）：

- astra 终审 R1：bounce 闸门 / squish 横向 / FontChange 几何 / 卡片 hover / 内容键模板分量
- 6.1sol 交叉票 R2：起拖停淡化 / 部分折叠行标注 / oversize 含单位盒 / 审计用例诚实化
- 6.1sol 终审 R3：hover 真实序列（本节 ②）、closeEvent、滞回清零、折叠故障保持、
  DSH 关闭 offline（DSH 那例在本文件末尾）
- 网络包络振荡的回归在 ``test_island_network_envelope.py``（astra 阻塞 1）

- R1-2 工作上升沿弹跳必须过与 ``notify_event`` 同一道闸门（event_effects + 免打扰）
- R1-3 squish 拉伸期（sy>1）横向只鼓不缩，宽岛内容不出外壳
- R1-4 FontChange 后普通胶囊的窗口几何与行计划同步
- R1-5 展开卡片 hover 暂停 15s 自动收起（离开重新倒计时）
- 附：内容缓存键覆盖段模板分量（label/box_text 变化必须重建位图）
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
import pet.island_layout as island_layout_mod
from pet import quiet_mode
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.dsh_state import DshState

app = QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, width=1400):
        self._rect = QRect(0, 0, width, 768)

    def availableGeometry(self):
        return self._rect


class _StubMonitor:
    def __init__(self, interval):
        self.interval = interval
        self.sample = None
        self.started = False
        self.stops = 0
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
        self.started = True

    def stop(self, wait=False):
        self.started = False
        self.stops += 1

    def close(self):
        self.started = False
        self.closes += 1


def _island(monkeypatch, *, metrics=(), **overrides):
    def factory(_self, interval):
        return _StubMonitor(interval)

    monkeypatch.setattr(island_mod.DynamicIsland, "_make_net_monitor", factory)
    monkeypatch.setattr(island_mod.DynamicIsland, "_make_sys_monitor", factory)
    monkeypatch.setattr(island_mod.DynamicIsland, "_current_screen",
                        lambda self: _FakeScreen())
    cfg = Config(base=tempfile.mkdtemp())
    data = {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
            "info_mode": "time", "custom_text": "", "show_status": True,
            "style": "dark", "x": 400, "y": 300}
    data.update(overrides)
    cfg.set("dynamic_island", data)
    cfg.set("island_metrics", list(metrics))
    return DynamicIsland(cfg)


# ---------------------------------------------------------- R1-2 弹跳闸门
def test_work_edge_bounce_respects_event_effects_and_quiet_mode(monkeypatch):
    """DSH 开工弹跳：默认弹；event_effects 关掉不弹；免打扰期间不弹。

    astra 应修 2：修复前 ``set_dsh_state`` 的工作上升沿无条件 ``_bounce()``，
    与 ``notify_event``/``bump`` 的开关语义形成两套（裁决稿 §一-7：禁弹跳，
    读数照常——状态点本身不受闸门影响，所以只拦弹跳不拦状态）。
    """
    island = _island(monkeypatch)
    try:
        bounces = []
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))

        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [3.0], "默认（动效开+非免打扰）工作上升沿应弹一下"

        # event_effects 关掉：换岛重测（配置在岛实例上）
        island.close()
        island = _island(monkeypatch, event_effects=False)
        bounces.clear()
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [], "event_effects=False 时工作上升沿不许弹"
        island.close()

        # 免打扰期间：active()=True 的替身 QuietState
        class _Quiet:
            def suppression_active(self, **_kw):
                return True

        monkeypatch.setattr(quiet_mode, "shared_quiet_state", lambda: _Quiet())
        island = _island(monkeypatch)
        bounces.clear()
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [], "免打扰期间工作上升沿不许弹"
        # 状态本身照常（读数照常是 DND 规则的另一半）
        assert island._dsh_state == DshState.WORKING.value
    finally:
        island.close()


# ---------------------------------------------------------- R1-3 squish 横向只鼓不缩
def test_squish_stretch_never_narrows_the_shell(monkeypatch):
    """sy>1（拉伸期）外壳横向必须保持静止宽：内容不随形变，sx<1 会把宽岛的
    头像/状态点画到外壳外（astra 应修 3）。"""
    island = _island(monkeypatch, metrics=["cpu", "mem", "network"],
                     custom_text="x" * 60, info_mode="custom")
    try:
        island._update_size()
        app.processEvents()
        rest_rect, _ = island._squished_capsule_rect()
        assert rest_rect.left() == 6.0
        for sy in (0.85, 1.0, 1.06, 1.12):
            island._squish = sy
            rect, _r = island._squished_capsule_rect()
            assert rect.left() <= 6.0 + 0.01, (
                f"squish={sy} 外壳左缘 {rect.left():.2f} 越过静止左缘 6（横向收缩）")
            assert rect.right() >= rest_rect.right() - 0.01, (
                f"squish={sy} 外壳右缘 {rect.right():.2f} 窄于静止右缘 {rest_rect.right():.2f}")
    finally:
        island.close()


# ---------------------------------------------------------- R1-4 FontChange 几何同步
def test_font_change_commits_geometry_in_normal_mode(monkeypatch):
    """FontChange 清缓存后，普通胶囊的窗口宽必须当刻与行计划一致（astra 应修 4：
    修复前要等 30s 心跳或其他事件才同步，期间绘制与几何脱节）。

    测试必须**真的换字体**（6.1sol 建议 5）：不换字体时新旧自然宽相同，
    删掉 ``_update_size()`` 这行断言也能过——那是假绿。
    """
    island = _island(monkeypatch, metrics=["cpu", "mem"])
    try:
        island.show()
        app.processEvents()
        island._update_size()
        app.processEvents()
        width_before = island.width()
        # 岛的字体来自 _FONT_LAYERS 的像素常量（部件字体不影响它）——把 value 层
        # 改大：字体指纹必变、自然宽真变（前提断言）；再发 FontChange 事件
        monkeypatch.setitem(island_mod._FONT_LAYERS, "value",
                            (24, island_mod._FONT_LAYERS["value"][1]))
        island.changeEvent(QEvent(QEvent.Type.FontChange))
        app.processEvents()
        assert island._row_plan().width != width_before, (
            "前提：字号层变化后自然宽必须真的变化（否则本测试没有判别力）")
        assert island.width() == island._row_plan().width, (
            "FontChange 后窗口宽与行计划宽不一致（几何没有同步提交）")
    finally:
        island.close()


# ---------------------------------------------------------- R1-5 卡片 hover 暂停收起
def test_card_hover_pauses_auto_collapse(monkeypatch):
    """展开卡片：hover 暂停 15s 自动收起，离开重新倒计时（裁决稿 §一-10；
    astra 应修 5——修复前用户正读着卡片也会被定时器收掉）。"""
    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        # 真实序列（6.1sol 终审）：先在 normal 态 enter（单击前鼠标已在岛内），
        # 再 expand——这一序列下鼠标不会再产生 enterEvent，15s 表不得启动
        island.enterEvent(None)
        island.expand_card()
        assert island._card_collapse_timer.isActive() is False, (
            "鼠标已在岛内时展开卡片，自动收起不得启动（用户正读着卡片）")
        island.leaveEvent(None)
        assert island._card_collapse_timer.isActive() is True, (
            "离开卡片必须重新倒计时")
        assert island._card_collapse_timer.interval() == island_mod._CARD_AUTO_COLLAPSE_MS
        # 展开后才把鼠标挪进来：同样要暂停（enter/leave 双向守卫）
        island._card_collapse_timer.stop()
        island.enterEvent(None)
        assert island._card_collapse_timer.isActive() is False
        # 隐藏复位（A1 第二票 R3）：hide 后 _cursor_inside 必须是 False——
        # 否则陈旧 True 会让显示后的 expand_card 误判「鼠标在岛内」不起表
        island.hide()
        app.processEvents()
        assert island._cursor_inside is False
    finally:
        island.close()


# ---------------------------------------------------------- 附：内容键覆盖段模板
def test_content_cache_key_covers_label_and_box_template(monkeypatch):
    """段模板分量（label/box_text）变化必须重建内容位图（astra 建议 1：
    修复前内容键只有 text/unit/state/severity，模板变化而文本不变时会拿旧位图）。"""
    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        first = island._content_cache()
        monkeypatch.setitem(island_mod._DEVICE_LABELS, "cpu", "处理器")
        second = island._content_cache()
        assert second is not first, "label 变化必须重建内容层（键含 label）"
        monkeypatch.setitem(island_mod._DEVICE_LABELS, "cpu", "CPU")
        third = island._content_cache()
        assert third is not second
    finally:
        island.close()


# ---------------------------------------------------------- R2-1 超宽判决含单位盒
def test_oversize_candidates_use_the_full_double_box_width(monkeypatch):
    """120px 判决必须按「值盒+单位盒」完整口径（6.1sol 应修 2：修复前
    oversize_segment_ids 只量 label+max_text，长单位段绕过判决）。"""
    from PySide6.QtGui import QFont, QFontMetrics
    from pet import island_segments as segments

    metrics = QFontMetrics(QFont("", 13))
    try:
        decl = segments.register_segment(
            id="long_unit", label="",
            format_value=lambda v: "1", max_text="8", unit="MMMMMMMMMMMM")
        assert decl.width_px(metrics) > segments.MAX_SEGMENT_WIDTH_PX, (
            "前提：长单位把完整盒宽推过 120px")
        assert "long_unit" in segments.oversize_segment_ids(metrics), (
            "长单位段必须进超宽候选（判决含单位盒）")
    finally:
        segments.clear_segments()
        assert segments.oversize_segment_ids(metrics) == ()


# ---------------------------------------------------------- R2-2 起拖停淡化
def test_starting_a_drag_stops_the_in_flight_fade(monkeypatch):
    """「先淡化、后起拖」：起拖必须停掉进行中的淡化并跳终点帧（6.1sol 应修 3；
    修复前 _dragging 只拦新淡化，残影在拖拽中继续推进）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPixmap

    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        island._update_size()
        app.processEvents()
        pm = QPixmap(max(1, island.width()), 44)
        island._start_content_fade(pm)
        assert island._content_fade_timer is not None
        center = island.geometry().center()

        def mouse(kind, global_pos, buttons=Qt.MouseButton.LeftButton):
            local = island.mapFromGlobal(global_pos)
            return QMouseEvent(kind, QPointF(local), QPointF(global_pos),
                               Qt.MouseButton.LeftButton, buttons,
                               Qt.KeyboardModifier.NoModifier)

        island.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, center))
        far = type(center)(center.x() + 200, center.y() + 120)
        island.mouseMoveEvent(mouse(QEvent.Type.MouseMove, far))
        assert island._dragging is True, "前提：位移超过阈值后进入拖拽"
        assert island._content_fade_timer is None, "起拖必须停掉进行中的淡化"
        assert island._content_fade_t == 1.0
        island.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, far,
                                       buttons=Qt.MouseButton.NoButton))
    finally:
        island.close()


# ---------------------------------------------------------- R2-3 部分折叠行的如实标注
def test_partially_folded_device_row_is_marked_folded_not_live(monkeypatch):
    """只折内存（CPU 还在订阅）时，共享快照仍会顺带更新内存——卡片这行要标
    「已折叠 · N 秒前」，不能看起来与正常采样行一样（6.1sol 应修 4）。"""
    from pet import sys_monitor as sm
    from pet.island_segments import MEM

    island = _island(monkeypatch, metrics=["cpu", "mem"])
    try:
        # 找「只折 mem」的屏宽（真实字体实测搜索）
        screen = _FakeScreen(1400)
        monkeypatch.setattr(island_mod.DynamicIsland, "_current_screen",
                            lambda self: screen)
        island._sys_pending = set()
        monitor = island._sys_monitor
        monitor.sample = sm.SysSample(cpu_percent=42.0, mem_percent=61.0,
                                      sampled_at=__import__("time").monotonic())
        island.show()
        app.processEvents()
        island._tick_sys()
        app.processEvents()
        plan = None
        for width in range(1400, 200, -2):
            screen._rect = QRect(0, 0, width, 768)
            island.refresh_from_config()
            plan = island._row_plan()
            if plan.folded == (MEM,):
                break
        assert plan and plan.folded == (MEM,), "找不到只折内存的档"
        island._tick_sys()
        rows = {row.seg_id: row for row in island._card_metric_rows()}
        assert rows[MEM].updated.startswith("已折叠 ·"), (
            f"部分折叠行必须标已折叠：{rows[MEM].updated!r}")
        assert "暂停采样" not in rows[MEM].updated, (
            "共享快照仍在更新它——说「暂停采样」是谎话")
    finally:
        island.close()


# ---------------------------------------------------------- ops5.5 M1：closeEvent 收口
def test_close_event_closes_both_monitors(monkeypatch):
    """窗口销毁时两条采样器必须主动 close（有界 join 的收口路径才走得到）。"""
    island = _island(monkeypatch, metrics=["cpu", "network"])
    try:
        island.show()
        app.processEvents()
        net_mon, sys_mon = island._net_monitor, island._sys_monitor
        assert net_mon is not None and sys_mon is not None
        island.close()
        app.processEvents()
        assert island._net_monitor is None and island._sys_monitor is None
        assert net_mon.closes >= 1 and sys_mon.closes >= 1
    finally:
        island.close()


# ---------------------------------------------------------- ops5.5 M3：退订清滞回
def test_unsubscribing_a_metric_clears_its_hysteresis_memory(monkeypatch):
    """CPU 92(crit) 折掉 → 跌到 85 恢复：按新采样序列应判 warn，不按旧记忆保 crit。

    口径（与 E2 调和后）：**折叠保持** severity（chip 告警点的唯一来源），
    **恢复订阅那一刻清零**（新采样序列）——两处各司其职。
    """
    import time as _time

    from pet import island_segments as isl
    from pet import sys_monitor as sm
    from pet.island_segments import CPU

    island = _island(monkeypatch, metrics=["cpu", "mem"])
    try:
        island.show()
        app.processEvents()
        monitor = island._sys_monitor
        monitor.sample = sm.SysSample(cpu_percent=92.0, mem_percent=40.0,
                                      sampled_at=_time.monotonic())
        island._tick_sys()
        assert island._alert_severity.get(CPU) == isl.ALERT_CRIT
        # 折叠 CPU（改配置撤段 = 退订路径）→ severity 保持（chip 告警点靠它亮）
        island.config.set("island_metrics", ["mem"])
        island.refresh_from_config()
        app.processEvents()
        assert island._alert_severity.get(CPU) == isl.ALERT_CRIT, (
            "折叠必须保持 severity（E2「折叠不埋没告警」）")
        # 恢复订阅那一刻清零（M3：新采样序列）→ 喂 85 从空记忆起步 → warn
        island.config.set("island_metrics", ["cpu", "mem"])
        island.refresh_from_config()
        app.processEvents()
        assert CPU not in island._alert_severity, "恢复订阅后滞回记忆必须清零"
        monitor.sample = sm.SysSample(cpu_percent=85.0, mem_percent=40.0,
                                      sampled_at=_time.monotonic() + 1)
        island._tick_sys()
        assert island._alert_severity.get(CPU) == isl.ALERT_WARN
    finally:
        island.close()


# ---------------------------------------------------------- 6.1sol #3：折叠不埋没故障
def test_full_fold_preserves_the_last_sampling_error(monkeypatch):
    """快照 error → 全折（收口袋、清快照）→ chip 告警与卡片原因不消失；恢复后清。"""
    import time as _time

    from pet import island_segments as isl
    from pet import sys_monitor as sm
    from pet.island_segments import CPU, MEM

    island = _island(monkeypatch, metrics=["cpu", "mem"])
    try:
        island.show()
        app.processEvents()
        monitor = island._sys_monitor
        monitor.sample = sm.SysSample(
            cpu_percent=None, mem_percent=None, sampled_at=_time.monotonic(),
            state=isl.STATE_ERROR, error_reason="psutil 读数失败")
        island._tick_sys()
        app.processEvents()
        # 全折（窄屏把 cpu+mem 全折进 +N，收口袋路径）：故障必须被保持
        screen = _FakeScreen(1400)
        monkeypatch.setattr(island_mod.DynamicIsland, "_current_screen",
                            lambda self: screen)
        plan = None
        for width in range(1400, 150, -2):
            screen._rect = QRect(0, 0, width, 768)
            island.refresh_from_config()
            plan = island._row_plan()
            if len(plan.folded) >= 2:
                break
        assert plan and len(plan.folded) >= 2, "找不到全折档"
        app.processEvents()
        assert island._sys_sample is None, "前提：收口袋后快照已清"
        segments = {seg.seg_id: seg for seg in island._compose_info_segments()}
        assert segments[CPU].state == isl.STATE_ERROR, (
            "被折前最后一拍是故障——段必须如实报 error，不是退回 sampling")
        # chip 的告警判定走当刻段列表：error 段按 crit 计（折叠不埋没故障）
        shown = island_layout_mod.apply_shrink(
            island._row_plan(), island._compose_info_segments(),
            primary_fm=island._metrics_for("primary"))
        chip = [seg for seg in shown if seg.kind == island_layout_mod.KIND_CHIP]
        assert chip and chip[0].severity == isl.ALERT_CRIT
        # 恢复（宽屏展开）后故障保持撤掉（新采样序列从 pending/-- 开始）
        screen._rect = QRect(0, 0, 1400, 768)
        island.refresh_from_config()
        app.processEvents()
        assert island._sys_error_hold == {}
        segments = {seg.seg_id: seg for seg in island._compose_info_segments()}
        assert segments[CPU].state == isl.STATE_SAMPLING
    finally:
        island.close()


# ---------------------------------------------------------- C2：隐藏/显示的采样生命周期
def test_hide_pauses_and_show_resumes_sys_sampling(monkeypatch):
    """hideEvent 停线程停表（保留订阅），showEvent 幂等恢复——隐藏即休眠的底座口径。"""
    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        monitor = island._sys_monitor
        assert monitor.started is True
        island.hide()
        app.processEvents()
        assert monitor.stops >= 1, "隐藏必须停采样线程"
        assert island._sys_timer.isActive() is False
        island.show()
        app.processEvents()
        assert monitor.started is True, "显示后采样必须恢复（订阅保留、幂等）"
    finally:
        island.close()
