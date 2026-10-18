# -*- coding: utf-8 -*-
"""官方功能包的本地来源解析（源码态构建缓存 / 冻结态随包目录）。

本仓库的官方包由 Core 自有链装配（``LocalFeatureRuntime.attach_official``），
不经过本地 ZIP 路由；但安装仍需要一个**已构建**的包根。这个模块只回答
"到哪里找/能不能现构建"：

* 冻结态：``<exe 目录>/features/<owner 或短名>/``（D4 构建脚本的落点）；
* 源码态：``<data>/official-packages/<短名>/`` 缓存；不存在时按需调用
  ``scripts/build_{screen,ai_chat}_package.py`` 构建一次；
* 显式覆盖：``PET_OFFICIAL_PACKAGE_ROOT``（开发/测试用）。

找不到或构建失败都返回 ``invalid/absent`` + 可照做的原因，不静默。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .official_features import (
    ACCOUNT_USAGE_FEATURE_ID,
    AI_FEATURE_ID,
    MUSIC_FEATURE_ID,
    OFFICIAL_FEATURES,
    SCREEN_FEATURE_ID,
    VOICE_CHIME_FEATURE_ID,
)

_DISPLAY = {
    SCREEN_FEATURE_ID: "屏幕理解",
    AI_FEATURE_ID: "AI 对话",
    ACCOUNT_USAGE_FEATURE_ID: "账户用量",
    MUSIC_FEATURE_ID: "音乐启动器",
    VOICE_CHIME_FEATURE_ID: "语音报时",
}

_SHORT = {
    SCREEN_FEATURE_ID: "screen-understanding",
    AI_FEATURE_ID: "ai-chat",
    ACCOUNT_USAGE_FEATURE_ID: "account-usage",
    MUSIC_FEATURE_ID: "music",
    VOICE_CHIME_FEATURE_ID: "voice-chime",
}

_BUILDERS = {
    SCREEN_FEATURE_ID: ("scripts.build_screen_package", "features/screen-understanding"),
    AI_FEATURE_ID: ("scripts.build_ai_chat_package", "features/ai-chat"),
    ACCOUNT_USAGE_FEATURE_ID: ("scripts.build_account_usage_package", "features/account-usage"),
    MUSIC_FEATURE_ID: ("scripts.build_music_package", "features/music"),
    VOICE_CHIME_FEATURE_ID: ("scripts.build_voice_chime_package", "features/voice-chime"),
}


@dataclass(frozen=True)
class OfficialPackageSource:
    owner: str
    status: str  # found | absent | invalid
    path: Path | None = None
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.status == "found" and self.path is not None


def official_display_name(owner: str) -> str:
    return _DISPLAY.get(str(owner), str(owner))


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _frozen_root() -> Path:
    return Path(sys.executable).resolve().parent / "features"


def _candidate_names(owner: str) -> tuple[str, ...]:
    short = _SHORT.get(owner, owner.rsplit(".", 1)[-1])
    return (owner, short)


def _find_in(root: Path, owner: str) -> Path | None:
    for name in _candidate_names(owner):
        directory = root / name
        if (directory / "manifest.json").is_file():
            return directory
        archive = root / f"{name}.zip"
        if archive.is_file():
            return archive
    return None


def _build_source(owner: str, output_root: Path) -> OfficialPackageSource:
    import importlib

    try:
        module_name, source_relative = _BUILDERS[owner]
    except KeyError:
        return OfficialPackageSource(owner, "absent", reason="这个官方包没有源码态构建入口")
    source = _repository_root() / source_relative
    if not (source / "mod.json").is_file():
        return OfficialPackageSource(owner, "absent", reason=f"缺少官方包源码树：{source_relative}")
    output = output_root / _SHORT[owner]
    if output.exists() or output.with_suffix(".zip").exists():
        return OfficialPackageSource(owner, "found", output)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        builder = importlib.import_module(module_name)
        result = builder.build_package(source, output)
    except Exception as exc:  # 构建失败如实回报，不猜
        return OfficialPackageSource(owner, "invalid", reason=f"官方包构建失败：{exc}")
    return OfficialPackageSource(owner, "found", Path(result))


def resolve_official_package(
    owner: str,
    *,
    root: Path | str | None = None,
    config_dir: Path | str | None = None,
    allow_build: bool = True,
) -> OfficialPackageSource:
    """定位一个官方包根；``root``/环境变量优先于默认位置。"""
    owner = str(owner)
    if owner not in OFFICIAL_FEATURES:
        return OfficialPackageSource(owner, "invalid", reason="不是官方登记的包 ID")

    explicit = root if root is not None else os.environ.get("PET_OFFICIAL_PACKAGE_ROOT")
    if explicit:
        found = _find_in(Path(explicit), owner)
        if found is not None:
            return OfficialPackageSource(owner, "found", found)
        if not allow_build:
            return OfficialPackageSource(owner, "absent", reason=f"目录里没有这个官方包：{explicit}")

    if getattr(sys, "frozen", False):
        found = _find_in(_frozen_root(), owner)
        if found is not None:
            return OfficialPackageSource(owner, "found", found)
        return OfficialPackageSource(owner, "absent", reason=f"随包目录里没有这个官方包：{_frozen_root()}")

    if config_dir is not None:
        cache = Path(config_dir) / "official-packages"
        found = _find_in(cache, owner)
        if found is not None:
            return OfficialPackageSource(owner, "found", found)
        if allow_build:
            return _build_source(owner, cache)
        return OfficialPackageSource(owner, "absent", reason="官方包尚未构建")

    return OfficialPackageSource(owner, "absent", reason="没有可用的官方包来源")


__all__ = [
    "OfficialPackageSource",
    "official_display_name",
    "resolve_official_package",
]
