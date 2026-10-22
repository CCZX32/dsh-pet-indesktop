"""品牌图标：DeepSeek 官方鲸鱼（ds_whale.png）与鲸蛙（jingwa.png）。

两个素材都在 ``assets/chat/``（随包分发）。**出场口径**（同主分支）：

- **标题栏**（``ask_window``）：固定 DS logo——「截图问答」四字由它直接顶掉，
  不随机、旁边也不加第二个图标位；素材缺席时才退回那四个字。
- **加载动画**（``ask_window._LoadingFish``）：每次开始等待抽一次，
  ``random.random() < JINGWA_LOADING_CHANCE`` 出鲸蛙，其余 DS logo；整次请求
  保持所选的那一只，不轮播、不每帧重抽。

加载口径：冻结包先查 ``_MEIPASS``，源码树回退到仓库根的 ``assets/chat/``；
**候选按序试到底**——文件在但解码失败（半截下载 / 错格式）要继续试下一个候选，
全部候选都拿不到图才返回空 QPixmap，调用方按「空图 = 不显示图标」处理。
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtGui import QPixmap

__all__ = [
    "JINGWA_LOADING_CHANCE",
    "load_ds_whale",
    "load_jingwa",
    "pick_loading_icon",
]

_CACHE: dict[str, QPixmap] = {}

#: 加载动画抽中鲸蛙的概率（10% 彩蛋，其余一律 DS logo）。
JINGWA_LOADING_CHANCE = 0.1


def _candidates(name: str) -> list[Path]:
    paths: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(Path(meipass) / "assets" / "chat" / name)
    # petcore/ui/screen/brand_icons.py -> 仓库根
    paths.append(Path(__file__).resolve().parents[3] / "assets" / "chat" / name)
    return paths


def _load(name: str) -> QPixmap:
    cached = _CACHE.get(name)
    if cached is not None:
        return cached
    pixmap = QPixmap()
    for path in _candidates(name):
        if not path.is_file():
            continue
        loaded = QPixmap(str(path))
        # 只有解码成功才算找到：冻结包里混进坏图时「文件在」不等于「图能用」。
        if not loaded.isNull():
            pixmap = loaded
            break
    _CACHE[name] = pixmap
    return pixmap


def load_ds_whale() -> QPixmap:
    """DeepSeek 官方鲸鱼图标——品牌主标识。"""
    return _load("ds_whale.png")


def load_jingwa() -> QPixmap:
    """鲸蛙图标——加载动画的 10% 彩蛋。"""
    return _load("jingwa.png")


def pick_loading_icon() -> QPixmap:
    """加载动画的主角：``random.random() < 0.1`` 出鲸蛙，其余 DS logo。

    两只素材都在场才掷骰；只剩一只时它就是答案（缺席的那只不该被掷出来当空帧）；
    都缺席返回空图，调用方回退三点跳动。
    """
    whale = load_ds_whale()
    jingwa = load_jingwa()
    whale_ok, jingwa_ok = not whale.isNull(), not jingwa.isNull()
    if whale_ok and jingwa_ok:
        return jingwa if random.random() < JINGWA_LOADING_CHANCE else whale
    return whale if whale_ok else jingwa
