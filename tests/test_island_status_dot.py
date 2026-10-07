# -*- coding: utf-8 -*-
"""灵动岛状态点五态体系（P2 Slice E1）契约测试。

改造前：8px 实心绿 = 「宠物可见」单语义。新语义 = 形状+颜色**双通道**五态，
优先级 **错误 > 待确认 > 工作 > 完成瞬态 > 空闲/隐藏**（同刻只画一个图元）：

- 空闲（宠物可见、无事件）= 主题次色实心点（不再是绿）；
- 完成 = 绿实心点：``success`` 事件进入时亮起，**4s 后回落**（单次 QTimer，
  回落后定时器销毁——停表纪律）；
- 宠物隐藏 / DSH 离线 = 主题次色**空心环**（1.5px 描边）；
- 待确认/待回答 = accent **空心环**（读 ``dsh_state`` 的 waiting 锁存位：
  gated 口径在 ``pet/dsh_state.py``，本层不碰原始事件流）；
- 错误 = 红实心 ``#F2777A`` + 感叹矢量（QPainterPath 两笔，不用字符 glyph）；
- 工作 = accent 实心点。

硬约束：8px 尺寸不变；状态点变化只 ``update()``，**永不进宽度白名单键**
（它是纯绘制态）。断言口径：像素取真——``_content_cache()`` 是真 QPainter 画出来
的位图，不用桩画家；只留状态点时，内容层里除它之外没有任何图元，圆心/环上像素
的取色才有唯一解释。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF
from PySide6.QtGui import QColor, QImage, QPainterPath, QPainter
from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
from pet.config import Config
from pet.dynamic_island import DynamicIsland

# dark 主题下的期望色：中性 = 主题次色、工作/待确认 = 主题色（默认 blue）
_NEUTRAL = "#a0aabe"
_ACCENT = "#40b8ff"
_DONE_GREEN = "#50dc78"
_ERROR_RED = "#f2777a"

# 收敛器的全部状态 + ""（该通道从未被喂过，纯桌宠/未接 DSH 场景）
_DSH_STATES = ("", "offline", "idle", "thinking", "working",
               "waiting_approval", "waiting_question", "success", "error")


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _island(tmp_path: Path, **overrides) -> DynamicIsland:
    """只留状态点的岛：内容层除状态点外零图元（像素断言的前提）。"""
    cfg = Config(base=tmp_path)
    data = {
        "enabled": True, "show_icon": False, "show_name": False,
        "show_info": False, "show_status": True, "info_mode": "time",
        "style": "dark", "x": 400, "y": 300,
    }
    data.update(overrides)
    cfg.set("dynamic_island", data)
    return DynamicIsland(cfg)


def _dot_style(island: DynamicIsland) -> tuple[str, str]:
    """(形状, 颜色) —— 绘制层解析出的唯一结果（十六进制便于真值表比对）。"""
    shape, color = island._status_dot_style()
    return shape, color.name()


def _expected(state: str, visible: bool, done: bool) -> tuple[str, str]:
    """规格真值表（错误 > 待确认 > 工作 > 空闲/隐藏；完成是空闲点位的 4s 替身）。"""
    if state == "error":
        return "glyph", _ERROR_RED
    if state in ("waiting_approval", "waiting_question"):
        return "hollow", _ACCENT
    if state in ("working", "thinking"):
        return "solid", _ACCENT
    if state == "offline" or not visible:
        return "hollow", _NEUTRAL
    if done:
        return "solid", _DONE_GREEN
    return "solid", _NEUTRAL


def _content_image(island: DynamicIsland) -> QImage:
    return island._content_cache().toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _opaque_bbox(image: QImage, alpha_min: int = 40):
    """内容层里非空像素的外接框；只留状态点时它就是状态点本体。"""
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() >= alpha_min:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _near(color: QColor, expected: str, tol: int = 26) -> bool:
    want = QColor(expected)
    return (abs(color.red() - want.red()) <= tol
            and abs(color.green() - want.green()) <= tol
            and abs(color.blue() - want.blue()) <= tol)


def _dot_box(island: DynamicIsland):
    """(image, bbox)：状态点在内容层位图里的位置与尺寸。"""
    image = _content_image(island)
    bbox = _opaque_bbox(image)
    assert bbox is not None, "状态点没画出来（内容层全透明）"
    return image, bbox


def _center(bbox) -> tuple[int, int]:
    """状态点的几何中心（像素中心口径：外接框右下角算到 +1）。"""
    x0, y0, x1, y1 = bbox
    return (x0 + x1 + 1) // 2, (y0 + y1 + 1) // 2


# ---------------------------------------------------------------- 优先级真值表
def test_five_state_truth_table_all_combinations(tmp_path):
    """全组合真值表：8 态（+未喂态）× 宠物可见×2 × 完成瞬态×2。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        for state in _DSH_STATES:
            for visible in (True, False):
                for want_done in (True, False):
                    # 完成瞬态经公开路径进入：success 边沿亮绿；"工作"顶掉瞬态
                    island.set_dsh_state("working")
                    island.set_dsh_state("success")
                    if not want_done:
                        island.set_dsh_state("working")
                    island.set_dsh_state(state)
                    island.set_pet_visible(visible)
                    got = _dot_style(island)
                    want = _expected(state, visible, island._dot_done)
                    assert got == want, (
                        f"state={state!r} visible={visible} want_done={want_done} "
                        f"done={island._dot_done} → {got} != {want}")
        # success 边沿必须真亮绿（不是靠"读到 done=True"自我实现）
        island.set_pet_visible(True)
        island.set_dsh_state("working")
        island.set_dsh_state("success")
        assert _dot_style(island) == ("solid", _DONE_GREEN)
        # 更高优先级状态进来立即顶掉瞬态（不留过期绿点）
        island.set_dsh_state("error")
        assert island._dot_done is False
        assert _dot_style(island) == ("glyph", _ERROR_RED)
    finally:
        island.hide()
        island.deleteLater()


