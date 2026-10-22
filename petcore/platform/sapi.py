"""Windows 本地语音（SAPI5）：零网络、零 Key、毫秒级，断网时的兜底后端。

移植自主分支 ``pet/tts/sapi.py``（lite 版）：只保留合成与音色探测，不再登记
成 ``TtsProvider``——provider 声明在 :mod:`petcore.net.tts`，本模块只做合成。

要点：

1. **晚绑定** ``CreateObject(..., dynamic=True)``：本机 ``GetModule('sapi.dll')``
   会报 ``TYPE_E_CANTLOADLIBRARY``，不走 typelib 生成；
2. ``SAPI.SpFileStream`` 直接把语音写成 wav，与 ``sapi_synthesize`` 的
   ``out_path`` 契约一致；
3. **COM 是线程级的**：合成跑在后台线程，缺 ``CoInitialize`` 时 ``CreateObject``
   直接抛「尚未调用 CoInitialize」。这里用 thread-local 只初始化一次；
4. 非 Windows 一律 ``RuntimeError("sapi unavailable")``；其它失败按
   ``RuntimeError`` / ``OSError`` 抛出，由 ``SpeechService`` 分类。
"""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path

#: SpFileStream.Open 的 SSFM_CREATE（覆写已有文件）
SSFM_CREATE = 3

_com_ready = threading.local()
_OPTIONS_CACHE: tuple[tuple[str, str], ...] | None = None


def _dependency_present() -> bool:
    try:
        return importlib.util.find_spec("comtypes") is not None
    except (ImportError, ValueError):
        return False


def available() -> bool:
    """Windows 且装了 ``comtypes``（只看平台与依赖，不碰 COM，不查音色）。"""
    return os.name == "nt" and _dependency_present()


def _client():
    from comtypes import client

    return client


def _ensure_com() -> None:
    """确保**当前线程**进过 COM 初始化（每线程只做一次，见主分支注释）。"""
    if getattr(_com_ready, "value", None) is True:
        return
    import comtypes

    comtypes.CoInitialize()
    _com_ready.value = True


def release_thread_com() -> None:
    """本线程若因本模块进过 COM，就配对 ``CoUninitialize`` 释放。

    只给短命的合成 worker 线程收尾用；常驻 GUI 线程不调（那里没有「线程结束」
    这个收尾点，提前释放反而可能让后续 COM 调用落进已拆除的 apartment）。
    """
    if getattr(_com_ready, "value", None) is not True:
        return
    _com_ready.value = False
    try:
        import comtypes

        comtypes.CoUninitialize()
    except Exception:  # pragma: no cover - 非 Windows / 库缺失
        pass


def _voice_objects():
    try:
        _ensure_com()
        voice = _client().CreateObject("SAPI.SpVoice", dynamic=True)
        return voice, voice.GetVoices()
    except Exception:  # noqa: BLE001 - 没语音包/没 COM 都按「拿不到」处理
        return None, None


def installed_voices(force: bool = False) -> tuple[tuple[str, str], ...]:
    """已安装的 SAPI5 音色：``((描述, 描述), ...)``。"""
    global _OPTIONS_CACHE
    if _OPTIONS_CACHE is not None and not force:
        return _OPTIONS_CACHE
    if not available():
        _OPTIONS_CACHE = ()
        return _OPTIONS_CACHE
    _voice, voices = _voice_objects()
    options: list[tuple[str, str]] = []
    if voices is not None:
        for index in range(voices.Count):
            try:
                description = str(voices.Item(index).GetDescription())
            except Exception:  # noqa: BLE001
                continue
            options.append((description, description))
    _OPTIONS_CACHE = tuple(options)
    return _OPTIONS_CACHE


def pick_default_voice(voice, prefer: tuple[str, ...] = ("Chinese", "中文", "Huihui", "Yaoyao", "Kangkang")):
    """挑一个音色：优先中文，其次第一个可用项；一个都没有返回 None。"""
    _voice, voices = _voice_objects()
    if voices is None or voices.Count == 0:
        return None
    fallback = None
    for index in range(voices.Count):
        try:
            item = voices.Item(index)
            description = str(item.GetDescription())
        except Exception:  # noqa: BLE001
            continue
        if fallback is None:
            fallback = item
        if any(key in description for key in prefer):
            return item
    return fallback


def find_voice(description: str):
    """按描述找音色（先精确、再子串；描述为空返回 None）。"""
    wanted = str(description or "").strip()
    if not wanted:
        return None
    _voice, voices = _voice_objects()
    if voices is None:
        return None
    partial = None
    for index in range(voices.Count):
        try:
            item = voices.Item(index)
            text = str(item.GetDescription())
        except Exception:  # noqa: BLE001
            continue
        if text == wanted:
            return item
        if partial is None and wanted.lower() in text.lower():
            partial = item
    return partial


def sapi_rate(rate) -> int:
    """倍率（0.5–2.0）→ SAPI ``Rate``（-10..10，0 为默认）。"""
    try:
        number = float(rate)
    except (TypeError, ValueError):
        number = 1.0
    if number != number:
        number = 1.0
    number = max(0.5, min(2.0, number))
    return max(-10, min(10, int(round((number - 1.0) * 10))))


def sapi_volume(volume) -> int:
    """0.0–1.0 → SAPI ``Volume``（0..100）。"""
    try:
        number = float(volume)
    except (TypeError, ValueError):
        number = 1.0
    if number != number:
        number = 1.0
    return max(0, min(100, int(round(max(0.0, min(1.0, number)) * 100))))


def sapi_synthesize(
    text: str,
    *,
    voice: str = "",
    rate: float = 1.0,
    volume: float = 1.0,
    out_path: Path | str,
) -> None:
    """把文本合成到 ``out_path``（标准 wav）。失败抛 ``RuntimeError``/``OSError``。"""
    if not available():
        raise RuntimeError("sapi unavailable")
    destination = Path(out_path)
    try:
        _ensure_com()
        client = _client()
        speaker = client.CreateObject("SAPI.SpVoice", dynamic=True)
        target = find_voice(str(voice or "")) or pick_default_voice(speaker)
        if target is None:
            raise RuntimeError("sapi unavailable")
        speaker.Voice = target
        speaker.Rate = sapi_rate(rate)
        speaker.Volume = sapi_volume(volume)
        stream = client.CreateObject("SAPI.SpFileStream", dynamic=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        stream.Open(str(destination), SSFM_CREATE)
        speaker.AudioOutputStream = stream
        try:
            speaker.Speak(str(text or ""))
        finally:
            stream.Close()
    except RuntimeError:
        raise
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 - COM 失败统一成 RuntimeError
        raise RuntimeError(f"sapi synthesis failed: {type(exc).__name__}") from exc
    try:
        size = destination.stat().st_size
    except OSError as exc:
        raise OSError("sapi produced no audio file") from exc
    if size <= 0:
        raise OSError("sapi produced empty audio")
