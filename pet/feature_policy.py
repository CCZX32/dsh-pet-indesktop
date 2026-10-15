# -*- coding: utf-8 -*-
"""本地功能包的策略真相源：API 版本、能力上限、资源上限、验签器装配。零 Qt。

为什么单列一个模块：这几个值有**三个**消费者，而它们不能都 import 到同一处——
宿主侧在 ``pet/feature_management.py``（带 Qt 绑定），作者侧的打包脚本与构建/发布门
在 ``scripts/``（只该拿运行依赖，不该为了两个常量把 Qt 绑定拉起来）。抄第二份的代价
已经出现过一次：``scripts/build_mod_example.py`` 里那份 ``FEATURE_CAPABILITIES``
字面量与 ``pet/feature_management.py`` 的同名常量各说各话。所以这里做成唯一真相源，
由 ``tests/test_feature_packaging_wiring.py`` 的"不许有第二份定义"守卫钉住。

**能力上限是兼容性声明，不是运行期权限**：它只回答"这个包声明的能力有没有超出 Core 的
v1 公开面"（host-only 的功能包与桌宠以相同权限运行，见 ``docs/modding/PORT-STATUS.md``
§一-1 的信任口径）。同理，这里装配出来的是**本地用户自选包**那条口子的验签策略
（``allow_local_packages=True``）：显式用户信任，不是发布者认证，也不是沙箱。
"""

from __future__ import annotations

import sys

from . import __version__
from .plugins.package_trust import FeaturePackageVerifier, VerificationLimits

#: v1 公开面声明的 API 版本（包的清单必须声明它）。
API_VERSION = "1"

#: v1 公开面声明的能力上限（包可以少声明，不能多声明）。
FEATURE_CAPABILITIES = frozenset({"menu.contribute", "settings.contribute"})

#: 资源上限的默认档（与 ``VerificationLimits`` 的默认值同一份；暂存与验签共用，
#: 免得"装的时候一套上限、验的时候另一套"）。
DEFAULT_LIMITS = VerificationLimits()

__all__ = ["API_VERSION", "DEFAULT_LIMITS", "FEATURE_CAPABILITIES", "local_package_verifier", "official_package_verifier"]


def local_package_verifier(feature_id: str, *, platform: str = sys.platform, limits: VerificationLimits = DEFAULT_LIMITS) -> FeaturePackageVerifier:
    """本地用户自选包（显式用户信任）的验签策略——**唯一一份装配**。

    ``platform`` 是**目标平台**，不是"跑这个函数的机器"：构建脚本要在 Linux 上验一份
    为 Linux 声明的包、在 macOS 上验 darwin 那一份，所以由调用方传进来；默认值才是本机。
    ``feature_id`` 由调用方给出（路由读到的 owner，或宿主装配时的 owner）——非法 ID 由
    ``FeaturePackageVerifier`` 自己拒。
    """
    return FeaturePackageVerifier(
        core_version=__version__,
        api_version=API_VERSION,
        platform=platform,
        allowed_capabilities=FEATURE_CAPABILITIES,
        allow_local_packages=True,
        feature_id=feature_id,
        limits=limits,
    )


def official_package_verifier(feature_id: str, *, platform: str = sys.platform, limits: VerificationLimits = DEFAULT_LIMITS) -> FeaturePackageVerifier:
    """官方闭集功能包的验签策略（DLC 识屏包线）：能力上限 = 官方登记，不是本地包上限。

    与 :func:`local_package_verifier` 的差异只在 ``allowed_capabilities``——官方登记
    （``OFFICIAL_FEATURES``）里的 ``screen.capture`` / ``network.http`` 不属于 v1 本地包
    公开面，官方包经这条 Core 自有链声明它们。``allow_local_packages=True`` 是 Phase5A
    的显式用户信任口径（本地激活，不是发布者认证）；官方 id 的 factory/执行形态/能力
    闭集核对在 ``package_trust`` 内部照旧生效。

    当前只接识屏包：AI 包的宿主绑定属聊天包线，这里明确拒绝。
    """
    from .official_features import SCREEN_FEATURE_ID, official_feature

    if feature_id != SCREEN_FEATURE_ID:
        raise ValueError("unsupported official feature")
    registration = official_feature(feature_id)
    return FeaturePackageVerifier(
        core_version=__version__,
        api_version=API_VERSION,
        platform=platform,
        allowed_capabilities=registration.capabilities,
        allow_local_packages=True,
        feature_id=feature_id,
        limits=limits,
    )
