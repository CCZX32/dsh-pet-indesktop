# -*- coding: utf-8 -*-
"""「快速识屏」三个动作的编排（假 OCR / 假视觉通道 / 假采集闭环，offscreen）。

本片的产品面只有三件事：**采集 → 引擎 → 展示**。三条链路的差别全在中间那一步：

| 动作 | 中间那一步 | 隐私口径 |
|---|---|---|
| 提取文字 | 本地 OCR | 纯本地，绝不联网、不确认 |
| 翻译 | OCR（原文）+ 翻译引擎（译文，后续片） | 引擎缺席时如实说明，不留假结果 |
| 问答 | 确认 → vision/chat 通道 | **发云端前必须显式确认**，拒绝即丢图 |

另有两条横切纪律，逐条有用例：

- **物理隔离**：采集会话期间暂停主动识屏 watcher，会话结束只恢复到"此前配置
  允许的状态"——此前没在跑就不许被这次截图唤醒（对称，不是无条件 resume）；
- **一次一条**：已经在采集中时第二次触发被拒，不许叠第二层覆盖层。

纪律：offscreen，假宿主同步直调；唯一涉及真线程的用例走 ``QSignalSpy.wait``
（宽预算、事件同步），不 sleep 赌时序。
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from pet.screen_capture import actions as actions_mod  # noqa: E402
from pet.screen_capture.actions import (  # noqa: E402
    ACTION_ASK,
    ACTION_OCR,
    ACTION_TRANSLATE,
    ScreenCaptureActions,
    ScreenCapturePresenter,
)
from pet.screen_capture.result_panel import ScreenResult, ScreenResultPanel  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _image() -> QImage:
    img = QImage(8, 8, QImage.Format.Format_RGB888)
    img.fill(0x203040)
    return img


# ------------------------------------------------------------------ 假件


class _FakeController(QObject):
    """假采集闭环：按脚本把三条出口之一发出来（同步，钉死顺序）。"""

    captured = Signal(object, object)
    cancelled = Signal(str)
    failed = Signal(str)

    def __init__(self, *, mode: str = "captured") -> None:
        super().__init__()
        self.mode = mode
        self.starts = 0
        self.emit_on_start = True

    def start(self) -> bool:
        self.starts += 1
        if self.starts > 1:
            return False
        if self.emit_on_start:
            self.emit()
        return True

    def emit(self) -> None:
        image = _image()
        if self.mode == "captured":
            self.captured.emit(image, object())
        elif self.mode == "cancelled":
            self.cancelled.emit("esc")
        else:
            self.failed.emit("grab-empty")


class _FakeWatcher:
    """主动识屏 watcher 的替身：``resume()`` 与真实实现同义（= apply_config）。"""

    def __init__(self, *, running: bool = True, allowed: bool = True) -> None:
        self.running = running
        self.allowed = allowed          # 配置层面的"允许跑"
        self.pauses = 0
        self.resumes = 0
        self.apply_configs = 0

    def is_running(self) -> bool:
        return self.running

    def pause(self) -> None:
        self.pauses += 1
        self.running = False

    def resume(self) -> None:
        self.resumes += 1
        self.apply_config()

    def apply_config(self) -> None:
        self.apply_configs += 1
        self.running = self.allowed


class _RecordingPresenter:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.results: list[ScreenResult] = []

    def status(self, text: str) -> None:
        self.statuses.append(str(text))

    def show(self, result: ScreenResult):
        self.results.append(result)
        return None


class _FakeIsland(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.events: list[str] = []
        self.setVisible(True)

    def set_last_message(self, text: str) -> None:
        self.messages.append(str(text))

    def notify_event(self, kind: str = "generic") -> None:
        self.events.append(str(kind))


class _FakeHost:
    def __init__(self, *, island=None, watcher=None) -> None:
        self._island = island
        self.proactive_watcher = watcher
        self.bubbles: list[str] = []

    def screen_capture_island(self):
        return self._island

    def show_bubble(self, text, duration_ms: int = 3200, **_ignored) -> bool:
        self.bubbles.append(str(text))
        return True


def _make_actions(**kwargs) -> ScreenCaptureActions:
    controller = kwargs.pop("controller", None) or _FakeController()
    presenter = kwargs.pop("presenter", None) or _RecordingPresenter()
    host = kwargs.pop("host", None) or _FakeHost()
    kwargs.setdefault("run_inline", True)
    return ScreenCaptureActions(host, controller=controller, presenter=presenter, **kwargs)


# ------------------------------------------------------------------ 提取文字


def test_ocr_action_feeds_the_selection_to_the_local_engine_and_shows_it(monkeypatch):
    seen: list[object] = []
    presenter = _RecordingPresenter()

    def fake_ocr(image):
        seen.append(image)
        return "识别到的文字"

    action = _make_actions(ocr=fake_ocr, presenter=presenter)
    assert action.run(ACTION_OCR) is True

    assert len(seen) == 1 and isinstance(seen[0], QImage)
    assert len(presenter.results) == 1
    result = presenter.results[0]
    assert result.title == "截图提取文字"
    assert result.primary == "识别到的文字"
    assert result.secondary == ""
    assert result.force_panel is True          # 要能复制，必须上面板
    assert "本地" in result.status


def test_ocr_action_reports_an_honest_reason_when_no_engine_is_wired(monkeypatch):
    """引擎缺席不许冒充成功：如实说明 + 不编结果（切片 2 落地前就是这个态）。"""
    monkeypatch.setattr(actions_mod, "resolve_ocr_engine", lambda: None)
    presenter = _RecordingPresenter()
    action = _make_actions(ocr=None, presenter=presenter)

    assert action.run(ACTION_OCR) is True
    assert action.busy is False
    assert len(presenter.results) == 1
    result = presenter.results[0]
    assert result.primary == ""
    assert "尚未接入" in result.status


# ------------------------------------------------------------------ 翻译


def test_translate_action_keeps_the_source_and_says_the_engine_is_pending(monkeypatch):
    monkeypatch.setattr(actions_mod, "resolve_translator", lambda: None)
    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "Hello world", translator=None,
                           presenter=presenter)

    assert action.run(ACTION_TRANSLATE) is True
    result = presenter.results[0]
    assert result.title == "截图翻译"
    assert result.primary == "Hello world"      # 原文照旧拿得到
    assert result.secondary == ""               # 没有引擎就不摆假译文
    assert "后续片" in result.status


def test_translate_action_fills_both_bilingual_slots_with_an_engine():
    calls: list[tuple[object, str]] = []

    def fake_translate(image, source):
        calls.append((image, source))
        return "你好，世界"

    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "Hello world", translator=fake_translate,
                           presenter=presenter)

    assert action.run(ACTION_TRANSLATE) is True
    assert calls and calls[0][1] == "Hello world"
    result = presenter.results[0]
    assert result.primary == "Hello world"
    assert result.secondary == "你好，世界"


# ------------------------------------------------------------------ 问答


def test_ask_action_confirms_before_sending_pixels_to_the_cloud():
    order: list[str] = []
    seen: list[object] = []

    def fake_confirm(purpose: str) -> bool:
        order.append(f"confirm:{purpose}")
        return True

    def fake_ask(image):
        order.append("ask")
        seen.append(image)
        return "我看这块区域像是一段代码。"

    presenter = _RecordingPresenter()
    action = _make_actions(ask=fake_ask, confirm=fake_confirm, presenter=presenter)

    assert action.run(ACTION_ASK) is True
    assert order == ["confirm:ask", "ask"]       # 先确认、后发图，顺序是红线
    assert len(seen) == 1
    result = presenter.results[0]
    assert result.title == "截图问答"
    assert result.primary == "我看这块区域像是一段代码。"


def test_ask_action_declines_and_drops_the_selection_without_touching_the_channel():
    calls: list[str] = []
    presenter = _RecordingPresenter()
    action = _make_actions(
        ask=lambda _img: calls.append("ask") or "不该发生",
        confirm=lambda _purpose: False,
        presenter=presenter,
    )

    assert action.run(ACTION_ASK) is True
    assert calls == []                            # 拒绝 = 一个像素都没出去
    assert presenter.results == []
    assert any("取消" in text for text in presenter.statuses)
    assert action.busy is False


def test_ask_action_fails_closed_when_the_confirm_dialog_itself_breaks():
    """确认环节自己炸了（父窗没了/弹窗失败）＝ 不发：隐私门只认明确的"是"。"""
    calls: list[str] = []

    def broken_confirm(_purpose: str) -> bool:
        raise RuntimeError("弹窗失败")

    presenter = _RecordingPresenter()
    action = _make_actions(
        ask=lambda _img: calls.append("ask") or "不该发生",
        confirm=broken_confirm,
        presenter=presenter,
    )

    assert action.run(ACTION_ASK) is True
    assert calls == []
    assert presenter.results == []
    assert any("取消" in text for text in presenter.statuses)
    assert action.busy is False


# ------------------------------------------------------------------ 失败/取消


def test_cancel_restores_the_watcher_and_never_runs_the_engine():
    watcher = _FakeWatcher(running=True)
    ocr_calls: list[object] = []
    presenter = _RecordingPresenter()
    action = _make_actions(
        controller=_FakeController(mode="cancelled"),
        ocr=lambda img: ocr_calls.append(img) or "x",
        watcher=watcher,
        presenter=presenter,
    )

    assert action.run(ACTION_OCR) is True
    assert ocr_calls == []
    assert presenter.results == []
    assert any("取消" in text for text in presenter.statuses)
    assert watcher.pauses == 1 and watcher.resumes == 1
    assert action.busy is False


def test_capture_failure_is_reported_and_the_watcher_comes_back():
    watcher = _FakeWatcher(running=True)
    presenter = _RecordingPresenter()
    action = _make_actions(
        controller=_FakeController(mode="failed"),
        ocr=lambda _img: "x",
        watcher=watcher,
        presenter=presenter,
    )
    failures: list[str] = []
    action.failed.connect(failures.append)

    assert action.run(ACTION_OCR) is True
    assert failures == ["grab-empty"]
    assert presenter.results == []
    assert watcher.pauses == 1 and watcher.resumes == 1


def test_start_exception_still_restores_the_watcher():
    """启动就抛异常（宿主侧千奇百怪）时，物理隔离同样必须对称收口。"""
    class _RaisingController(_FakeController):
        def start(self) -> bool:
            self.starts += 1
            raise RuntimeError("宿主炸了")

    watcher = _FakeWatcher(running=True)
    presenter = _RecordingPresenter()
    action = _make_actions(controller=_RaisingController(), watcher=watcher,
                           presenter=presenter)

    assert action.run(ACTION_OCR) is False
    assert watcher.pauses == 1 and watcher.resumes == 1
    assert action.busy is False


def test_second_trigger_while_capturing_is_refused():
    controller = _FakeController()
    controller.emit_on_start = False      # 停在"采集中"
    action = _make_actions(controller=controller, ocr=lambda _img: "x")

    assert action.run(ACTION_OCR) is True
    assert action.busy is True
    assert action.run(ACTION_ASK) is False   # 不许叠第二层覆盖层
    assert controller.starts == 1

    controller.emit()                        # 收口后可以再来一次
    assert action.busy is False


# ------------------------------------------------------------------ watcher 对称


def test_watcher_pause_restore_is_symmetric_with_the_previous_state():
    """恢复走 ``resume()``（= 按配置重评估）；此前没在跑的绝不被这次截图唤醒。"""
    running = _FakeWatcher(running=True)
    action = _make_actions(watcher=running, ocr=lambda _img: "x")
    assert action.run(ACTION_OCR) is True
    assert running.pauses == 1
    assert running.resumes == 1
    assert running.apply_configs == 1     # 恢复 = 重评估配置，不是无条件重启
    assert running.running is True

    paused = _FakeWatcher(running=False, allowed=False)
    action = _make_actions(watcher=paused, ocr=lambda _img: "x")
    assert action.run(ACTION_OCR) is True
    assert paused.pauses == 1
    assert paused.resumes == 0
    assert paused.apply_configs == 0
    assert paused.running is False

    action = _make_actions(watcher=None, ocr=lambda _img: "x")
    assert action.run(ACTION_OCR) is True     # watcher 缺席也不许炸


def test_watcher_is_resolved_again_for_every_session(monkeypatch):
    """watcher 每次现取（m9）：壳的共享 watcher 会晚建/重建，构造期抓到的那一个
    可能早就不是当值的那一个——一次截图必须暂停**当时**的那个。

    宿主取用路径（``_host_watcher``）返回的是哪个对象由宿主决定，这里换掉它来模拟
    "第一轮之后 watcher 被换掉了"。
    """
    first = _FakeWatcher(running=True)
    second = _FakeWatcher(running=True)
    current = {"watcher": first}
    monkeypatch.setattr(actions_mod, "_host_watcher", lambda _host: current["watcher"])

    controller = _FakeController()          # 假闭环只允许"进入"一次（模拟真实的一次触发）
    action = _make_actions(controller=controller, watcher=None, ocr=lambda _img: "x")
    assert action.run(ACTION_OCR) is True
    assert (first.pauses, first.resumes) == (1, 1)

    current["watcher"] = second             # 第二轮之前换了当值的 watcher
    controller.starts = 0                   # 上一轮已收口，假件按"允许下一轮"复位
    assert action.run(ACTION_OCR) is True

    assert (second.pauses, second.resumes) == (1, 1)
    assert (first.pauses, first.resumes) == (1, 1), "换掉之后不该再动上一个"


def test_watcher_gate_resumes_the_instance_it_actually_paused():
    """恢复必须落在被暂停的那一个实例上：现取到别的对象就恢复别的对象＝
    我们暂停的那个永远醒不过来。"""
    paused_one = _FakeWatcher(running=True)
    swapped_in = _FakeWatcher(running=True)
    current = {"watcher": paused_one}
    gate = actions_mod._WatcherGate(lambda: current["watcher"])

    gate.pause()
    current["watcher"] = swapped_in      # 会话进行中被换掉
    gate.restore()

    assert (paused_one.pauses, paused_one.resumes) == (1, 1)
    assert (swapped_in.pauses, swapped_in.resumes) == (0, 0)


def test_watcher_gate_tolerates_a_broken_provider():
    """取用回调本身出错＝这条面不可用，不是截图失败。"""
    def _boom():
        raise RuntimeError("no watcher today")

    gate = actions_mod._WatcherGate(_boom)
    gate.pause()
    gate.restore()          # 不抛即通过

    assert actions_mod._WatcherGate(None)._current() is None


# ------------------------------------------------------------------ 线程纪律


def test_blocking_stages_run_off_the_gui_thread_and_report_back_on_it():
    main_thread = threading.current_thread().name
    worker_names: list[str] = []
    done = threading.Event()

    def fake_ask(image):
        worker_names.append(threading.current_thread().name)
        return "答"

    presenter = _RecordingPresenter()
    action = _make_actions(ask=fake_ask, confirm=lambda _p: True, presenter=presenter,
                           run_inline=False)
    action.result_ready.connect(lambda _result: done.set())

    assert action.run(ACTION_ASK) is True
    # 事件同步 + 宽预算（不用 QtTest 的 wait：它在"信号已先到"时返回 False，
    # 那是个会随线程调度翻面的假红）。CI runner 是新开机的慢机器，预算给足。
    deadline = time.monotonic() + 10.0
    while not done.is_set() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert done.is_set(), "后台线程的结果没有回到 GUI 线程"
    assert action.busy is False
    assert worker_names and worker_names[0] != main_thread
    assert presenter.results[0].primary == "答"


def test_empty_result_and_recognition_failure_say_different_things():
    """「没认到字」与「识别失败」是两件事，文案不许混：

    - 没认到字 = 引擎正常跑完、图里就是没文字（用户该去换一张图）；
    - 识别失败 = 引擎自己出了问题（缺模型/依赖/推理异常），**不知道**图里有没有
      文字。这时候说"没有识别到文字"就是撒谎，用户会一直换图试。
    """
    empty_presenter = _RecordingPresenter()
    empty_action = _make_actions(ocr=lambda _img: "   ", presenter=empty_presenter)
    empty_failures: list[str] = []
    empty_action.failed.connect(empty_failures.append)

    assert empty_action.run(ACTION_OCR) is True

    empty_status = empty_presenter.results[-1].status
    assert "没有识别到文字" in empty_status
    assert empty_failures == [], "没认到字不是失败，不许报错"

    def broken(_img):
        raise RuntimeError("缺少本地 OCR 模型文件 PP-OCRv6_det_small.onnx")

    broken_presenter = _RecordingPresenter()
    broken_action = _make_actions(ocr=broken, presenter=broken_presenter)
    broken_failures: list[str] = []
    broken_action.failed.connect(broken_failures.append)

    assert broken_action.run(ACTION_OCR) is True

    broken_status = broken_presenter.statuses[-1]
    assert "识别失败" in broken_status
    assert "没有识别到文字" not in broken_status, "引擎坏了却说「图里没字」＝撒谎"
    assert "PP-OCRv6_det_small.onnx" in broken_status, "失败必须带上人话原因"
    assert broken_failures and "PP-OCRv6_det_small.onnx" in broken_failures[0]
    assert empty_status != broken_status


# ------------------------------------------------------------ 用完就丢（归还）


def _recording_release():
    """假释放入口：记录"被调了几次"，并支持验证"确实发生在收口之后"。"""
    calls: list[float] = []

    def release() -> bool:
        calls.append(time.monotonic())
        return True

    release.calls = calls          # type: ignore[attr-defined]
    return release


def test_ocr_action_hands_the_local_engine_back_when_the_session_ends():
    """交付后必须归还引擎：这是「用完就丢」在编排层的唯一落点。"""
    release = _recording_release()
    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "识别到的文字", release=release,
                           presenter=presenter)

    assert action.run(ACTION_OCR) is True

    assert len(release.calls) == 1, "一次会话收口恰好归还一次"
    assert presenter.results, "归还发生在收口里，但结果照样要交付"
    assert action.busy is False


def test_cancelled_and_failed_sessions_also_hand_the_engine_back():
    """取消/失败同样是会话结束：任何出口都不许把引擎留在原地。

    这两条出口上引擎通常还没被加载（no-op），但"调用点存在"必须被钉住——
    漏掉它就会表现为"某条失败路径之后引擎常驻到下次重启"。
    """
    for mode in ("cancelled", "failed"):
        release = _recording_release()
        controller = _FakeController(mode=mode)
        action = _make_actions(controller=controller, release=release,
                              presenter=_RecordingPresenter())

        assert action.run(ACTION_OCR) is True
        assert action.busy is False
        assert len(release.calls) == 1, f"{mode} 出口没有归还引擎"


def test_release_failure_never_breaks_a_delivered_result():
    """归还失败只是日志：图已经拿到了，不该反过来变成用户可见的错误。"""
    def boom() -> bool:
        raise RuntimeError("释放炸了")

    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "识别到的文字", release=boom,
                           presenter=presenter)

    assert action.run(ACTION_OCR) is True

    assert presenter.results[0].primary == "识别到的文字"


def test_release_does_not_block_the_gui_thread_or_the_result():
    """真线程口径：归还跑在后台（实测 unload 约 48 ms，压在浮层弹出那一刻）。"""
    main_thread = threading.current_thread().name
    worker_names: list[str] = []
    done = threading.Event()

    def release() -> bool:
        worker_names.append(threading.current_thread().name)
        done.set()
        return True

    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "识别到的文字", release=release,
                           presenter=presenter, run_inline=False)
    action.result_ready.connect(lambda _result: None)

    assert action.run(ACTION_OCR) is True

    deadline = time.monotonic() + 10.0
    while not done.is_set() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert done.is_set(), "归还没有在预算内发生"
    assert worker_names[0] != main_thread, "归还跑在了 GUI 线程上"
    assert presenter.results[0].primary == "识别到的文字"


def test_release_seam_matches_the_engine_module_contract():
    """跨切片契约：``ocr.py`` 必须真的有编排层要调的那个释放入口。"""
    engine = pytest.importorskip("pet.screen_capture.ocr")
    assert callable(getattr(engine, actions_mod.OCR_RELEASE_ENTRY, None))
    assert callable(actions_mod.resolve_ocr_release())


def test_missing_release_entry_is_tolerated(monkeypatch):
    """旧版引擎没有释放入口时：不还而已，识别链路照常交付。"""
    monkeypatch.setattr(actions_mod, "resolve_ocr_release", lambda: None)
    presenter = _RecordingPresenter()
    action = _make_actions(ocr=lambda _img: "识别到的文字", presenter=presenter)

    assert action.run(ACTION_OCR) is True

    assert presenter.results[0].primary == "识别到的文字"


# ------------------------------------------------------------------ seam 契约


def test_ocr_seam_matches_the_engine_module_contract():
    """同包 OCR 引擎（切片 2）的模块级入口必须与 ``actions`` 的 seam 常量对得上。

    这是**跨切片契约**的机器化：入口改名/挪位在这里红，而不是等用户点了菜单
    才发现"本地识别没接线"。引擎模块不在时跳过（本片可以独立交付）。
    """
    engine = pytest.importorskip("pet.screen_capture.ocr")
    assert callable(getattr(engine, actions_mod.OCR_ENTRY, None))
    assert actions_mod.ocr_engine_available() is True


# ------------------------------------------------------------------ 展示落点


def test_presenter_drives_the_real_dynamic_island(tmp_path):
    """真实灵动岛（offscreen）：状态与短结果确实进了岛的「最近消息」面。

    岛没有公开的消息读取入口——``_last_message`` 就是卡片那一行渲染的那一份，
    所以这里读它（不是断言私有调用顺序，而是断言用户看得见的那段文案）。
    """
    from pet.config import Config
    from pet.dynamic_island import DynamicIsland

    cfg = Config(tmp_path)
    data = dict(cfg.get("dynamic_island", {}) or {})
    data.update({"style": "dark", "show_info": True})
    cfg.set("dynamic_island", data)
    island = DynamicIsland(cfg)
    island.show()   # 离屏：只让"可见"判据成立，屏幕上不会出现任何东西
    presenter = ScreenCapturePresenter(island=island, panel_factory=ScreenResultPanel)

    presenter.status("正在本地识别文字…")
    assert island._last_message == "正在本地识别文字…"

    panel = presenter.show(ScreenResult(title="截图提取文字", primary="字" * 80))
    assert isinstance(panel, ScreenResultPanel)
    assert island._last_message.endswith("…")

    panel.close_panel()
    island.close()
    island.deleteLater()


def test_presenter_routes_status_and_short_results_to_the_island():
    island = _FakeIsland()
    presenter = ScreenCapturePresenter(island=island, bubble=None,
                                       panel_factory=ScreenResultPanel)

    presenter.status("正在识别…")
    assert island.messages[-1] == "正在识别…"
    assert island.events[-1] == "generic"

    panel = presenter.show(ScreenResult(title="截图提取文字", primary="确定"))
    assert panel is None                        # 短结果不上面板
    assert island.messages[-1] == "确定"
    assert island.events[-1] == "reply"


def test_presenter_sends_long_results_to_the_panel_beside_the_island():
    island = _FakeIsland()
    presenter = ScreenCapturePresenter(island=island, panel_factory=ScreenResultPanel)

    panel = presenter.show(ScreenResult(title="截图提取文字", primary="字" * 120))
    assert isinstance(panel, ScreenResultPanel)
    assert panel.isVisible() is True
    assert panel.primary_text() == "字" * 120
    # 岛的短文案是限长摘要，不是全文
    assert island.messages[-1].endswith("…")
    assert len(island.messages[-1]) <= actions_mod.SHORT_RESULT_LIMIT + 1
    panel.close_panel()


def test_presenter_boundary_at_the_island_line_limit():
    """边界值：正好等于上限的短结果不上岛外，超一个字就必须开面板。"""
    island = _FakeIsland()
    presenter = ScreenCapturePresenter(island=island, panel_factory=ScreenResultPanel)

    at_limit = "字" * actions_mod.SHORT_RESULT_LIMIT
    assert presenter.show(ScreenResult(title="截图提取文字", primary=at_limit)) is None
    assert island.messages[-1] == at_limit

    over_limit = "字" * (actions_mod.SHORT_RESULT_LIMIT + 1)
    panel = presenter.show(ScreenResult(title="截图提取文字", primary=over_limit))
    assert isinstance(panel, ScreenResultPanel)
    assert panel.primary_text() == over_limit
    panel.close_panel()


def test_presenter_falls_back_to_the_pet_bubble_without_an_island():
    host = _FakeHost(island=None)
    presenter = ScreenCapturePresenter(island=None, bubble=host.show_bubble,
                                       panel_factory=ScreenResultPanel)

    presenter.status("正在识别…")
    assert host.bubbles[-1] == "正在识别…"

    panel = presenter.show(ScreenResult(title="截图问答", primary="答" * 100))
    assert isinstance(panel, ScreenResultPanel)
    assert host.bubbles[-1].startswith("答")
    panel.close_panel()


# ------------------------------------------------- 结果浮层主题（交叉审查 m2）


def test_presenter_hands_an_explicit_theme_to_the_panel_factory():
    """``style`` 必须真的传下去：不传等于浅色宿主上永远弹深色浮层。"""
    seen: dict = {}

    def factory(parent, **kwargs):
        seen.update(kwargs)
        return None      # 造不出来也不影响这条断言：本用例只看"传了什么"

    presenter = ScreenCapturePresenter(island=None, panel_factory=factory, style="light")
    presenter.show(ScreenResult(title="截图提取文字", primary="字" * 80, force_panel=True))

    assert seen == {"style": "light"}


def test_presenter_leaves_the_theme_to_the_panel_when_the_host_has_none():
    """没主题（跟随系统/读不到配置）＝不传 style，由面板按宿主调色板现判。"""
    seen: list = []

    def factory(parent, **kwargs):
        seen.append(kwargs)
        return None

    presenter = ScreenCapturePresenter(island=None, panel_factory=factory, style=None)
    presenter.show(ScreenResult(title="截图提取文字", primary="字" * 80, force_panel=True))

    assert seen == [{}]


def test_host_theme_comes_from_the_same_key_the_menus_use():
    """真值只有一份：主配置的 ``context_menu_appearance.theme``（菜单渲染用的那个键）。

    ``system``/缺失一律 ``None``——那表示"跟着宿主调色板现判"，不由这里猜。
    """
    host = _FakeHost()
    host.cfg = {"context_menu_appearance": {"theme": "light"}}
    assert actions_mod._host_theme(host) == "light"

    host.cfg = {"context_menu_appearance": {"theme": "dark"}}
    assert actions_mod._host_theme(host) == "dark"

    host.cfg = {"context_menu_appearance": {"theme": "system"}}
    assert actions_mod._host_theme(host) is None

    host.cfg = {"context_menu_appearance": "not a mapping"}
    assert actions_mod._host_theme(host) is None

    assert actions_mod._host_theme(object()) is None


def test_default_presenter_builds_a_light_panel_for_a_light_host():
    """端到端：浅色宿主 → 默认编排件造出来的浮层真的是浅色那份。"""
    host = _FakeHost()
    host.cfg = {"context_menu_appearance": {"theme": "light"}}
    action = ScreenCaptureActions(host, controller=_FakeController(), run_inline=True)

    panel = action._presenter.panel()   # 私有入口：这里要验的正是"默认装配"这一层

    assert isinstance(panel, ScreenResultPanel)
    assert panel.style == "light"
    panel.close_panel()
