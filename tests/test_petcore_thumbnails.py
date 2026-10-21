from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from petcore.contracts.content import AnimationSpec
from petcore.engine.enums import AnimatType, GraphType
from petcore.media import thumbnails
from petcore.media.thumbnails import (
    ThumbnailCache,
    decode_thumbnail,
    representative_frame_index,
    thumbnail_key,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_frames(directory: Path, count: int = 3, size=(100, 80)) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        image = QImage(size[0], size[1], QImage.Format.Format_ARGB32)
        image.fill(0xFF000000 | (index * 0x40 << 16))
        assert image.save(str(directory / f"frame_{index:03d}.png"))
    return directory


def _spec(directory: Path, name: str = "anim") -> AnimationSpec:
    return AnimationSpec(
        name=name,
        graph=GraphType.IDEL,
        animat=AnimatType.SINGLE,
        frameseq_dir=directory,
    )


def _wait_for(qapp, predicate, spins: int = 100) -> bool:
    for _ in range(spins):
        qapp.processEvents()
        if predicate():
            return True
        threading.Event().wait(0.01)
    return predicate()


def test_representative_frame_index_boundaries() -> None:
    assert representative_frame_index(0) == 0
    assert representative_frame_index(1) == 0
    assert representative_frame_index(2) == 0
    assert representative_frame_index(3) == 1
    assert representative_frame_index(100) == 61
    assert representative_frame_index(10, fraction=0.0) == 0
    assert representative_frame_index(10, fraction=1.0) == 9
    assert representative_frame_index(10, fraction=2.0) == 9
    assert representative_frame_index(10, fraction=-1.0) == 0
    assert representative_frame_index(-5) == 0


def test_decode_frameseq_thumbnail_uses_the_representative_frame(qapp, tmp_path: Path) -> None:
    directory = _make_frames(tmp_path / "frames", count=3)
    image = decode_thumbnail(_spec(directory))

    assert not image.isNull()
    assert max(image.width(), image.height()) == 64
    assert (image.width(), image.height()) == (64, 51)
    # 3 帧的 62% 是第 2 张（index 1），颜色应为 0x40 红。
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.red() == 0x40


def test_decode_single_image_and_missing_source(qapp, tmp_path: Path) -> None:
    path = tmp_path / "still.png"
    source = QImage(200, 120, QImage.Format.Format_ARGB32)
    source.fill(0xFF30A0FF)
    assert source.save(str(path))
    spec = AnimationSpec(name="still", graph=GraphType.IDEL, animat=AnimatType.SINGLE, path=path)

    image = decode_thumbnail(spec)
    assert not image.isNull()
    assert max(image.width(), image.height()) == 64

    missing = _spec(tmp_path / "nope")
    assert decode_thumbnail(missing).isNull()
    empty = AnimationSpec(name="empty", graph=GraphType.IDEL, animat=AnimatType.SINGLE)
    assert decode_thumbnail(empty).isNull()


def test_thumbnail_key_covers_source_version_and_size(qapp, tmp_path: Path) -> None:
    directory = _make_frames(tmp_path / "frames", count=2)
    spec = _spec(directory)
    key = thumbnail_key(spec)
    assert key is not None
    assert key[0] == str(directory)
    assert key[3] == 64
    assert thumbnail_key(spec, max_side=32)[3] == 32
    no_source = AnimationSpec(name="none", graph=GraphType.IDEL, animat=AnimatType.SINGLE)
    assert thumbnail_key(no_source) is None


def test_cache_decodes_once_off_the_gui_thread_and_reuses_memory(qapp, tmp_path: Path) -> None:
    directory = _make_frames(tmp_path / "cache-frames", count=3)
    spec = _spec(directory, name="cache-anim")
    cache = ThumbnailCache(qapp)
    results: list[QPixmap] = []

    def callback(pixmap) -> None:
        results.append(pixmap)

    cache.request(spec, callback)
    cache.request(spec, callback)  # 同一 key 只解码一次，但两个回调都要收到
    assert cache.pool.waitForDone(5000)
    assert _wait_for(qapp, lambda: len(results) == 2)
    assert all(isinstance(item, QPixmap) for item in results)
    assert not results[0].isNull()
    assert max(results[0].width(), results[0].height()) == 64

    # 内存命中：第三次请求同步回调。
    cache.request(spec, callback)
    assert len(results) == 3


def test_cache_reads_the_disk_cache_on_a_fresh_instance(qapp, tmp_path: Path) -> None:
    directory = _make_frames(tmp_path / "disk-frames", count=2)
    spec = _spec(directory, name="disk-anim")
    first = ThumbnailCache(qapp)
    first.request(spec, lambda pixmap: None)
    assert first.pool.waitForDone(5000)
    disk_path = thumbnails._disk_path(thumbnail_key(spec))
    assert _wait_for(qapp, disk_path.exists), "缩略图应写入磁盘缓存"

    second = ThumbnailCache(qapp)
    results: list[QPixmap] = []
    second.request(spec, results.append)
    assert len(results) == 1, "磁盘缓存命中时必须同步回调"
    assert not results[0].isNull()


def test_thumbnail_cache_is_a_process_singleton(qapp) -> None:
    assert ThumbnailCache.instance() is ThumbnailCache.instance()
    assert thumbnails.thumbnail_cache() is ThumbnailCache.instance()