def test_error_outranks_everything(tmp_path):
    """错误不可自动恢复：宠物隐藏、完成瞬态、工作态都盖不过它。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("working")
        island.set_dsh_state("success")
        island.set_pet_visible(False)
        island.set_dsh_state("error")
        assert _dot_style(island) == ("glyph", _ERROR_RED)
        # 待确认 > 工作，且都是空心/实心两种形状通道
        island.set_dsh_state("waiting_approval")
        assert _dot_style(island) == ("hollow", _ACCENT)
        island.set_dsh_state("waiting_question")
        assert _dot_style(island) == ("hollow", _ACCENT)
        # 待确认也盖过隐藏：形状仍是 accent 环而不是中性环
        island.set_pet_visible(False)
        assert _dot_style(island) == ("hollow", _ACCENT)
    finally:
        island.hide()
        island.deleteLater()


def test_working_and_waiting_follow_accent_preset(tmp_path):
    """工作/待确认跟主题色走（换 accent 预设即换点色）。"""
    _qapp()
    island = _island(tmp_path, accent="pink")
    island.show()
    try:
        island.set_dsh_state("working")
        assert _dot_style(island) == ("solid", "#ff7ab8")
        island.set_dsh_state("waiting_approval")
        assert _dot_style(island) == ("hollow", "#ff7ab8")
    finally:
        island.hide()
        island.deleteLater()


# ------------------------------------------------------------------ 形状像素
def test_rendered_pixels_cover_all_five_states(tmp_path):
    """双通道形状断言（真像素）：实心 / 空心环 / 红实心+感叹。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        # 空闲：中性实心 + 尺寸 8px 不变
        island.set_dsh_state("idle")
        image, bbox = _dot_box(island)
        w, h = bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1
        assert w == 8 and h == 8, f"状态点尺寸必须仍是 8px（实测 {w}×{h}）"
        cx, cy = _center(bbox)
        assert _near(image.pixelColor(cx, cy), _NEUTRAL), "空闲 = 中性实心点"

        # 工作：accent 实心
        island.set_dsh_state("working")
        image, bbox = _dot_box(island)
        cx, cy = _center(bbox)
        assert _near(image.pixelColor(cx, cy), _ACCENT), "工作 = accent 实心点"

        # 完成：绿实心（4s 瞬态内）
        island.set_dsh_state("success")
        image, bbox = _dot_box(island)
        cx, cy = _center(bbox)
        assert _near(image.pixelColor(cx, cy), _DONE_GREEN), "完成 = 绿实心点"

        # 隐藏 / 离线：中性空心环 —— 圆心不填、环上有色
        for state in ("offline", "hidden"):
            if state == "hidden":
                island.set_dsh_state("idle")
                island.set_pet_visible(False)
            else:
                island.set_dsh_state("offline")
                island.set_pet_visible(True)
            image, bbox = _dot_box(island)
            x0, y0, x1, y1 = bbox
            cx, cy = _center(bbox)
            assert image.pixelColor(cx, cy).alpha() < 20, \
                f"{state}：空心环圆心必须透明（而是 {image.pixelColor(cx, cy).name()}）"
            assert _near(image.pixelColor(x0 + 1, cy), _NEUTRAL), \
                f"{state}：环体应是中性色 1.5px 描边"
            assert (x1 - x0 + 1, y1 - y0 + 1) == (8, 8), \
                "空心环与实心点同一 8px 足迹"

        # 待确认：accent 空心环（形状同"隐藏"、颜色通道不同）
        island.set_pet_visible(True)
        island.set_dsh_state("waiting_approval")
        image, bbox = _dot_box(island)
        x0, y0, x1, y1 = bbox
        cx, cy = _center(bbox)
        assert image.pixelColor(cx, cy).alpha() < 20, "待确认 = 空心环"
        assert _near(image.pixelColor(x0 + 1, cy), _ACCENT), "待确认环是 accent 色"

        # 错误：红实心 + 感叹（圆心竖列上有近白笔画）
        island.set_dsh_state("error")
        image, bbox = _dot_box(island)
        x0, y0, x1, y1 = bbox
        cx = _center(bbox)[0]
        # 盘内离开笔画中轴的像素必须是纯红（底色不是红就是没画红实心）
        assert _near(image.pixelColor(x0 + 2, y0 + 3), _ERROR_RED, tol=30), \
            "错误点底色必须是红 #F2777A"
        inks = [image.pixelColor(cx, y).blue() for y in range(y0, y1 + 1)]
        assert max(inks) > 170, "感叹矢量没画出来（中轴上没有近白笔画）"
    finally:
        island.hide()
        island.deleteLater()


