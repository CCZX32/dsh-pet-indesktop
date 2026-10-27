"""致谢数据的后台刷新任务。

用守护线程而不是 ``QThread``：刷新可能持续到单次请求超时（粉丝 79 页），关闭
设置窗时不该把进程卡住；任务对象保留在模块级集合里直到线程结束，避免「C++
对象已删除还在 emit」。
"""

from __future__ import annotations

import logging
import threading
import warnings

from PySide6.QtCore import QCoreApplication, QObject, Signal

logger = logging.getLogger("petcore.ui.settings.credits_job")

_LIVE: set["CommunityRefreshJob"] = set()


class CommunityRefreshJob(QObject):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, *, kinds=("credits", "fans"), force: bool = False) -> None:
        super().__init__()
        self._service = service
        self._kinds = tuple(kinds)
        self._force = bool(force)
        self._cancelled = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        _LIVE.add(self)
        self._thread = threading.Thread(
            target=self._run, name="petcore-community-refresh", daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True
        with warnings.catch_warnings():
            # 没有连接的信号 disconnect 会发 RuntimeWarning，不是错误。
            warnings.simplefilter("ignore", RuntimeWarning)
            for name in ("progress", "done", "failed"):
                try:
                    getattr(self, name).disconnect()
                except (RuntimeError, TypeError):
                    pass

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _report(self, message: str) -> None:
        if self._cancelled or QCoreApplication.instance() is None:
            return
        self.progress.emit(str(message))

    def _run(self) -> None:
        try:
            report = self._service.refresh(
                kinds=self._kinds, force=self._force, progress=self._report
            )
        except Exception as exc:  # noqa: BLE001 - 线程里的异常必须变成信号
            logger.warning("community refresh failed: %s", type(exc).__name__)
            if not self._cancelled and QCoreApplication.instance() is not None:
                self.failed.emit(type(exc).__name__)
        else:
            if not self._cancelled and QCoreApplication.instance() is not None:
                self.done.emit(report)
        finally:
            self._thread = None
            _LIVE.discard(self)


def cancel_all(timeout: float = 0.5) -> None:
    """退出/关闭设置窗时统一取消；最多等 ``timeout`` 秒，不阻止 Qt 退出。"""
    jobs = list(_LIVE)
    for job in jobs:
        job.cancel()
    for job in jobs:
        thread = job._thread
        if thread is None or thread is threading.current_thread():
            continue
        try:
            thread.join(max(0.0, float(timeout)))
        except RuntimeError:
            continue
