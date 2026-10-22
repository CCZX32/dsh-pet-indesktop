"""聊天窗口的 Core 实现：ChatPort 的唯一实现者。

每个 ``(owner, pet_slot)`` 一个窗口；会话按 slot + 角色落盘，互不串流。
mod 通过端口注册「用户发送 / 停止」回调，窗口关闭只隐藏、不销毁历史。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ...chat.session_store import ChatSession, SessionStore
from .window import ChatWindow

logger = logging.getLogger("petcore.ui.chat")


@dataclass
class _ChatState:
    owner: str
    slot: int
    store: SessionStore
    session: ChatSession
    window: ChatWindow
    submit_callback: Callable[[str, int], None] | None = None
    stop_callback: Callable[[int], None] | None = None
    active: bool = False
    extras: dict = field(default_factory=dict)


class ChatController(QObject):
    """窗口 + 会话 + 流式合帧；对外只暴露 ChatPort 的语义。

    ``token/done/error`` 可能由 mod 的后台线程调用：这里用信号跨线程排队，
    GUI 线程只做合并刷新，绝不在 worker 线程碰控件。
    """

    token_received = Signal(str, str, int)
    done_received = Signal(str, str, int)
    error_received = Signal(str, str, str, int)

    def __init__(self, host, root: Path) -> None:
        super().__init__(host if isinstance(host, QObject) else None)
        self.host = host
        self.root = Path(root)
        self._states: dict[tuple[str, int], _ChatState] = {}
        self._submit_registry: dict[str, Callable[[str, int], None]] = {}
        self._stop_registry: dict[str, Callable[[int], None]] = {}
        self.token_received.connect(self._apply_token)
        self.done_received.connect(self._apply_done)
        self.error_received.connect(self._apply_error)

    # ---------------------------------------------------------------- 公共状态
    def states(self) -> dict[tuple[str, int], _ChatState]:
        return dict(self._states)

    def window_for(self, owner: str, slot: int | None = None) -> ChatWindow | None:
        key = (str(owner), self._slot(slot))
        state = self._states.get(key)
        return state.window if state is not None else None

    # ---------------------------------------------------------------- ChatPort
    def open(self, owner: str, *, pet_slot: int | None = None, title: str = "") -> bool:
        state = self._ensure(owner, pet_slot)
        if title:
            state.window.setWindowTitle(str(title))
        state.window.show()
        state.window.raise_()
        state.window.activateWindow()
        return True

    def append(
        self, owner: str, role: str, text: str, *, pet_slot: int | None = None
    ) -> None:
        state = self._ensure(owner, pet_slot)
        state.window.append_message(role, text)
        state.session.append(role, text)
        self._save(state)

    def token(self, owner: str, delta: str, *, pet_slot: int | None = None) -> None:
        self.token_received.emit(str(owner), str(delta or ""), self._slot(pet_slot))

    def done(
        self, owner: str, text: str = "", *, pet_slot: int | None = None
    ) -> None:
        self.done_received.emit(str(owner), str(text or ""), self._slot(pet_slot))

    def error(
        self,
        owner: str,
        reason: str,
        message: str = "",
        *,
        pet_slot: int | None = None,
    ) -> None:
        self.error_received.emit(
            str(owner), str(reason), str(message or ""), self._slot(pet_slot)
        )

    def history(self, owner: str, *, pet_slot: int | None = None) -> list[dict[str, str]]:
        state = self._ensure(owner, pet_slot)
        return [dict(item) for item in state.session.messages]

    def close(self, owner: str, *, pet_slot: int | None = None) -> None:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        if state is not None:
            state.window.hide()

    def cancel(self, owner: str, *, pet_slot: int | None = None) -> None:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        if state is None:
            return
        if state.stop_callback is not None:
            try:
                state.stop_callback(state.slot)
            except Exception:
                logger.exception("chat stop callback failed")
        state.window.finish_stream(state.window.stream_text())
        state.active = False

    def is_open(self, owner: str, *, pet_slot: int | None = None) -> bool:
        state = self._states.get((str(owner), self._slot(pet_slot)))
        return bool(state is not None and state.window.isVisible())

    def on_submit(
        self, owner: str, callback: Callable[[str, int], None]
    ) -> Callable[[], None]:
        owner = str(owner)
        self._submit_registry[owner] = callback
        return lambda: self._submit_registry.pop(owner, None)

    def on_stop(self, owner: str, callback: Callable[[int], None]) -> Callable[[], None]:
        owner = str(owner)
        self._stop_registry[owner] = callback
        return lambda: self._stop_registry.pop(owner, None)

    # ---------------------------------------------------------------- 内部
    def _slot(self, slot: int | None) -> int:
        if slot is not None:
            try:
                return max(0, int(slot))
            except (TypeError, ValueError):
                return 0
        return 0

    def _character_for(self, slot: int) -> str:
        pets = getattr(self.host, "pets", None)
        if pets is not None:
            window = pets.window_for_slot(slot)
            config = getattr(window, "config", None)
            if config is not None:
                return str(config.get("character") or "default")
        config = getattr(self.host, "config", None)
        if config is not None:
            return str(config.get("character") or "default")
        return "default"

    def _ensure(self, owner: str, pet_slot: int | None) -> _ChatState:
        owner = str(owner)
        slot = self._slot(pet_slot)
        key = (owner, slot)
        state = self._states.get(key)
        if state is not None:
            return state
        store = SessionStore(self.root, slot=slot, character_id=self._character_for(slot))
        sessions = store.list_sessions()
        session = sessions[0] if sessions else store.new_session()
        window = ChatWindow(
            title=self._title(owner, slot),
            font_size=self._font_size(),
        )
        window.submitted.connect(lambda text, s=key: self._on_submit(s, text))
        window.stop_requested.connect(lambda s=key: self._on_stop(s))
        window.cleared.connect(lambda s=key: self._on_clear(s))
        window.session_selected.connect(lambda session_id, s=key: self._on_session(s, session_id))
        window.closed.connect(lambda s=key: self._on_closed(s))
        window.set_history(sessions, session.session_id)
        window.load_messages(session.messages)
        state = _ChatState(
            owner=owner, slot=slot, store=store, session=session, window=window
        )
        self._states[key] = state
        return state

    def _title(self, owner: str, slot: int) -> str:
        suffix = "主桌宠" if slot == 0 else f"桌宠 {slot}"
        return f"AI 对话 · {suffix}"

    def _font_size(self) -> int:
        config = getattr(self.host, "config", None)
        try:
            return int(config.get("ui_font_size") or 13) if config is not None else 13
        except (TypeError, ValueError):
            return 13

    def _save(self, state: _ChatState) -> None:
        try:
            state.store.save(state.session)
        except OSError:
            logger.warning("chat session save failed", exc_info=True)

    def _apply_token(self, owner: str, delta: str, slot: int) -> None:
        state = self._ensure(owner, slot)
        if not state.active:
            state.window.begin_stream()
            state.session.append("assistant", "")
            state.active = True
        state.window.append_token(delta)

    def _apply_done(self, owner: str, text: str, slot: int) -> None:
        state = self._ensure(owner, slot)
        state.window.finish_stream(text)
        final = str(text or "")
        if not final:
            messages = state.window.messages()
            final = messages[-1]["content"] if messages else ""
        # 用窗口的最终内容覆盖会话里那条空的 assistant 记录。
        if state.session.messages and state.session.messages[-1].get("role") == "assistant":
            state.session.messages[-1]["content"] = final[:24_000]
        elif final:
            state.session.append("assistant", final)
        state.active = False
        self._save(state)
        self._refresh_history(state)

    def _apply_error(self, owner: str, reason: str, message: str, slot: int) -> None:
        state = self._ensure(owner, slot)
        state.window.show_error(reason, message)
        if state.session.messages and state.session.messages[-1].get("content") == "":
            state.session.messages.pop()
        state.active = False
        self._save(state)

    def _on_submit(self, key: tuple[str, int], text: str) -> None:
        state = self._states.get(key)
        if state is None:
            return
        callback = self._submit_registry.get(state.owner)
        if callback is None:
            state.window.show_error("no_handler", "没有扩展接管这个对话窗口")
            return
        state.window.append_message("user", text)
        state.session.append("user", text)
        self._save(state)
        self._refresh_history(state)
        try:
            callback(text, state.slot)
        except Exception:
            logger.exception("chat submit callback failed")
            state.window.show_error("handler_failed", "扩展处理消息时出错")

    def _on_stop(self, key: tuple[str, int]) -> None:
        state = self._states.get(key)
        if state is None:
            return
        self.cancel(state.owner, pet_slot=state.slot)

    def _on_clear(self, key: tuple[str, int]) -> None:
        state = self._states.get(key)
        if state is None:
            return
        state.session = state.store.new_session()
        state.active = False
        self._refresh_history(state)

    def _on_session(self, key: tuple[str, int], session_id: str) -> None:
        state = self._states.get(key)
        if state is None:
            return
        if not session_id:
            state.session = state.store.new_session()
            state.window.load_messages([])
        else:
            loaded = state.store.load(session_id)
            if loaded is None:
                return
            state.session = loaded
            state.window.load_messages(loaded.messages)
        state.active = False
        self._refresh_history(state)

    def _on_closed(self, key: tuple[str, int]) -> None:
        state = self._states.get(key)
        if state is not None:
            self._save(state)

    def _refresh_history(self, state: _ChatState) -> None:
        try:
            sessions = state.store.list_sessions()
        except OSError:
            sessions = []
        state.window.set_history(sessions, state.session.session_id)
