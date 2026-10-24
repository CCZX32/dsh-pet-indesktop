from __future__ import annotations

import logging
import os

from PySide6.QtCore import QAbstractNativeEventFilter, QObject

logger = logging.getLogger("petcore.platform.session")

_WM_QUERYENDSESSION = 0x0011
_WM_ENDSESSION = 0x0016


class SessionWatcher(QObject, QAbstractNativeEventFilter):
    def __init__(self, on_session_end, parent: QObject | None = None):
        super().__init__(parent)
        self._on_session_end = on_session_end
        self._fired = False

    def install(self) -> None:
        app = _qapp()
        if app is not None:
            app.installNativeEventFilter(self)

    def remove(self) -> None:
        app = _qapp()
        if app is not None:
            app.removeNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt" or self._fired:
            return False, 0
        try:
            import ctypes

            from ctypes import wintypes

            # HWND is pointer-sized: indexing uint32 words reads the high half
            # of HWND, not MSG.message, on 64-bit Windows.
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            message_id = msg.message
        except Exception:
            return False, 0
        if message_id in (_WM_QUERYENDSESSION, _WM_ENDSESSION):
            self._fired = True
            try:
                self._on_session_end()
            except Exception:
                logger.debug("session end callback failed", exc_info=True)
        return False, 0


def _qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance()
