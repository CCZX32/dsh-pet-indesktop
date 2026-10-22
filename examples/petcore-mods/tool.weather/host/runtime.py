"""天气命令：菜单触发、后台线程取数、气泡反馈。运行时无 Qt。"""

from __future__ import annotations

import threading

from .client import WeatherClient
from .logic import NO_CITY_TEXT, WeatherReading, city_code_for, current_city


class WeatherRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"show": self.show}
        self.client_factory = WeatherClient
        self._busy = False
        self._threads: list[threading.Thread] = []

    # ---------------------------------------------------------------- 命令

    def show(self) -> None:
        ports = self.context.ports
        presentation = ports.presentation
        if presentation is None:
            return
        config = ports.config
        if config is not None and not bool(config.get("weather_enabled", True)):
            presentation.say(
                "天气提醒已关闭：设置 → 扩展管理 → 天气", duration_ms=5000, force=True
            )
            return
        if self._busy:
            presentation.say("还在查天气，稍等一下…", duration_ms=3000, force=True)
            return
        city = current_city(config) if config is not None else ""
        if not city:
            presentation.say(NO_CITY_TEXT, duration_ms=6000, force=True)
            return
        http = getattr(ports, "http", None)
        if http is None:
            presentation.say("取数端口不可用：请更新 core 后再试", duration_ms=6000, force=True)
            return
        code = city_code_for(config, city) if config is not None else ""
        self._busy = True
        presentation.say(f"正在查 {city} 的天气…", duration_ms=3000, force=True)
        thread = threading.Thread(
            target=self._work, args=(http, city, code), name="weather-fetch", daemon=True
        )
        self._threads.append(thread)
        thread.start()

    # ---------------------------------------------------------------- 线程

    def _work(self, http, city: str, code: str) -> None:
        try:
            reading = self.client_factory(http).fetch(city, code=code)
        except Exception as exc:  # noqa: BLE001 - 失败必须变成可见气泡
            self._later(lambda exc=exc: self._fail(exc))
            return
        self._later(lambda reading=reading: self._finish(reading))

    def _later(self, callback) -> None:
        scheduler = self.context.ports.scheduler
        if scheduler is None:
            callback()
            return
        scheduler.call_later(0, callback)

    def _finish(self, reading: WeatherReading) -> None:
        self._busy = False
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say(reading.bubble_text(), duration_ms=6000, force=True)

    def _fail(self, exc: BaseException) -> None:
        self._busy = False
        presentation = self.context.ports.presentation
        if presentation is not None:
            presentation.say(str(exc) or "天气获取失败", duration_ms=8000, force=True)

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> None:
        return

    def stop(self) -> None:
        self._busy = False

    def close(self) -> None:
        self.stop()