def test_error_glyph_is_two_strokes(tmp_path):
    """感叹是两笔矢量路径（竖杠 + 圆点），不是字符 glyph。"""
    _qapp()
    path = island_mod._status_error_glyph_path(QRectF(0, 0, 8, 8))
    assert isinstance(path, QPainterPath)
    moves = [path.elementAt(i).type
             for i in range(path.elementCount())].count(
        QPainterPath.ElementType.MoveToElement)
    assert moves == 2, f"感叹必须两笔（实测 {moves} 笔）"

    # 渲染取证：圆心竖列上"近白"像素分成两段（杠 + 点），中间隔着红
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("error")
        image, bbox = _dot_box(island)
        x0, y0, x1, y1 = bbox
        cx = _center(bbox)[0]
        runs: list[list[int]] = []
        for y in range(y0, y1 + 1):
            if image.pixelColor(cx, y).blue() > 170:
                if runs and runs[-1][-1] == y - 1:
                    runs[-1].append(y)
                else:
                    runs.append([y])
        assert len(runs) == 2, f"近白笔画应分成两段（杠 / 点），实测 {runs}"
    finally:
        island.hide()
        island.deleteLater()


def test_glyph_path_is_drawn_once_only_for_error(tmp_path, monkeypatch):
    """绘制调用记录：感叹路径只在错误态被调一次，且拿到的是 8px 点矩形。"""
    _qapp()
    calls: list[QRectF] = []
    original = island_mod._status_error_glyph_path

    def spy(rect: QRectF) -> QPainterPath:
        calls.append(QRectF(rect))
        return original(rect)

    monkeypatch.setattr(island_mod, "_status_error_glyph_path", spy)
    island = _island(tmp_path)
    island.show()
    try:
        for state in ("idle", "working", "waiting_approval", "success", "offline"):
            island.set_dsh_state(state)
            island._content_cache()
        assert calls == [], "非错误态一次都不许调感叹路径"
        island.set_dsh_state("error")
        island._content_cache()
        assert len(calls) == 1, f"错误态应恰好画一次感叹（实测 {len(calls)}）"
        assert calls[0].width() == 8 and calls[0].height() == 8, \
            "感叹矢量按 8px 点矩形生成（尺寸不变）"
    finally:
        island.hide()
        island.deleteLater()


