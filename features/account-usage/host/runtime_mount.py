# -*- coding: utf-8 -*-
"""账户用量包 Runtime：手动查询 + 周期刷新 + 结果气泡。

网络请求在 daemon 线程里跑，结果经 Qt 信号回到 GUI 线程；定时器来自
``context.scheduler``，``stop``/``close`` 一定取消，停用后不留后台动作。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .balance import BalanceError, fetch_balance, format_balance
from .config import AccountConfig

_LOG = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30.0
BUBBLE_MS = 6000


class _QueryBridge(QObject):
    finished = Signal(object)


class AccountUsageRuntime:
    def __init__(self, context):
        self.context = context
        self.config = AccountConfig(context)
        self.commands = {"usage": self.show, "refresh": self.refresh}
        self._bridge = _QueryBridge()
        self._bridge.finished.connect(self._on_result)
        self._timer = None
        self._busy = False
        self._armed = False
        self._closed = False

    # --------------------------------------------------------------- 命令面
    def show(self):
        if self._closed:
            return
        cached = self._read_cache()
        if cached is not None and time.time() - cached[0] < CACHE_TTL_SECONDS:
            self._bubble(cached[1])
            return
        self._query()

    def refresh(self):
        if self._closed:
            return
        self._query()

    # --------------------------------------------------------------- 生命周期
    def start(self):
        if self._closed:
            return
        self._armed = True
        self._schedule()

    def stop(self):
        self._armed = False
        self._cancel_timer()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._armed = False
        self._cancel_timer()
        scheduler = self.context.scheduler
        if scheduler is not None:
            scheduler.close()

    # --------------------------------------------------------------- 内部实现
    def _schedule(self) -> None:
        self._cancel_timer()
        if self._closed or not self._armed or not self.config.enabled:
            return
        minutes = self.config.refresh_minutes
        scheduler = self.context.scheduler
        if minutes <= 0 or scheduler is None:
            return
        self._timer = scheduler.call_repeating(minutes * 60_000, self.refresh)

    def _cancel_timer(self) -> None:
        scheduler = self.context.scheduler
        if self._timer is not None and scheduler is not None:
            scheduler.cancel(self._timer)
        self._timer = None

    def _query(self) -> None:
        if self._closed or self._busy:
            return
        api_key = self.config.api_key()
        if not api_key:
            self._bubble("余额查询失败：未配置 API Key（扩展设置 → 账户用量）")
            return
        base_url = self.config.base_url
        verify_ssl = self.config.verify_ssl
        self._busy = True

        def work() -> None:
            try:
                payload = fetch_balance(base_url, api_key, verify_ssl=verify_ssl)
                result = ("ok", format_balance(payload))
            except BalanceError as exc:
                result = ("error", str(exc))
            except Exception:
                _LOG.exception("账户用量查询失败")
                result = ("error", "请求失败")
            self._bridge.finished.emit(result)

        threading.Thread(target=work, name="account-usage-query", daemon=True).start()

    @Slot(object)
    def _on_result(self, result) -> None:
        self._busy = False
        if self._closed or not isinstance(result, tuple) or len(result) != 2:
            return
        kind, value = result
        if kind == "ok":
            self._write_cache(value)
            self._bubble(value)
        else:
            self._bubble(f"余额查询失败：{value}")

    def _bubble(self, text: str) -> None:
        presentation = self.context.presentation
        if presentation is not None:
            presentation.show_bubble(str(text), duration_ms=BUBBLE_MS)

    # --------------------------------------------------------------- 缓存
    def _cache_path(self) -> Path | None:
        user_data = self.context.user_data
        return Path(user_data.root) / "balance_cache.json" if user_data is not None else None

    def _read_cache(self):
        path = self._cache_path()
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text("utf-8"))
            at, text = float(payload["at"]), str(payload["text"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return at, text

    def _write_cache(self, text: str) -> None:
        path = self._cache_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"at": time.time(), "text": text}, ensure_ascii=False), "utf-8")
            temporary.replace(path)
        except OSError:
            _LOG.warning("账户用量缓存写入失败", exc_info=True)
