"""截图提问的 Core 实现：``ScreenAskPort`` 的唯一实现者。

每个 ``(owner, pet_slot)`` 一个窗口；窗口关闭只隐藏、不销毁历史（同聊天窗）。
模型调用仍由 mod 在回调里完成——Core 不依赖具体业务域，也不 import 网络层。

线程纪律：``submitted`` 在 GUI 线程到达，回调在**后台守护线程**执行（可能阻塞
几十秒），结果经 Qt 信号排队回 GUI 线程再碰控件。worker 只接触纯数据
（question / png bytes / history 副本），绝不碰窗口对象。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ...contracts.screen import ScreenCapture
from .ask_window import DEFAULT_QUESTION, ScreenAskWindow

logger = logging.getLogger("petcore.ui.screen")

AskCallback = Callable[[str, bytes, list[dict], int], str]


@dataclass
class _AskState:
    owner: str
    slot: int
    window: ScreenAskWindow
    capture: ScreenCapture | None = None
    history: list[dict] = field(default_factory=list)
    pending_question: str = ""
    generation: int = 0


class ScreenAskController(QObject):
    """窗口 + 历史 + 后台发送；对外只暴露 ``ScreenAskPort`` 的语义。"""

    # (owner, pet_slot, generation, 文本)
    _reply_ready = Signal(str, int, int, str)
    _reply_failed = Signal(str, int, int, str)

    def __init__(self, host, root: Path | str | None = None) -> None:
        super().__init__(host if isinstance(host, QObject) else None)
        self.host = host
        self.root = Path(root) if root is not None else None
        self._states: dict[tuple[str, int], _AskState] = {}
        self._ask_registry: dict[str, AskCallback] = {}
        self._reply_ready.connect(self._apply_reply)
        self._reply_failed.connect(self._apply_failure)

    # ---------------------------------------------------------------- 公共状态

    def window_for(self, owner: str, pet_slot: int | None = None) -> ScreenAskWindow | None:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        return state.window if state is not None else None

    # ---------------------------------------------------------------- ScreenAskPort

    def open(
        self,
        owner: str,
        capture: ScreenCapture,
        *,
        pet_slot: int | None = None,
        title: str = "",
    ) -> bool:
        state = self._ensure(owner, pet_slot)
        # 新采集 = 新会话：旧历史与在途回合一律作废（窗口也由 start() 清空）。
        state.generation += 1
        state.capture = capture
        state.history.clear()
        state.pending_question = ""
        state.window.start(capture, title)
        return True

    def close(self, owner: str, *, pet_slot: int | None = None) -> None:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        if state is not None:
            state.window.hide()

    def is_open(self, owner: str, *, pet_slot: int | None = None) -> bool:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        return bool(state is not None and state.window.isVisible())

    def history(self, owner: str, *, pet_slot: int | None = None) -> list[dict]:
        """已完成的 ``{role, content}`` 回合副本（不含在途问题与图片）。"""
        state = self._states.get((str(owner), self._slot(pet_slot)))
        if state is None:
            return []
        return [dict(item) for item in state.history]

    def on_ask(self, owner: str, callback: AskCallback) -> Callable[[], None]:
        owner = str(owner)
        self._ask_registry[owner] = callback

        def unsubscribe() -> None:
            if self._ask_registry.get(owner) is callback:
                self._ask_registry.pop(owner, None)

        return unsubscribe

    # ---------------------------------------------------------------- 内部

    def _slot(self, slot: int | None) -> int:
        if slot is None:
            return 0
        try:
            return max(0, int(slot))
        except (TypeError, ValueError):
            return 0

    def _ensure(self, owner: str, pet_slot: int | None) -> _AskState:
        owner = str(owner)
        slot = self._slot(pet_slot)
        key = (owner, slot)
        state = self._states.get(key)
        if state is not None:
            return state
        window = ScreenAskWindow()
        window.submitted.connect(lambda text, k=key: self._on_submitted(k, text))
        state = _AskState(owner=owner, slot=slot, window=window)
        self._states[key] = state
        return state

    def _on_submitted(self, key: tuple[str, int], question: str) -> None:
        state = self._states.get(key)
        if state is None or state.capture is None:
            return
        if state.window.is_waiting():
            return
        text = str(question or "").strip() or DEFAULT_QUESTION
        state.window.append_user(text)
        callback = self._ask_registry.get(state.owner)
        if callback is None:
            # 没有扩展接管：立刻给可见错误，绝不停在「正在看图…」。
            state.window.end_waiting("没有扩展接管截图提问")
            return
        state.generation += 1
        generation = state.generation
        state.pending_question = text
        history = [dict(item) for item in state.history]
        png = bytes(state.capture.png)
        state.window.begin_waiting()
        threading.Thread(
            target=self._ask_worker,
            args=(key, generation, callback, text, png, history),
            daemon=True,
            name=f"petcore-screen-ask-{key[1]}",
        ).start()

    def _ask_worker(
        self,
        key: tuple[str, int],
        generation: int,
        callback: AskCallback,
        question: str,
        png: bytes,
        history: list[dict],
    ) -> None:
        try:
            reply = callback(question, png, history, key[1])
        except Exception as exc:
            # 只记类型：异常文本可能带 endpoint/密钥片段，绝不进日志。
            logger.warning("screen ask callback failed: %s", type(exc).__name__)
            self._reply_failed.emit(
                key[0], key[1], generation, str(exc) or type(exc).__name__
            )
            return
        self._reply_ready.emit(key[0], key[1], generation, str(reply or ""))

    def _apply_reply(self, owner: str, slot: int, generation: int, reply: str) -> None:
        state = self._states.get((owner, slot))
        if state is None or generation != state.generation:
            return
        text = str(reply or "").strip()
        if not text:
            state.pending_question = ""
            state.window.end_waiting("模型没有返回内容")
            return
        state.history.append({"role": "user", "content": state.pending_question})
        state.history.append({"role": "assistant", "content": text})
        state.pending_question = ""
        state.window.append_assistant(text)
        state.window.end_waiting()

    def _apply_failure(self, owner: str, slot: int, generation: int, reason: str) -> None:
        state = self._states.get((owner, slot))
        if state is None or generation != state.generation:
            return
        # 失败不落假答复：历史保持「已完成回合」，这一问不算完成。
        state.pending_question = ""
        state.window.end_waiting(f"发送失败：{reason}")