# --------------------------------------------------------------- 完成瞬态 4s
def test_done_flash_interval_is_4s_and_single_shot(tmp_path):
    """规格常量与定时器形态：4s、单次。"""
    _qapp()
    assert island_mod._DOT_DONE_MS == 4000
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("success")
        timer = island._dot_done_timer
        assert timer is not None and timer.isSingleShot()
        assert timer.interval() == 4000
        assert timer.isActive()
    finally:
        island.hide()
        island.deleteLater()


def test_done_flash_falls_back_and_destroys_timer(tmp_path, monkeypatch):
    """完成 → 4s 到点回落空闲，且定时器停表销毁（不真睡：压缩间隔 + 事件循环）。"""
    _qapp()
    monkeypatch.setattr(island_mod, "_DOT_DONE_MS", 40)
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("success")
        timer = island._dot_done_timer
        assert timer is not None
        deadline = time.monotonic() + 5.0
        while island._dot_done_timer is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
        assert island._dot_done_timer is None, "回落之后不得留下空转定时器"
        assert island._dot_done is False
        assert timer.isActive() is False
        # 停表纪律的强断言：不是"停下"而是对象真的从 Qt 对象树上被销毁
        from PySide6.QtCore import QCoreApplication, QEvent
        import shiboken6
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(timer), "回落后单次定时器必须销毁（deleteLater）"
        assert _dot_style(island) == ("solid", _NEUTRAL), "回落后是空闲中性实心点"
    finally:
        island.hide()
        island.deleteLater()


def test_done_flash_survives_idle_edge_but_dies_on_work(tmp_path):
    """瞬态语义：success 之后的 idle 边沿不打断绿点；工作/待确认/错误立即接管。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("success")
        island.set_dsh_state("idle")
        assert _dot_style(island) == ("solid", _DONE_GREEN)
        assert island._dot_done_timer is not None

        island.set_dsh_state("working")
        assert _dot_style(island) == ("solid", _ACCENT)
        assert island._dot_done_timer is None, "被更高优先级顶掉时必须停表销毁"
        assert island._dot_done is False
    finally:
        island.hide()
        island.deleteLater()


def test_hidden_island_never_arms_flash(tmp_path):
    """隐藏即休眠：不可见时不点表（隐藏态零定时器空转）。"""
    _qapp()
    island = _island(tmp_path)
    try:
        assert not island.isVisible()
        island.set_dsh_state("success")
        assert island._dot_done_timer is None
        assert island._dot_done is False
    finally:
        island.deleteLater()


def test_hide_stops_flash_timer(tmp_path):
    """闪完之前隐藏：定时器立刻停表销毁（下次显示不残留旧绿点）。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        island.set_dsh_state("success")
        assert island._dot_done_timer is not None
        island.hide()
        assert island._dot_done_timer is None
        assert island._dot_done is False
    finally:
        island.deleteLater()


