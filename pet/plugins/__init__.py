# -*- coding: utf-8 -*-
"""包信任层 + 功能扩展宿主运行时。

``package_trust`` 是**包信任**（签名/清单/指纹/路径边界校验），零 Qt、零宿主依赖。
D2 第一片起，本包还承载功能扩展**宿主运行时**：
``capabilities`` / ``ports`` / ``contributions`` / ``feature_host``（进程级注册表与
状态机）、``feature_packages``（从**已验签字节**装载 host 代码）、
``package_binding``（把已验签版本绑进宿主）、``worker_launch``（已验签版本 →
子进程启动授权）。Phase 2 内核移植再加 ``events``（CoreEventBus：owner 隔离的
同步事件总线，由 ``feature_host`` 接进启停/故障生命周期）。

本文件仍然**不做任何顶层再导出**：导入 ``pet.plugins`` 不得把宿主运行时或 Qt
拉起来——需要哪一个就显式 ``from pet.plugins.feature_host import ...``。
"""

from __future__ import annotations

__all__: list[str] = []
