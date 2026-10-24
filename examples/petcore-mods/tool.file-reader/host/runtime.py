"""拖文件解读运行时：订阅 Core 的 drop 事件、后台请求 AI、气泡 + 会话记录。

运行时无 Qt；所有回 GUI 线程的动作都走 `SchedulerPort.call_later`。
"""

from __future__ import annotations

import threading
import time

from .reader import (
    BUDGET_EXHAUSTED_HINT,
    NO_SERVICE_HINT,
    NO_TEXT_HINT,
    ScanBudget,
    build_user_text,
    collect_interpretable,
    extract_text,
    summarize,
)

OWNER = "tool.file-reader"
PROGRESS_BUBBLE_MS = 3500
REQUEST_TIMEOUT_S = 120.0


class FileReaderRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"read_last": self.read_last}
        self._unsubscribe = None
        self._busy = False
        self._stopped = False
        self._generation = 0
        self._cancel = None
        self._progress = None
        self._last: list = []
        self._threads: list[threading.Thread] = []

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> None:
        self._stopped = False
        interaction = self.context.ports.interaction
        if interaction is not None and self._unsubscribe is None:
            self._unsubscribe = interaction.on_drop(OWNER, self.on_drop)

    def stop(self) -> None:
        self._stopped = True
        self._generation += 1
        if self._cancel is not None:
            self._cancel.set()
        scheduler = self.context.ports.scheduler
        if self._progress is not None and scheduler is not None:
            scheduler.cancel(self._progress)
        self._progress = None
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:  # noqa: BLE001 - 卸载失败不该拖垮退出
                pass
            self._unsubscribe = None
        self._busy = False

    def close(self) -> None:
        self.stop()

    # ---------------------------------------------------------------- 命令

    def read_last(self) -> None:
        if not self._last:
            self._say("还没有拖过文件：把文件拖到桌宠身上就能解读。")
            return
        self._start(self._last, truncated=False)

    # ---------------------------------------------------------------- 事件

    def on_drop(self, paths) -> None:
        if self._stopped or not self._enabled():
            return
        budget = ScanBudget()
        files = collect_interpretable(paths, budget)
        if not files:
            self._say(BUDGET_EXHAUSTED_HINT if budget.truncated else NO_TEXT_HINT)
            return
        self._last = list(files)
        self._start(files, truncated=budget.truncated)

    # ---------------------------------------------------------------- 请求

    def _start(self, files, *, truncated: bool) -> None:
        if self._stopped or not self._enabled():
            return
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._busy or self._threads:
            self._say("上一批还在解读，稍等一下…")
            return
        api = getattr(self.context.ports, "api", None)
        service_id = self._service_id(api)
        if api is None or not service_id:
            self._say(NO_SERVICE_HINT)
            return
        content, skipped = extract_text(files)
        if not content.strip():
            self._say(NO_TEXT_HINT)
            return
        self._busy = True
        names = [path.name for path in files]
        message = build_user_text(content, names, skipped, budget_truncated=truncated)
        self._say(f"正在读 {len(files)} 个文件…")

        generation = self._generation
        stop = threading.Event()
        self._cancel = stop
        interval = max(5.0, self._float("file_reader_progress_seconds", 15.0))
        scheduler = self.context.ports.scheduler
        handle = None
        if scheduler is not None:
            started = time.monotonic()

            def heartbeat() -> None:
                if stop.is_set():
                    return
                self._say(f"还在读…已用 {int(time.monotonic() - started)} 秒")

            handle = scheduler.call_every(int(interval * 1000), heartbeat)
            self._progress = handle

        def work() -> None:
            failure: BaseException | None = None
            text = ""
            try:
                result = api.stream_chat(
                    service_id,
                    [{"role": "user", "content": message}],
                    timeout=REQUEST_TIMEOUT_S,
                    cancel=stop,
                )
                text = getattr(result, "text", "") or ""
            except Exception as exc:  # noqa: BLE001 - 失败必须可见
                failure = exc
            finally:
                stop.set()
                if handle is not None and scheduler is not None:
                    scheduler.cancel(handle)
            if failure is not None:
                self._later(lambda: self._fail(failure), generation)
                return
            self._later(lambda: self._finish(text), generation)

        thread = threading.Thread(target=work, name="file-reader", daemon=True)
        self._threads.append(thread)
        thread.start()

    def _finish(self, text: str) -> None:
        self._busy = False
        self._say(summarize(text) or "读完了，但没拿到内容。")
        if not self._record_enabled():
            return
        chat = getattr(self.context.ports, "chat", None)
        record = getattr(chat, "record", None) if chat is not None else None
        if not callable(record):
            return
        try:
            record(OWNER, "user", "（拖入文件）请解读这些文件")
            record(OWNER, "assistant", text)
        except Exception:  # noqa: BLE001 - 记录失败不影响气泡
            pass

    def _fail(self, exc: BaseException) -> None:
        self._busy = False
        self._say(str(exc) or "解读失败")

    # ---------------------------------------------------------------- 配置/工具

    def _config(self):
        return getattr(self.context.ports, "config", None)

    def _bool(self, key: str, default: bool) -> bool:
        config = self._config()
        if config is None:
            return default
        try:
            return bool(config.get(key, default))
        except Exception:  # noqa: BLE001 - 配置异常按默认值走
            return default

    def _float(self, key: str, default: float) -> float:
        config = self._config()
        if config is None:
            return default
        try:
            return float(config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _enabled(self) -> bool:
        return self._bool("file_reader_enabled", True)

    def _record_enabled(self) -> bool:
        return self._bool("file_reader_record", True)

    def _service_id(self, api) -> str:
        if api is None:
            return ""
        config = self._config()
        selected = ""
        if config is not None:
            try:
                selected = str(config.get("ai_service", "") or "")
            except Exception:  # noqa: BLE001 - 读配置失败按自动选择
                selected = ""
        if selected:
            return selected
        try:
            services = list(api.services())
        except Exception:  # noqa: BLE001 - 服务表损坏按未配置处理
            return ""
        return str(getattr(services[0], "service_id", "")) if services else ""

    def _later(self, callback, generation: int) -> None:
        def deliver():
            if self._stopped or generation != self._generation:
                return
            if not self._enabled():
                self._busy = False
                return
            self._progress = None
            callback()

        scheduler = self.context.ports.scheduler
        if scheduler is None:
            deliver()
            return
        scheduler.call_later(0, deliver)

    def _say(self, text: str) -> None:
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say(text, duration_ms=PROGRESS_BUBBLE_MS, force=True)