# -------------------------------------------------------------- 宽度白名单
def test_state_change_rebuilds_content_but_never_touches_width(tmp_path):
    """状态点变化只重建内容层位图：宽度与行计划输入键一个字节都不动。"""
    _qapp()
    island = _island(tmp_path, show_info=True, info_mode="custom", custom_text="测试")
    island.show()
    try:
        width = island.width()
        plan_inputs = island._plan_inputs()
        for state in _DSH_STATES:
            island.set_dsh_state(state)
            assert island.width() == width, f"{state}：状态点改了胶囊宽度"
            assert island._plan_inputs() == plan_inputs, f"{state}：状态点进了宽度键"
        # 形状/颜色确实进了**内容**缓存键：实心→空心（同色）也必须换位图
        island.set_dsh_state("idle")
        solid = island._content_cache()
        island.set_dsh_state("offline")
        hollow = island._content_cache()
        assert hollow is not solid, "空心环与实心点同色也必须各自成键（形状改像素）"
        island.set_dsh_state("error")
        assert island._content_cache() is not hollow, "错误（红+感叹）必须重建位图"
    finally:
        island.hide()
        island.deleteLater()


# ------------------------------------------------------------------ 停靠细条
def test_docked_strip_draws_same_status_element(tmp_path):
    """停靠细条与胶囊同一图元语言：实心/空心在细条里同样成立。"""
    _qapp()
    island = _island(tmp_path, edge_dock=True, dock_edge="left")
    try:
        island.show()
        island._apply_position()
        assert island._mode == "docked"

        def render() -> QImage:
            target = QImage(island.size(), QImage.Format.Format_ARGB32)
            target.fill(QColor(0, 0, 0, 0))
            painter = QPainter(target)
            island._paint_strip(painter)
            painter.end()
            return target

        # 竖条：状态点在底部（几何沿用既有 8px 点）
        cx = island.width() // 2
        cy = island.height() - 8 - 8 + 4
        island.set_dsh_state("idle")
        assert _near(render().pixelColor(cx, cy), _NEUTRAL), "细条里空闲仍是中性实心"

        island.set_dsh_state("offline")
        strip = render()
        assert not _near(strip.pixelColor(cx, cy), _NEUTRAL, tol=10), \
            "细条里隐藏态必须是空心环（圆心不填）"
        assert _near(strip.pixelColor(cx - 3, cy), _NEUTRAL), "环体在细条里同样可见"

        island.set_dsh_state("waiting_approval")
        strip = render()
        assert _near(strip.pixelColor(cx - 3, cy), _ACCENT), "细条环跟 accent 走"
        island.set_dsh_state("error")
        # 杠与点之间的红色分隔行必须是底色红（形状通道在细条里同样成立）
        assert _near(render().pixelColor(cx, cy + 1), _ERROR_RED, tol=30)
    finally:
        island.hide()
        island.deleteLater()


