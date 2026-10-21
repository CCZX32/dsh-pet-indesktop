"""Host 端口的 Qt 实现：定时器、存储、宠物注册表、交互事件与免打扰。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QTimer

from .. import paths
from ..contracts.api import ApiMetadata, ApiRequest
from ..contracts.host import HostPorts

logger = logging.getLogger("petcore.ui.ports")


class QtScheduler:
    def __init__(self) -> None:
        self._timers: dict[str, QTimer] = {}
        self._counter = 0

    def _new_handle(self) -> str:
        self._counter += 1
        return f"timer-{self._counter}"

    def call_later(self, delay_ms: int, callback) -> str:
        handle = self._new_handle()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(max(0, int(delay_ms)))
        timer.timeout.connect(lambda: self._fire(handle, callback))
        self._timers[handle] = timer
        timer.start()
        return handle

    def call_every(self, interval_ms: int, callback) -> str:
        handle = self._new_handle()
        timer = QTimer()
        timer.setInterval(max(1, int(interval_ms)))
        timer.timeout.connect(callback)
        self._timers[handle] = timer
        timer.start()
        return handle

    def _fire(self, handle: str, callback) -> None:
        timer = self._timers.pop(handle, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        try:
            callback()
        except Exception:
            logger.exception("scheduled callback failed")

    def cancel(self, handle: str) -> None:
        timer = self._timers.pop(handle, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def cancel_owner(self, owner: str) -> None:
        del owner


class AudioAdapter:
    def __init__(self, window) -> None:
        self.window = window

    def play(self, path: Path | str, volume: float | None = None) -> bool:
        try:
            player = self.window.sound
            if volume is not None:
                player.set_volume(float(volume))
            player.play(Path(path))
            return True
        except Exception:
            logger.debug("audio play failed", exc_info=True)
            return False

    def set_volume(self, volume: float) -> None:
        try:
            self.window.sound.set_volume(float(volume))
        except Exception:
            pass


class StorageAdapter:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def data_dir(self, owner: str) -> Path:
        path = paths.feature_data_dir(self.root, owner)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def config_dir(self, owner: str) -> Path:
        return self.data_dir(owner)


class QuietMode:
    def __init__(self) -> None:
        self._until: float | None = None

    def set_quiet(self, seconds: float) -> None:
        self._until = time.monotonic() + max(0.0, float(seconds)) if seconds > 0 else None

    def quiet_active(self) -> bool:
        if self._until is None:
            return False
        if time.monotonic() >= self._until:
            self._until = None
            return False
        return True

    def quiet_until(self) -> float | None:
        return self._until

    def remaining_seconds(self) -> float:
        until = self._until
        if until is None:
            return 0.0
        remaining = until - time.monotonic()
        if remaining <= 0.0:
            self._until = None
            return 0.0
        return remaining


class PetHandleImpl:
    def __init__(self, host, window) -> None:
        self.host = host
        self.window = window
        self.slot = window.slot
        self.is_primary = window.is_primary

    def body_rect(self) -> tuple[int, int, int, int]:
        return self.window.body_rect()

    def velocity(self) -> tuple[float, float]:
        return self.window.motion.velocity()

    def move_by(self, dx: float, dy: float) -> None:
        self.window.move(
            int(round(self.window.x() + dx)), int(round(self.window.y() + dy))
        )

    def set_velocity(self, vx: float, vy: float) -> None:
        self.window.motion.set_velocity(vx, vy)

    def show(self) -> None:
        self.window.set_visible(True)

    def hide(self) -> None:
        self.window.set_visible(False)

    def say(self, text: str, duration_ms: int = 4000) -> None:
        self.window.say(text, duration_ms)

    def play_animation(self, name: str) -> bool:
        return self.window.play_animation(name)

    def play_event(self, group: str, variant: str | int | None = None) -> bool:
        return self.window.play_event(group, variant)


class PetRegistry:
    def __init__(self, host) -> None:
        self.host = host

    def pets(self) -> tuple[PetHandleImpl, ...]:
        manager = getattr(self.host, "pets", None)
        if manager is None:
            return ()
        return tuple(PetHandleImpl(self.host, window) for window in manager.each())

    def primary(self) -> PetHandleImpl | None:
        window = getattr(self.host, "window", None)
        return PetHandleImpl(self.host, window) if window is not None else None

    def active(self) -> PetHandleImpl | None:
        window = getattr(self.host, "_active_window", None) or getattr(self.host, "window", None)
        return PetHandleImpl(self.host, window) if window is not None else None


class InteractionAdapter:
    def __init__(self, host) -> None:
        self.host = host
        self._click_callbacks: dict[str, list] = {}
        self._drop_callbacks: dict[str, list] = {}
        self._timers: dict[str, list[str]] = {}
        self._scheduler = QtScheduler()
        # 每个窗口一份包装表：``id(window) -> (window, {id(callback): wrapper})``。
        # 包装器按 (窗口, 回调) 唯一，重复 attach 不会让一次点击触发多次。
        self._click_wrappers: dict[int, tuple[object, dict[int, object]]] = {}
        self._drop_wrappers: dict[int, tuple[object, dict[int, object]]] = {}

    def _windows(self):
        manager = getattr(self.host, "pets", None)
        if manager is not None:
            return list(manager.each())
        window = getattr(self.host, "window", None)
        return [window] if window is not None else []

    def _wrapper_table(self, registry, window) -> dict[int, object]:
        key = id(window)
        entry = registry.get(key)
        if entry is None or entry[0] is not window:
            entry = (window, {})
            registry[key] = entry
        return entry[1]

    def attach_window(self, window) -> None:
        """把当前所有点击/投喂回调挂到 ``window``（子宠 spawn 后必须补这一挂）。"""
        if window is None:
            return
        click_table = self._wrapper_table(self._click_wrappers, window)
        add_click = getattr(window, "add_click_listener", None)
        if callable(add_click):
            for callbacks in self._click_callbacks.values():
                for callback in callbacks:
                    marker = id(callback)
                    if marker in click_table:
                        continue
                    wrapper = lambda win, cb=callback: cb(win)
                    click_table[marker] = wrapper
                    add_click(wrapper)
        drop_table = self._wrapper_table(self._drop_wrappers, window)
        add_drop = getattr(window, "add_drop_listener", None)
        if callable(add_drop):
            for callbacks in self._drop_callbacks.values():
                for callback in callbacks:
                    marker = id(callback)
                    if marker in drop_table:
                        continue
                    wrapper = lambda items, cb=callback: cb(list(items))
                    drop_table[marker] = wrapper
                    add_drop(wrapper)

    def detach_window(self, window) -> None:
        """窗口关闭时摘掉监听，避免回调持有已销毁的窗口。"""
        if window is None:
            return
        for registry, remover in (
            (self._click_wrappers, "remove_click_listener"),
            (self._drop_wrappers, "remove_drop_listener"),
        ):
            entry = registry.pop(id(window), None)
            if entry is None or entry[0] is not window:
                continue
            remove = getattr(window, remover, None)
            if not callable(remove):
                continue
            for wrapper in entry[1].values():
                try:
                    remove(wrapper)
                except RuntimeError:
                    break

    def on_click(self, owner: str, callback):
        self._click_callbacks.setdefault(owner, []).append(callback)
        for window in self._windows():
            self.attach_window(window)
        return lambda: self._remove(
            owner, callback, self._click_callbacks, self._click_wrappers
        )

    def on_drop(self, owner: str, callback):
        self._drop_callbacks.setdefault(owner, []).append(callback)
        for window in self._windows():
            self.attach_window(window)
        return lambda: self._remove(
            owner, callback, self._drop_callbacks, self._drop_wrappers
        )

    def _remove(self, owner: str, callback, table, registry=None) -> None:
        values = table.get(owner)
        if values and callback in values:
            values.remove(callback)
        if registry is not None:
            self._detach_callback(callback, registry)

    def _detach_callback(self, callback, registry) -> None:
        marker = id(callback)
        remover = (
            "remove_click_listener"
            if registry is self._click_wrappers
            else "remove_drop_listener"
        )
        for key, (window, wrappers) in list(registry.items()):
            wrapper = wrappers.pop(marker, None)
            if wrapper is None:
                continue
            remove = getattr(window, remover, None)
            if callable(remove):
                try:
                    remove(wrapper)
                except RuntimeError:
                    pass
            if not wrappers:
                registry.pop(key, None)

    def on_tick(self, owner: str, callback, interval_ms: int = 16) -> str:
        handle = self._scheduler.call_every(interval_ms, lambda: callback(interval_ms / 1000.0))
        self._timers.setdefault(owner, []).append(handle)
        return handle

    def cancel_owner(self, owner: str) -> None:
        for handle in self._timers.pop(owner, []):
            self._scheduler.cancel(handle)
        for callback in self._click_callbacks.pop(owner, []):
            self._detach_callback(callback, self._click_wrappers)
        for callback in self._drop_callbacks.pop(owner, []):
            self._detach_callback(callback, self._drop_wrappers)


class CoreApiPort:
    """API 能力的 core 门面：mod 只看见元数据与一次解析结果，拿不到存储实现。"""

    OWNER = "core.api"

    def __init__(self, host, store, credentials) -> None:
        self.host = host
        self.store = store
        self.credentials = credentials

    def services(self) -> tuple[ApiMetadata, ...]:
        version = str(self.store.version())
        return tuple(service.metadata(version) for service in self.store.services())

    def metadata(self, service_id: str) -> ApiMetadata:
        service = self.store.get(service_id)
        if service is None:
            raise KeyError(f"unknown api service: {service_id}")
        return service.metadata(str(self.store.version()))

    def resolve(self, service_id: str) -> ApiRequest:
        metadata = self.metadata(service_id)
        api_key = self.credentials.get(self.OWNER, str(service_id)) or ""
        return ApiRequest(metadata, api_key)

    def subscribe(self, callback):
        return self.store.subscribe(callback)

    def open_settings(self) -> None:
        self.host.open_settings("api")


def build_ports(host, window) -> HostPorts:
    store = getattr(host, "api_store", None)
    credentials = getattr(host, "api_credentials", None)
    api = CoreApiPort(host, store, credentials) if store is not None and credentials is not None else None
    return HostPorts(
        presentation=host.presentation_port(),
        scheduler=QtScheduler(),
        audio=AudioAdapter(window),
        storage=StorageAdapter(host.root),
        pets=PetRegistry(host),
        interaction=InteractionAdapter(host),
        quiet=getattr(host, "quiet", None),
        credentials=credentials,
        api=api,
    )
