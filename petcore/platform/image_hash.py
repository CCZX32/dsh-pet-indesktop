"""画面指纹：64 位 dHash，用来判断「还是同一屏内容」。

主动识屏每 8 秒采样一次前台窗口，绝大多数时候画面没变。dHash 把画面压成
9×8 灰度后逐行比较相邻像素，得到 64 位整数；两张图的 Hamming 距离小于阈值就
当作同一画面，不再发请求（省额度、省费用）。

只依赖 Qt，不引 Pillow：调用方传进 ``QImage``，空图返回 0（调用方按「无法比较」
处理，不会误判成「没变化」）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

HASH_WIDTH = 9
HASH_HEIGHT = 8


def dhash(image: QImage | None) -> int:
    """9×8 灰度差分哈希；空图返回 0。

    先缩到 9×8 再转灰度：两种顺序结果等价，但「先缩」只让 Qt 采样 72 个格子
    （实测 1200×800：9.87 ms → 1.58 ms），灰度转换不再扫整幅 96 万像素。
    缩放用平滑重采样而不是最近邻——最近邻在相邻两帧会因采样位置抖动产生假
    「画面变化」，白白多花额度。
    """
    if image is None or image.isNull():
        return 0
    try:
        small = image.scaled(
            HASH_WIDTH,
            HASH_HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_Grayscale8)
    except (RuntimeError, ValueError):
        return 0
    if small.isNull():
        return 0
    value = 0
    bit = 0
    for y in range(HASH_HEIGHT):
        previous = int(small.pixelColor(0, y).value())
        for x in range(1, HASH_WIDTH):
            current = int(small.pixelColor(x, y).value())
            if current > previous:
                value |= 1 << bit
            previous = current
            bit += 1
    return value


def hamming_distance(first: int, second: int) -> int:
    """两个 64 位指纹的差异位数（0–64）。"""
    return int(first ^ second).bit_count()
