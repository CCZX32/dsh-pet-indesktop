"""清单入口（``mod.json`` 的 ``host/factory.py:create_host``）。

``FeatureManager.import_entrypoint`` 对非 ``__init__.py`` 的入口按**单文件**导入：
模块没有包上下文，直接 ``from .runtime import ...`` 会失败。这里把 host 目录显式
绑定成一个包（``petcore_media_music_host``）再委托 ``host/__init__.py`` 装配，
入口字符串因此保持不变；按包加载（测试里的 ``submodule_search_locations``）时
``__package__`` 已经有值，直接复用。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

#: 绑定 host 目录用的包名：刻意不叫 ``petcore_feature_media_music``（那正是 loader
#: 给单文件入口分配的模块名），免得两套模块互相盖掉。
PACKAGE = "petcore_media_music_host"


def _package_name() -> str:
    package = globals().get("__package__") or ""
    if package:
        return str(package)
    if sys.modules.get(PACKAGE) is not None:
        return PACKAGE
    host_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        host_dir / "__init__.py",
        submodule_search_locations=[str(host_dir)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {host_dir / '__init__.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return PACKAGE


def create_host(context):
    return importlib.import_module(_package_name()).create_host(context)
