# -*- coding: utf-8 -*-
"""Core 侧退出闸门（``pet/async_exit.py``）：owner 作用域的后台工作 drain 屏障。

蓝本 = DLC 分支的 ``tests/test_async_exit.py``。这里是**真 Qt 事件循环**的用例：
闸门本身是一个装在 ``QApplication`` 上的事件过滤器，所以"按住退出"这件事只有
把真 ``QEvent.Type.Quit`` 投进真 app 才算验过（直接调 ``eventFilter`` 只能验
一半——过滤器有没有被装上、装上之后拦不拦得住，都在 ``sendEvent`` 里）。

参与者用假货（``prepare``/``ready`` 两个回调），因为闸门对它们的约定就是这两
个可调用；真参与者是包里的 ``AiRuntime``（其 overlay/线程语义在
``test_ai_package_*`` 里另测）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication

from pet.async_exit import ApplicationExitGate, application_exit_gate

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def gate(qapp):
    """同一进程共享的闸门；用例收口时保证不留参与者。

    留一个永远不 ready 的参与者会让**后面所有用例**的退出事件都被按住——
    这是共享 ``QApplication`` 下最容易踩的一次性污染，所以收口是强制的。
    """
    instance = application_exit_gate(qapp)
    yield instance
    for token in list(instance._participants):
        instance.unregister(token)
    # 放行时闸门会排一次 ``QTimer.singleShot(0, app.quit)``；在这里清干净，
    # 免得它落到**后面某个正在跑 QEventLoop 的用例**里把那个循环提前结束。
    for _ in range(3):
        qapp.processEvents()


def _filtered(app, gate) -> bool:
    """闸门对这一枚 Quit 的判断：True = 事件被消费（退出被按住）。

    **不能**拿 ``QApplication.sendEvent`` 的返回值当判据：``QCoreApplication::notify``
    在"被事件过滤器吃掉"与"交给接收者处理"两种情况下都返回 ``true``，所以它区分不出
    拦没拦住。Qt 事件过滤器的公开契约就是 ``QObject.eventFilter`` 的返回值
    （``true`` = 事件被消费，不再往下走），这里问的正是这一条。
    """
    return bool(gate.eventFilter(app, QEvent(QEvent.Type.Quit)))


def _pump(app, predicate, *, timeout: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


# --------------------------------------------------------------- 闸门开合


def test_a_quit_passes_through_when_nothing_is_registered(qapp, gate):
    assert gate.blockers == ()
    assert _filtered(qapp, gate) is False


def test_the_gate_is_wired_into_the_real_event_dispatch(qapp, gate):
    """闸门真的装在了 app 上：一枚真 ``Quit`` 经 Qt 分派就能让闸门动起来。

    这一步单独验，是因为"过滤器返回 true"只说明判断对，不说明它**被装上**。
    真投递一次的可见后果是参与者的 ``prepare`` 被调到（回调是测试给的，
    ``blockers`` 也是公开面），所以这里用真分派 + 这两个可观察量。
    """
    prepares: list[str] = []
    gate.register("official.ai-chat", lambda: prepares.append("prepare"), lambda: False)
    QApplication.sendEvent(qapp, QEvent(QEvent.Type.Quit))
    assert prepares == ["prepare"]
    assert gate.blockers == ({"owner": "official.ai-chat", "reason": "background_drain_pending"},)


def test_pending_work_holds_the_quit(qapp, gate):
    prepares: list[str] = []
    gate.register("official.ai-chat", lambda: prepares.append("prepare"), lambda: False)
    assert _filtered(qapp, gate) is True  # 事件被过滤器吃掉，app 收不到 Quit
    assert prepares == ["prepare"]
    assert gate.blockers == ({"owner": "official.ai-chat", "reason": "background_drain_pending"},)
    assert _filtered(qapp, gate) is True  # prepare 只跑一次，闸门依旧关着
    assert prepares == ["prepare"]


def test_ready_evidence_releases_the_gate(qapp, gate):
    """两段语义：**收齐证据的那一枚被吃掉**，下一枚才真的放行。

    ``_advance`` 收尾时会排一次 ``QTimer.singleShot(0, app.quit)``（闸门持有的
    Core 定时器）把退出重新提一次——所以"按住"不会永远按住，也不会在同一枚事件上
    既拦又放。
    """
    state = {"ready": False}
    gate.register("official.ai-chat", lambda: None, lambda: state["ready"])
    assert _filtered(qapp, gate) is True  # 还没干完 → 按住
    state["ready"] = True
    assert _filtered(qapp, gate) is True  # 这一枚用来收证据，仍被吃掉
    assert gate.blockers == ()
    assert _filtered(qapp, gate) is False  # 下一枚真的放行


def test_release_is_acknowledged_so_the_next_quit_is_not_swallowed_twice(qapp, gate):
    gate.register("official.ai-chat", lambda: None, lambda: True)
    assert _filtered(qapp, gate) is True  # 第一枚：收证据 + 吃掉
    assert _filtered(qapp, gate) is False  # 第二枚：放行（放行只认一次）
    assert _filtered(qapp, gate) is False  # 之后再投：没有参与者，正常放行


def test_unregister_stops_blocking(qapp, gate):
    token = gate.register("official.ai-chat", lambda: None, lambda: False)
    assert _filtered(qapp, gate) is True
    gate.unregister(token)
    assert gate.blockers == ()
    assert _filtered(qapp, gate) is False


def test_unregister_is_idempotent(qapp, gate):
    token = gate.register("official.ai-chat", lambda: None, lambda: False)
    gate.unregister(token)
    gate.unregister(token)
    assert gate.blockers == ()

    # 取一个不存在的 token 也不炸（退出收口可能重复调）。
    gate.unregister("不存在的 token")


def test_a_participant_registered_mid_quit_recloses_the_gate(qapp, gate):
    """退出途中又有人注册 = 又有活要等，已经放行的那一次被收回（上游同口径）。"""
    gate.register("official.ai-chat", lambda: None, lambda: True)
    assert _filtered(qapp, gate) is True  # 收齐证据（已排了一次重提退出）
    gate.register("official.ai-chat", lambda: None, lambda: False)
    assert _filtered(qapp, gate) is True  # 闸门重新关上
    assert gate.blockers[0]["owner"] == "official.ai-chat"


# --------------------------------------------------------------- 失败隔离


def test_a_failing_prepare_is_reported_without_waiting_forever(qapp, gate):
    """prepare 抛异常：记成阻塞原因，不再重试，也不把闸门放开。

    放开是错的——"准备失败"不等于"活干完了"；正确行为是留着参与者让用户看到
    阻塞原因（``blockers`` 是 UI 侧唯一读得到的那份）。
    """
    calls: list[str] = []

    def prepare():
        calls.append("prepare")
        raise RuntimeError("drain 准备失败")

    gate.register("official.ai-chat", prepare, lambda: False)
    assert _filtered(qapp, gate) is True
    assert calls == ["prepare"]
    assert gate.blockers == ({"owner": "official.ai-chat", "reason": "drain_prepare_failed"},)
    assert _filtered(qapp, gate) is True
    assert calls == ["prepare"]  # 失败后不再重试 prepare


def test_failing_ready_evidence_is_reported(qapp, gate):
    def ready():
        raise RuntimeError("证据读不出来")

    gate.register("official.ai-chat", lambda: None, ready)
    assert _filtered(qapp, gate) is True
    assert gate.blockers == ({"owner": "official.ai-chat", "reason": "drain_evidence_failed"},)


# --------------------------------------------------------------- Core 定时器


def test_defer_runs_the_callback_once_on_the_core_timer(qapp, gate):
    seen: list[str] = []
    gate.defer(lambda: seen.append("fired"), 10)
    assert seen == []  # 不同步执行：回调属于事件循环
    assert _pump(qapp, lambda: bool(seen))
    assert seen == ["fired"]
    _pump(qapp, lambda: False, timeout=0.05)
    assert seen == ["fired"]  # 单次


def test_deferred_callback_errors_do_not_escape_the_event_loop(qapp, gate):
    """回调抛异常不该把事件循环带走（定时器归属 Core，不归属可能已销毁的窗口）。"""
    import time

    def boom():
        raise RuntimeError("窗口没了")

    gate.defer(boom, 5)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            qapp.processEvents()
        except RuntimeError as exc:  # pragma: no cover - 失败即用例红
            pytest.fail(f"defer 的回调异常漏进事件循环: {exc!r}")
        time.sleep(0.005)


def test_deferred_timers_are_owned_by_the_gate_itself(qapp, gate):
    """定时器的父对象必须是闸门：窗口销毁不得带走 Core 的收口定时器。"""
    gate.defer(lambda: None, 5)
    timers = [child for child in gate.children() if isinstance(child, QTimer)]
    assert timers, "defer 的定时器没有挂在闸门上"


# --------------------------------------------------------------- 单例边界


def test_the_gate_is_one_per_application(qapp):
    assert application_exit_gate(qapp) is application_exit_gate(qapp)
    assert isinstance(application_exit_gate(qapp), ApplicationExitGate)


def test_the_gate_cannot_be_created_without_an_application():
    """新进程里没有 QApplication：必须显式报错，不是返回一个半成品闸门。

    在**新进程**里验（本进程早已有 QApplication，断言等于没验）。
    """
    code = (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from pet.async_exit import application_exit_gate\n"
        "try:\n"
        "    application_exit_gate(None)\n"
        "except RuntimeError as exc:\n"
        "    print('RUNTIME_ERROR', exc)\n"
        "else:\n"
        "    print('NO_ERROR')\n"
    ) % str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("RUNTIME_ERROR"), result.stdout
