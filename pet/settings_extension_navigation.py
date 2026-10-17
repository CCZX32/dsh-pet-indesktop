"""DLC AI settings navigation to the existing, lock-owning settings process.

Only the fixed AI owner route is accepted. Requests are bounded and transient;
the idle settings receiver has no polling timer or worker thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QLockFile, QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from shiboken6 import isValid

_LOG = logging.getLogger(__name__)
_REQUEST = b"ai-settings\n"
_ACK = b"ok\n"


def _endpoint(config_dir, pid):
    digest = hashlib.sha256(os.fsencode(Path(config_dir).resolve())).hexdigest()[:16]
    # Keep the name short: POSIX also counts the system temporary-directory prefix.
    return f"pet-ai-{digest}-{pid}"


class AiSettingsReceiver(QObject):
    """Created only after _exec_settings owns settings.lock; closed before unlock."""

    def __init__(self, config_dir, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self._closed = False
        self._navigating = False
        self._connections = set()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.setMaxPendingConnections(8)
        self.server.newConnection.connect(self._accept)
        name = _endpoint(config_dir, os.getpid())
        # The singleton lock rules out another live receiver for this identity.
        QLocalServer.removeServer(name)
        if not self.server.listen(name):
            _LOG.warning("DLC settings navigation unavailable: %s", self.server.errorString())

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self._connections) >= 8:
                socket.abort()
                socket.deleteLater()
                continue
            self._connections.add(socket)
            socket.setReadBufferSize(len(_REQUEST) + 1)
            deadline = QTimer(socket)
            deadline.setSingleShot(True)
            deadline.timeout.connect(lambda socket=socket: socket.abort())
            deadline.start(2000)
            buffer = bytearray()

            def receive(socket=socket, deadline=deadline, buffer=buffer):
                buffer.extend(bytes(socket.readAll()))
                if not _REQUEST.startswith(buffer):
                    socket.abort()
                elif buffer == _REQUEST:
                    deadline.stop()
                    socket.write(_ACK)
                    socket.disconnectFromServer()
                    if not self._navigating and not self._closed:
                        self._navigating = True
                        QTimer.singleShot(0, self._navigate)

            def disconnected(socket=socket):
                self._connections.discard(socket)
                socket.deleteLater()

            socket.readyRead.connect(receive)
            socket.disconnected.connect(disconnected)
            receive()

    def _navigate(self):
        try:
            if self._closed or not isValid(self.dialog):
                return
            if self.dialog.isMinimized():
                self.dialog.showNormal()
            else:
                self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            # Reuse the same-owner draft preservation and other-owner draft gate.
            self.dialog.select_page("extension:official.ai-chat")
        finally:
            self._navigating = False

    def close(self):
        self._closed = True
        if isValid(self.server):
            self.server.close()
        for socket in tuple(self._connections):
            if isValid(socket):
                socket.abort()
        self._connections.clear()


class AiSettingsRequest(QObject):
    """One asynchronous click, including a short wait for a starting settings host."""

    def __init__(self, config_dir, on_failed, *, timeout_ms=5000):
        super().__init__(QCoreApplication.instance())
        self.finished = False
        self._config_dir = Path(config_dir)
        self._on_failed = on_failed
        self._timeout_ms = timeout_ms
        self._name = None
        self._reply = bytearray()
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._socket = QLocalSocket(self)
        self._socket.setReadBufferSize(len(_ACK) + 1)
        self._socket.connected.connect(lambda: self._socket.write(_REQUEST))
        self._socket.readyRead.connect(self._received)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._attempt)
        self._timer.start()
        self._attempt()

    def _attempt(self):
        if self.finished:
            return
        if self._elapsed.elapsed() >= self._timeout_ms:
            self._finish(False)
            return
        if self._socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            return
        if self._name is None:
            lock = QLockFile(str(self._config_dir / "settings.lock"))
            info = lock.getLockInfo()
            if info is None:
                return
            pid, _host, _app = info
            if pid <= 0:
                return
            # Pin this process generation: never replay a click into a later host.
            self._name = _endpoint(self._config_dir, pid)
        self._socket.connectToServer(self._name)

    def _received(self):
        self._reply.extend(bytes(self._socket.readAll()))
        if self._reply == _ACK:
            self._finish(True)
        elif not _ACK.startswith(self._reply):
            self._finish(False)

    def _finish(self, delivered):
        if self.finished:
            return
        self.finished = True
        self._timer.stop()
        self._socket.abort()
        callback, self._on_failed = self._on_failed, None
        self.deleteLater()
        if not delivered:
            _LOG.warning("DLC settings navigation request was not acknowledged")
            callback()
