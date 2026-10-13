# -*- coding: utf-8 -*-
"""官方功能包验签层。

本仓库的 ``pet/plugins/`` 只承载**包信任**（``package_trust``）：签名/清单/指纹
/路径边界校验，零 Qt、零宿主依赖。DLC 分支的 ``pet/plugins/`` 还含插件运行时
（``feature_host``/``feature_packages``/``package_binding``/``ports`` 等），
那是功能扩展宿主运行时，不在本片范围内，未移植——所以本文件**不做任何顶层再导出**：
导入本包不应把功能扩展宿主的任何依赖拉起来。
"""

from __future__ import annotations

__all__: list[str] = []
