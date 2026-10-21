"""自言自语/点击台词共用的配图池与抽取规则（核心逻辑，无功能包依赖）。"""

from __future__ import annotations

import random
from pathlib import Path

from .. import paths

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
DEFAULT_IMAGE_DIR = "big_blue_fat_fish"


def builtin_image_dir() -> Path:
    return paths.legacy_asset_root() / DEFAULT_IMAGE_DIR


def resolve_image_dir(raw) -> Path:
    text = str(raw or "").strip()
    if not text:
        return builtin_image_dir()
    directory = Path(text).expanduser()
    if not directory.is_absolute():
        directory = paths.legacy_asset_root().parent / directory
    return directory


def image_files(directory: Path) -> list[Path]:
    """按后缀筛选图片（不读内容；给 --check 这类无 Qt 路径用）。"""
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    return [
        path
        for path in entries
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]


def readable_images(directory: Path) -> list[Path]:
    """在 :func:`image_files` 基础上再用 QImageReader 过滤不可读文件。"""
    try:
        from PySide6.QtGui import QImageReader
    except Exception:
        return image_files(directory)
    images: list[Path] = []
    for path in image_files(directory):
        try:
            if QImageReader(str(path)).canRead():
                images.append(path)
        except Exception:
            continue
    return images


def configured_images(config) -> tuple[Path, list[Path]]:
    """返回 (实际使用的目录, 可读图片)；配置目录无图时回退内置目录。"""
    directory = resolve_image_dir(config.get("self_talk_image_dir") if config else "")
    images = readable_images(directory)
    fallback = builtin_image_dir()
    if not images and directory != fallback:
        images = readable_images(fallback)
        if images:
            return fallback, images
    return directory, images


def image_chance(config, default: int = 30) -> int:
    try:
        value = float(config.get("self_talk_image_chance", default))
    except (TypeError, ValueError):
        return default
    return int(max(0.0, min(100.0, value)))


def image_scale(config, default: int = 100) -> int:
    try:
        value = float(config.get("self_talk_image_scale", default))
    except (TypeError, ValueError):
        return default
    return int(max(50.0, min(300.0, value)))


def pick_choice(
    rng: random.Random,
    texts,
    images,
    chance: int,
) -> tuple[str, object] | None:
    """先决定这次出图还是出文字，再在对应池里等权抽取。

    与主分支 ``pick_self_talk_choice`` 同口径：图片池为空只出文字、文字池为空只
    出图；两边都空返回 None。百分比就是真实出图概率（100 = 只出图）。
    """
    clean_texts = [str(text) for text in (texts or []) if str(text).strip()]
    image_list = list(images or [])
    if not clean_texts and not image_list:
        return None
    if not image_list:
        return ("text", rng.choice(clean_texts))
    if not clean_texts:
        return ("image", rng.choice(image_list))
    if rng.random() * 100.0 < max(0.0, min(100.0, float(chance))):
        return ("image", rng.choice(image_list))
    return ("text", rng.choice(clean_texts))
