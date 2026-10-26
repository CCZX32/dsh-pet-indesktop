"""右键菜单动画缩略图：代表帧解码 + 后台缓存。

菜单一次展开 100+ 段动画，逐段解码会卡住 GUI。这里把「选代表帧」与
解码/缩放放进最多 2 个线程，结果按 (来源, mtime, 大小, 边长) 缓存在内存
LRU 与临时目录 PNG 里；同一 key 只解码一次。
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QApplication

try:  # 打包环境可能没有 ffmpeg 后端；WebM 缩略图缺失不应影响菜单
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional dependency
    imageio_ffmpeg = None

logger = logging.getLogger("petcore.media.thumbnails")

FRAME_IMAGE_SUFFIXES = frozenset({".png", ".webp", ".jpg", ".jpeg"})
REPRESENTATIVE_FRACTION = 0.62
THUMBNAIL_MAX_SIDE = 64
CACHE_LIMIT = 128
MAX_THREADS = 2
def _disk_cache_dir() -> Path:
    """缩略图磁盘缓存：按 `--instance` 隔离，避免两个实例共用/互相清缓存。"""
    suffix = ""
    try:
        from .. import paths

        name = paths.normalize_instance(os.environ.get("PETCORE_INSTANCE"))
        if name:
            suffix = f"-{name}"
    except Exception:  # noqa: BLE001 - 缓存目录解析失败就用默认
        suffix = ""
    return Path(tempfile.gettempdir()) / f"dsh-pet-core-thumbs{suffix}"


DISK_CACHE_DIR = _disk_cache_dir()


def representative_frame_index(frame_count: int, fraction: float = REPRESENTATIVE_FRACTION) -> int:
    """取后中段的一帧（开头几帧往往和静止画面几乎一样）。"""
    try:
        count = max(1, int(frame_count or 1))
        ratio = float(fraction)
    except (TypeError, ValueError):
        return 0
    return max(0, min(count - 1, int((count - 1) * ratio)))


def _scaled_reader(path: Path, max_side: int) -> QImageReader:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > max_side:
        scale = max_side / float(max(size.width(), size.height()))
        reader.setScaledSize(
            QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
        )
    return reader


def _fit(image: QImage, max_side: int) -> QImage:
    if image.isNull() or max(image.width(), image.height()) <= max_side:
        return image
    return image.scaled(
        max_side,
        max_side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _decode_frameseq(directory: Path, max_side: int) -> QImage:
    try:
        frames = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in FRAME_IMAGE_SUFFIXES
        )
    except OSError:
        return QImage()
    if not frames:
        return QImage()
    target = representative_frame_index(len(frames))
    return _scaled_reader(frames[target], max_side).read()


def _decode_gif(path: Path, max_side: int) -> QImage:
    reader = QImageReader(str(path))
    count = max(1, int(reader.imageCount() or 1))
    target = representative_frame_index(count)
    if target and not reader.jumpToImage(target):
        reader = QImageReader(str(path))
        image = QImage()
        for _index in range(target + 1):
            image = reader.read()
            if image.isNull():
                break
        return image
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > max_side:
        scale = max_side / float(max(size.width(), size.height()))
        reader.setScaledSize(
            QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
        )
    return reader.read()


def _decode_webm(path: Path, max_side: int) -> QImage:
    if imageio_ffmpeg is None:
        return QImage()
    generator = None
    try:
        generator = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgba", bits_per_pixel=32)
        meta = next(generator)
        fps = float(meta.get("fps") or 24.0)
        duration = float(meta.get("duration") or 0.0)
        count = max(1, int(round(fps * duration)))
        target = representative_frame_index(count)
        raw_size = meta.get("size") or meta.get("source_size") or (0, 0)
        width, height = int(raw_size[0]), int(raw_size[1])
        if width <= 0 or height <= 0:
            return QImage()
        expected = width * height * 4
        for index, frame in enumerate(generator):
            if index < target:
                continue
            if len(frame) != expected:
                return QImage()
            image = QImage(frame, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
            return _fit(image, max_side)
    except Exception:
        logger.debug("webm thumbnail decode failed: %s", path, exc_info=True)
        return QImage()
    finally:
        if generator is not None:
            try:
                generator.close()
            except Exception:
                pass
    return QImage()


def decode_thumbnail(spec, max_side: int = THUMBNAIL_MAX_SIDE) -> QImage:
    """解出 ``spec`` 的代表帧（长边 ≤ ``max_side``）；失败返回空 QImage。"""
    if spec is None:
        return QImage()
    try:
        max_side = max(8, int(max_side))
    except (TypeError, ValueError):
        max_side = THUMBNAIL_MAX_SIDE
    directory = getattr(spec, "frameseq_dir", None)
    path = getattr(spec, "path", None)
    if directory is not None:
        image = _decode_frameseq(Path(directory), max_side)
        if not image.isNull():
            return _fit(image, max_side)
        # 帧序列缺失/损坏时退回原始视频或图片。
    if path is None:
        return QImage()
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return _decode_webm(path, max_side)
    if suffix == ".gif":
        return _fit(_decode_gif(path, max_side), max_side)
    return _fit(_scaled_reader(path, max_side).read(), max_side)


def thumbnail_key(spec, max_side: int = THUMBNAIL_MAX_SIDE) -> tuple[str, int, int, int] | None:
    source = getattr(spec, "frameseq_dir", None) or getattr(spec, "path", None)
    if source is None:
        return None
    try:
        stat = Path(source).stat()
    except OSError:
        return None
    return (str(source), int(stat.st_mtime_ns), int(stat.st_size), int(max_side))


def _disk_path(key) -> Path:
    digest = hashlib.sha1("|".join(str(item) for item in key).encode("utf-8")).hexdigest()
    return DISK_CACHE_DIR / f"{digest}.png"


class _DecodeSignals(QObject):
    done = Signal(object, QImage)


class _ThumbnailWorker(QRunnable):
    def __init__(self, key, spec, max_side: int, signals: _DecodeSignals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._key = key
        self._spec = spec
        self._max_side = max_side
        self._signals = signals

    def run(self) -> None:
        image = QImage()
        try:
            image = decode_thumbnail(self._spec, self._max_side)
        except Exception:
            logger.debug("thumbnail decode failed", exc_info=True)
        try:
            self._signals.done.emit(self._key, image)
        except RuntimeError:  # 进程退出时信号对象可能已经没了
            pass


class ThumbnailCache(QObject):
    """进程级缩略图缓存：内存 LRU 128 + 临时目录磁盘缓存 + 2 线程解码。"""

    _instance: "ThumbnailCache | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "ThumbnailCache":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(QApplication.instance())
            return cls._instance

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._memory: OrderedDict = OrderedDict()
        self._callbacks: dict = {}
        self._inflight: set = set()
        # 池不挂在会被 Python 回收的父对象上：退出时不 waitForDone，避免
        # ffmpeg 解码把进程关死。aboutToQuit 只清掉还没开跑的任务。
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(MAX_THREADS)
        self.pool.setExpiryTimeout(1000)
        self._signals = _DecodeSignals(self)
        self._signals.done.connect(self._on_decoded)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    # ------------------------------------------------------------- public
    def request(self, spec, callback, max_side: int = THUMBNAIL_MAX_SIDE) -> None:
        """请求 ``spec`` 的缩略图；命中缓存时同步回调，否则后台解码后回调。

        ``callback`` 收到 ``QPixmap``（在 GUI 线程调用）。
        """
        key = thumbnail_key(spec, max_side)
        if key is None:
            return
        cached = self._memory.get(key)
        if cached is not None:
            self._memory.move_to_end(key)
            self._invoke(callback, cached)
            return
        self._callbacks.setdefault(key, []).append(callback)
        if key in self._inflight:
            return
        disk = self._read_disk(key)
        if not disk.isNull():
            self._store(key, disk)
            self._flush(key)
            return
        self._inflight.add(key)
        self.pool.start(_ThumbnailWorker(key, spec, int(max_side), self._signals))

    def shutdown(self) -> None:
        """退出时丢掉排队任务；不等待正在跑的线程。"""
        try:
            self.pool.clear()
        except RuntimeError:
            pass

    # ------------------------------------------------------------ internal
    def _invoke(self, callback, image: QImage) -> None:
        if callback is None or image.isNull():
            return
        try:
            callback(QPixmap.fromImage(image))
        except RuntimeError:
            logger.debug("thumbnail callback target was deleted", exc_info=True)
        except Exception:
            logger.debug("thumbnail callback failed", exc_info=True)

    def _flush(self, key) -> None:
        callbacks = self._callbacks.pop(key, [])
        image = self._memory.get(key)
        for callback in callbacks:
            self._invoke(callback, image)

    def _store(self, key, image: QImage) -> None:
        self._memory[key] = QImage(image)
        self._memory.move_to_end(key)
        while len(self._memory) > CACHE_LIMIT:
            self._memory.popitem(last=False)

    def _read_disk(self, key) -> QImage:
        try:
            image = QImage(str(_disk_path(key)))
        except Exception:
            return QImage()
        return image

    def _write_disk(self, key, image: QImage) -> None:
        path = _disk_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(path), "PNG")
        except Exception:
            logger.debug("thumbnail disk cache write failed: %s", path, exc_info=True)

    def _on_decoded(self, key, image: QImage) -> None:
        self._inflight.discard(key)
        if image.isNull():
            self._callbacks.pop(key, None)
            return
        self._store(key, image)
        self._write_disk(key, image)
        self._flush(key)


def thumbnail_cache() -> ThumbnailCache:
    return ThumbnailCache.instance()
