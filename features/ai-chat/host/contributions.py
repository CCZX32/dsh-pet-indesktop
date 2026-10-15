# -*- coding: utf-8 -*-
"""AI 对话包自己的贡献描述（菜单 + 设置）。UI 只在被挂载时才导入。

本仓库拓扑适配（相对上游 DLC 同文件）：

* 定义用 :class:`pet.mod_api.v1.FeatureDefinition`（``mount_contract="mod/v1"``）——
  上游是 ``pet.plugins.feature_host.FeatureDefinition``（无挂载契约），本仓库的
  ``GenericModMounts`` 按 ``mod/v1`` 挂 Runtime，少了这一项包**装得起来但起不来**；
* 菜单工厂是两参 ``(menu, handle)``（``pet/mod_menu.py`` 的面），上游是三参
  ``(menu, handle, config, *, icons)``；
* 命令名 ``chat`` / ``quick_chat`` 由包自己的 Runtime 提供（见
  :mod:`.runtime_mount` 的 ``commands``）——**上游由 Core 的 ``pet/ai_bindings.py``
  用 ``host.attach`` 挂上 Core 的回调**，那条路的前提是"Core 里已经没有内置聊天"。
  本仓库内置聊天不动，包开的是它自己的窗口，所以命令跟着包 Runtime 走；
* 菜单文案带「（包）」后缀：内置 AI 对话与包**并存**，两项必须一眼分得开。
"""

from pet.mod_api.v1 import FeatureDefinition
from pet.plugins.contributions import Contribution
from pet.plugins.ports import CommandNotFound

OWNER = "official.ai-chat"


def _safe(handle):
    try:
        if handle.active:
            return handle.invoke()
    except CommandNotFound:
        return None
    return None


def chat_menu(menu, handle):
    from pet.context_menus.shared import add_action

    return add_action(menu, "AI 对话（包）", "chat", lambda: _safe(handle), close_on_trigger=True)


def quick_menu(menu, handle):
    from pet.context_menus.shared import add_action

    return add_action(menu, "快捷对话（包）", "chat", lambda: _safe(handle), close_on_trigger=True)


def settings_factory(context, parent=None):
    from .contribution_settings import AiContributionSettings

    return AiContributionSettings(context, parent)


def definition():
    from .factory import create_runtime

    return FeatureDefinition(
        OWNER,
        (
            Contribution("chat", "menu", command="chat", group="interaction", factory=chat_menu),
            Contribution("quick_chat", "menu", command="quick_chat", group="interaction", factory=quick_menu),
        ),
        settings_factory,
        runtime_factory=create_runtime,
        allow_in_process=True,
    )
