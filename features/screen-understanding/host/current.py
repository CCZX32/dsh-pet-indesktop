# -*- coding: utf-8 -*-
"""当前运行期上下文持有器：菜单工厂的两参签名适配（本仓库拓扑）。

上游的菜单工厂拿 ``(menu, handle, config)`` 三参；本仓库的贡献面是
``factory(menu, handle)`` 两参（``pet/mod_menu.py``）。官方识屏包一个进程只有
一个运行期实例（core 角色），挂载时把 ``ScreenRuntimeContext`` 钉在这里，
菜单据此读偏好；卸载/停用由 Runtime 包装器清掉。
"""

from __future__ import annotations

_CURRENT = None


def set_current(context) -> None:
    global _CURRENT
    _CURRENT = context


def clear_current(context=None) -> None:
    global _CURRENT
    if context is None or _CURRENT is context:
        _CURRENT = None


def current_preferences() -> dict:
    context = _CURRENT
    if context is None:
        return {}
    try:
        return context.preferences.read()
    except Exception:
        return {}
