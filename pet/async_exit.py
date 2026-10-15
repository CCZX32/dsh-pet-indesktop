# -*- coding: utf-8 -*-
"""Core 侧的非阻塞退出屏障：owner 作用域的后台工作 drain 门。

Ported from the DLC branch ``pet/async_exit.py``（逐字移植，只补本仓库口径的
docstring）。这里的"参与者"是**功能包自己的**后台工作（AI 包的在飞请求线程与
会话落盘）：它们各自保住自己的活，闸门既不杀进程也不 join 线程，只在
``QEvent.Type.Quit`` 被投到 ``QApplication`` 时把事件**吃掉**，直到每个参与者的
"活干完了"证据（``ready``）成立——事件循环因此始终可用，收口不会被一次
死等卡住。

三条硬口径：

* **失败即阻塞**：``prepare`` 或 ``ready`` 抛异常时记成阻塞原因并**不再重试**，
  绝不因为"读不出证据"就放行（放行等于用沉默代替结论）；
* **定时器归 Core**：:meth:`ApplicationExitGate.defer` 的 ``QTimer`` 父对象是
  闸门自己，不是可能已被销毁的功能包控件；
* **闸门按 app 单例**：挂在与进程同寿的 ``QApplication`` 上（``_owner_exit_gate``），
  功能包拿不到、也换不掉它。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class _Participant:
    owner: str
    prepare: Callable[[], object]
    ready: Callable[[], bool]


class ApplicationExitGate(QObject):
    """装在 ``QApplication`` 上的 Quit 事件过滤器；按 token 记参与者。"""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._participants: dict[str, _Participant] = {}
        self._prepared: set[str] = set()
        self._errors: dict[str, str] = {}
        self._waiting = False
        self._allow = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        app.installEventFilter(self)

    def register(self, owner: str, prepare: Callable[[], object], ready: Callable[[], bool]) -> str:
        """登记一个 owner 的后台工作；``ready`` 成立前退出被按住。"""
        token = uuid.uuid4().hex
        self._participants[token] = _Participant(owner, prepare, ready)
        if self._waiting:
            # 退出途中又有人登记 = 又有活要等：把已经放行的那一次收回来。
            self._allow = False
            self._timer.start()
        return token

    def unregister(self, token: str) -> None:
        self._participants.pop(token, None)
        self._prepared.discard(token)
        self._errors.pop(token, None)

    def defer(self, callback: Callable[[], object], milliseconds: int = 10) -> None:
        """在 Core 的定时器上跑一次回调（不归可能已销毁的窗口所有）。"""
        timer = QTimer(self)
        timer.setSingleShot(True)

        def run():
            try:
                callback()
            finally:
                timer.deleteLater()

        timer.timeout.connect(run)
        timer.start(milliseconds)

    @property
    def blockers(self) -> tuple[dict[str, str], ...]:
        """当下还挡着退出的 owner 与原因（UI 侧唯一读得到的那份证据）。"""
        return tuple({"owner": p.owner, "reason": self._errors.get(t, "background_drain_pending")} for t, p in self._participants.items())

    def eventFilter(self, watched, event):  # noqa: N802 - Qt 事件过滤器 ABI
        if watched is self._app and event.type() == QEvent.Type.Quit:
            if self._allow:
                # 上一次退出已经拿到全部证据：这一次放行，并复位。
                self._allow = False
                self._waiting = False
                self._timer.stop()
                return False
            if not self._participants:
                return False
            self._waiting = True
            self._advance()
            return True
        return False

    def _advance(self):
        for token, participant in list(self._participants.items()):
            if token not in self._prepared:
                self._prepared.add(token)
                try:
                    participant.prepare()
                except Exception:
                    self._errors[token] = "drain_prepare_failed"
            if token in self._errors:
                continue
            try:
                if participant.ready():
                    self.unregister(token)
            except Exception:
                self._errors[token] = "drain_evidence_failed"
        if not self._participants:
            self._timer.stop()
            self._allow = True
            QTimer.singleShot(0, self._app.quit)
        elif not self._timer.isActive():
            self._timer.start()


def application_exit_gate(app: QApplication | None = None) -> ApplicationExitGate:
    """进程级闸门（按 ``QApplication`` 单例）；没有 app 时显式报错。"""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("application_required_for_async_exit")
    gate = getattr(app, "_owner_exit_gate", None)
    if gate is None:
        gate = ApplicationExitGate(app)
        app._owner_exit_gate = gate
    return gate
