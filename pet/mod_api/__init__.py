"""Versioned public MOD author interfaces. Import an explicit version.

本包**不做任何顶层再导出**（照 :mod:`pet.plugins.__init__` 先例）：导入
``pet.mod_api`` 不得把宿主运行时或 Qt 拉起来，作者必须显式
``from pet.mod_api.v1 import ...``。可用的公开版本见 ``v1``。
"""