# -------------------------------------------------------------- 旧通道兼容
def test_legacy_agent_active_adapter(tmp_path):
    """旧粗粒度活跃位（迁移期兼容层）：True → 工作实心；False 下降沿 → 完成瞬态。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        island.set_agent_active(True)
        assert _dot_style(island) == ("solid", _ACCENT)
        island.set_agent_active(False)
        assert _dot_style(island) == ("solid", _DONE_GREEN)
        assert island._dot_done_timer is not None
    finally:
        island.hide()
        island.deleteLater()


def test_legacy_and_dsh_channels_do_not_fight(tmp_path):
    """DSH 通道优先：旧活跃位留着 True 也不许顶掉错误/待确认。"""
    _qapp()
    island = _island(tmp_path)
    island.show()
    try:
        island.set_agent_active(True)
        island.set_dsh_state("error")
        assert _dot_style(island) == ("glyph", _ERROR_RED)
        island.set_dsh_state("waiting_approval")
        assert _dot_style(island) == ("hollow", _ACCENT)
        # 收敛态缺席（纯桌宠/未接 DSH）时旧活跃位补位：True → 工作实心
        island.set_dsh_state("")
        assert _dot_style(island) == ("solid", _ACCENT)
        # 下降沿 → 完成瞬态（旧通道唯一的"任务结束"边沿）
        island.set_agent_active(False)
        assert _dot_style(island) == ("solid", _DONE_GREEN)
    finally:
        island.hide()
        island.deleteLater()


def test_status_dot_off_config_draws_nothing(tmp_path):
    """show_status 关掉：状态点一个像素都不画（配置闸门不因五态改造松动）。"""
    _qapp()
    island = _island(tmp_path, show_status=False, show_info=True,
                     info_mode="custom", custom_text="测试")
    island.show()
    try:
        island.set_dsh_state("error")
        error_img = _content_image(island)
        island.set_dsh_state("working")
        assert _content_image(island) == error_img, \
            "关掉状态点后，状态变化不得再影响内容层"
        reds = [(x, y)
                for y in range(error_img.height())
                for x in range(error_img.width())
                if _near(error_img.pixelColor(x, y), _ERROR_RED, tol=20)]
        assert not reds, f"关掉状态点仍画出了错误红点：{reds[:1]}"
    finally:
        island.hide()
        island.deleteLater()


# ------------------------------------------------------- 事件源接线（全链）
def test_appshell_forwards_converged_state_verbatim(tmp_path):
    """接线契约：AppShell 把**收敛态原文**交给岛，不再压成活跃布尔。"""
    _qapp()
    import pet.app as app_mod
    from PySide6.QtWidgets import QWidget

    class _StubIsland(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.states: list[str] = []

        def set_dsh_state(self, state: str) -> None:
            self.states.append(state)

    class _StubShell:
        island = _StubIsland()

    shell = _StubShell()
    try:
        for from_state, to_state in (("", "idle"), ("idle", "thinking"),
                                     ("thinking", "waiting_approval"),
                                     ("waiting_approval", "success"),
                                     ("success", "error"), ("error", "offline")):
            app_mod.AppShell._on_dsh_state_changed(shell, from_state, to_state)
        assert shell.island.states == ["idle", "thinking", "waiting_approval",
                                       "success", "error", "offline"]
    finally:
        shell.island.deleteLater()


def test_dsh_converger_to_dot_end_to_end(tmp_path):
    """全链：真收敛器（pet/dsh_state.py）产出的状态 → 状态点五态。

    覆盖 gated 口径：``approval/asked`` 这类会话级审计信号**不**算待确认，
    带 requestId 的 ``cordis/request-run`` 才算。
    """
    _qapp()
    from pet.dsh_state import DshStateConverger

    converger = DshStateConverger()
    island = _island(tmp_path)
    island.show()

    def feed(record: dict) -> None:
        for item in converger.handle_record(record):
            if item[0] == "state":
                island.set_dsh_state(item[2])

    try:
        # 探活基线：在线且无活动 → 空闲中性实心点
        for item in converger.set_online(True):
            if item[0] == "state":
                island.set_dsh_state(item[2])
        assert _dot_style(island) == ("solid", _NEUTRAL)

        feed({"event": "tool/call"})
        assert _dot_style(island) == ("solid", _ACCENT), "工作 = accent 实心"
        feed({"event": "turn/end"})
        assert _dot_style(island) == ("solid", _DONE_GREEN), "完成 = 绿实心"

        # 会话级审计信号不锁存：点色不因它变成待确认空心环
        feed({"event": "approval/asked"})
        assert _dot_style(island) == ("solid", _DONE_GREEN)

        # 真 UI 级审批（桥只在这种形态下写：payload.requiresApproval 严格 True，
        # 带 requestId）→ accent 空心环
        feed({"event": "cordis/request-run", "requestId": "r-1",
              "payload": {"requiresApproval": True}})
        assert _dot_style(island) == ("hollow", _ACCENT)

        # 审批锁存期间的非阻塞事件被收敛器忽略（锁存语义，不是点的 bug）
        feed({"event": "llm_error"})
        assert _dot_style(island) == ("hollow", _ACCENT)
        feed({"event": "cordis/request-run-resolved", "requestId": "r-1"})
        assert _dot_style(island) == ("solid", _ACCENT), "解锁回工作"

        # 错误 → 红实心 + 感叹
        feed({"event": "llm_error"})
        assert _dot_style(island) == ("glyph", _ERROR_RED)

        # DSH 退出（探活掉线）→ 离线空心环
        for item in converger.set_online(False):
            if item[0] == "state":
                island.set_dsh_state(item[2])
        assert _dot_style(island) == ("hollow", _NEUTRAL)
    finally:
        island.hide()
        island.deleteLater()
