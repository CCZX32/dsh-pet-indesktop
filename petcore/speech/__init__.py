"""Core 语音子系统：合成、缓存、重试与凭据；mod 只经 ``HostPorts.speech`` 使用。

本包**Qt-free**、**不 import 网络库**：真正联网的实现在 :mod:`petcore.net.tts`，
Windows 本地语音在 :mod:`petcore.platform.sapi`，后台线程与共享音频通道在
:mod:`petcore.ui.ports`。
"""

from __future__ import annotations

from .cache import SpeechCache
from .service import SpeechService

__all__ = ["SpeechCache", "SpeechService"]
