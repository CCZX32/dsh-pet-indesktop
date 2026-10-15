# -*- coding: utf-8 -*-
"""品牌图标对：DeepSeek 鲸鱼（ds_whale.png）与鲸蛙（jingwa.png）。

两个素材都在 ``assets/chat/``（随包分发）。这对图标在产品里**互相出场**：
截图问答标题栏的图标每次开新会话随机二选一；加载动画里两者轮流浮动。
本模块只负责加载与抽取，不做任何缓存之外的状态。

加载口径与 ``result_panel._load_whale`` 相同：冻结包先查 ``_MEIPASS``，
源码树回退到仓库根的 ``assets/chat/``；文件缺失或解码失败返回空 QPixmap，
调用方按"空图 = 不显示图标"处理（绝不让图标自己成为故障点）。
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtGui import QPixmap

_CACHE: dict[str, QPixmap] = {}

#: 鲸蛙在菜单里的身份：右键菜单「截图」入口的图标（用户点单：鲸蛙为菜单）。
JINGWA_MENU_ICON = "jingwa"


def _load(name: str) -> QPixmap:
    if name in _CACHE:
        return _CACHE[name]
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "chat" / name)
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "chat" / name)
    pixmap = QPixmap()
    for path in candidates:
        if path.is_file():
            loaded = QPixmap(str(path))
            if not loaded.isNull():
                pixmap = loaded
            break
    _CACHE[name] = pixmap
    return pixmap


def load_ds_whale() -> QPixmap:
    """DeepSeek 官方鲸鱼图标（simple-icons CC0 渐变蓝 PNG）。"""
    return _load("ds_whale.png")


def load_jingwa() -> QPixmap:
    """鲸蛙图标（用户供图：去水印、洪水填充去白底）。"""
    return _load("jingwa.png")


def pick_brand_icon() -> QPixmap:
    """两个品牌图标随机二选一（各 50%）。

    两者都缺席时返回空图（调用方不显示图标）；只有一个在场时它就是答案
    （不掷骰——另一个缺席时"随机"没有意义）。
    """
    whale = load_ds_whale()
    jingwa = load_jingwa()
    whale_ok, jingwa_ok = not whale.isNull(), not jingwa.isNull()
    if whale_ok and jingwa_ok:
        return whale if random.random() < 0.5 else jingwa
    return whale if whale_ok else jingwa
