# -*- coding: utf-8 -*-
"""账户用量包的贡献描述：一个菜单项 + 一个设置面板。

菜单命令由包自己的 Runtime 提供（``usage``）；设置面板走 MOD 中心的
``settings.contribute`` 通道，内置余额查询不动，两项并存。
"""

from __future__ import annotations

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.account-usage"


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def usage_menu(menu, handle):
    from pet.context_menus.shared import add_action

    return add_action(menu, "账户用量（包）", "account_usage", lambda: _safe(handle), close_on_trigger=True)


def settings_factory(context, parent=None):
    from .contribution_settings import AccountUsageSettings

    return AccountUsageSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        (Contribution("usage", "menu", command="usage", group="interaction", factory=usage_menu),),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
