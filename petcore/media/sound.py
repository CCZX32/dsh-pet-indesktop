from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("petcore.sound")

_MAX_CACHED = 16


def _new_media_player():
    """创建 ``(QMediaPlayer, QAudioOutput)``；QtMultimedia 不可用时返回 None。

    保留为模块级函数：用户自定义 mp3/ogg 走这条通道，测试可整体替换它。
    """
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except Exception:
        return None
    return QMediaPlayer(), QAudioOutput()


class SoundPlayer:
    """轻量音效播放：按路径缓存播放器，首播不再临时初始化音频后端。

    - ``.wav``（内置 click.wav / 小黄鸭转码产物）走 ``QSoundEffect``；
    - 其它格式（用户自定义 mp3/ogg/flac/m4a）走 ``QMediaPlayer + QAudioOutput``。

    首次创建播放对象会触发 QtMultimedia 后端初始化（实测几百毫秒），落在点击
    瞬间就是「第一次点击卡一下」。窗口启动时调用 :meth:`prepare` 预建，点击时
    只做 ``play()``。
    """

    def __init__(self, volume: float = 0.8):
        self.volume = max(0.0, min(1.0, volume))
        self._cache: dict[str, object] = {}
        self._players: dict[str, tuple[object, object]] = {}

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, float(volume)))
        for effect in self._cache.values():
            try:
                effect.setVolume(self.volume)
            except Exception:
                pass
        for _player, audio in self._players.values():
            try:
                audio.setVolume(self.volume)
            except Exception:
                pass

    def _make(self, source: Path):
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except Exception:
            return None
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(str(source)))
        effect.setVolume(self.volume)
        return effect

    def _prepare_player(self, source: Path) -> bool:
        key = str(source)
        pair = _new_media_player()
        if pair is None:
            return False
        player, audio = pair
        try:
            from PySide6.QtCore import QUrl

            audio.setVolume(self.volume)
            player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(str(source)))
        except Exception:
            logger.debug("media player setup failed: %s", source, exc_info=True)
            return False
        self._players[key] = (player, audio)
        if len(self._players) > _MAX_CACHED:
            self._players.pop(next(iter(self._players)))
        return True

    def _is_wav(self, source: Path) -> bool:
        return source.suffix.lower() == ".wav"

    def prepare(self, path: Path | str) -> bool:
        source = Path(path)
        key = str(source)
        is_wav = self._is_wav(source)
        cached = key in (self._cache if is_wav else self._players)
        if cached:
            return True
        if not source.exists():
            return False
        if not is_wav:
            return self._prepare_player(source)
        effect = self._make(source)
        if effect is None:
            return False
        self._cache[key] = effect
        if len(self._cache) > _MAX_CACHED:
            self._cache.pop(next(iter(self._cache)))
        return True

    def play(self, path: Path | str, volume: float | None = None) -> bool:
        source = Path(path)
        key = str(source)
        target = self.volume if volume is None else max(0.0, min(1.0, float(volume)))
        if not self._is_wav(source):
            pair = self._players.get(key)
            if pair is None:
                if not self.prepare(source):
                    logger.debug("sound file missing or unavailable: %s", source)
                    return False
                pair = self._players.get(key)
            if pair is None:
                return False
            player, audio = pair
            try:
                audio.setVolume(target)
                player.setPosition(0)
                player.play()
            except Exception:
                logger.debug("sound play failed: %s", source, exc_info=True)
                return False
            return True
        if key not in self._cache and not self.prepare(source):
            logger.debug("sound file missing or unavailable: %s", source)
            return False
        effect = self._cache.get(key)
        if effect is None:
            return False
        try:
            effect.setVolume(target)
            effect.play()
        except Exception:
            logger.debug("sound play failed: %s", source, exc_info=True)
            return False
        return True

    def stop_all(self) -> None:
        for effect in self._cache.values():
            try:
                effect.stop()
            except Exception:
                pass
        for player, _audio in self._players.values():
            try:
                player.stop()
            except Exception:
                pass
