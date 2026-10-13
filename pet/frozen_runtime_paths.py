# -*- coding: utf-8 -*-
"""冻结版 onedir 依赖目录的本地查找；没有源码/PYTHONPATH 回退。

逐字移植自 DLC 分支的 ``pet/frozen_runtime_paths.py``（S4 补齐 S3 登记的冻结态
缺口 #1）。它只解决一件事：**CPython 的 FileFinder 可能找不到超长路径下的
``.pyd``**——即使用长路径感知的冻结执行文件也一样。

为什么会这样（本机实测，原始输出见 ``.scratch/dlc-fusion/S4-HANDOFF.md``）：
Windows 上目录总长超过 MAX_PATH 时，``import`` 纯 ``.py`` 仍然成功（FileFinder
走的是 ``_wstat``，能拿到短名归一化结果），但 ``.pyd`` 走
``LoadLibrary`` 那条路会以 ``ERROR_FILENAME_EXCED_RANGE``（文件名或扩展名太长）
失败。实测：267 字符目录里的扩展模块直接 import ⇒
``ImportError: DLL load failed while importing …: 文件名或扩展名太长。``；
同一目录改用 ``\\\\?\\`` 扩展拼写放进 ``sys.path`` ⇒ 正常导入。

为什么它属于探针缺陷：探针模式（``--feature-package-probe``）的第一步就是
``import _dsh_probe_native``（``pet/workers/screen_entry.py``）。该 ``.pyd`` 只
存在于冻结版的密封依赖目录里；安装路径一长它就找不到 ⇒ ``sandbox_enforced()``
恒 False ⇒ 探针恒 77 ⇒ 上游报 ``worker_probe_failed``。

纪律（与 DLC 相同）：

* **只动**执行文件自己那个 ``_internal`` 目录，**不碰** PYZ 优先级（冻结版的
  ``PyiFrozenFinder`` 在 ``sys.meta_path`` 上，与 ``sys.path`` 顺序无关）；
* 只接受本机盘符的绝对路径，UNC / 设备命名空间 / 盘符相对路径 / 含 ``.`` 与
  ``..`` 的布局一律抛 :class:`ValueError`——宁可让调用方炸出来，也不把一条
  没被证明的路径塞进 ``sys.path``；
* 归一化后再比对，``_MEIPASS`` 本身已经带 ``\\\\?\\`` 时**不**拼出双前缀。

**与 DLC 原文的一处有意偏离（本机实测驱动）**：DLC 一律 ``sys.path.append``。
实测（Windows 11 / Python 3.13.7，输出见 S4-HANDOFF）——普通拼写的长目录**已经**
在 ``sys.path`` 里时，FileFinder 的 ``stat`` 会**成功**（所以它认定"这个模块在这
个目录里"），随后 ``LoadLibrary`` 才以"文件名或扩展名太长"失败；importlib 不会因为
加载失败就退到后面那条 path 条目。于是"追加扩展拼写"在那种布局下**等于没改**：
``['plain', 'extended']`` ⇒ 仍然 ``ImportError: 文件名或扩展名太长``；
``['extended', 'plain']`` 与 ``['extended']`` ⇒ 正常导入。
所以本实现在**普通拼写已在** ``sys.path`` 里时**就地替换**它，缺席时才追加。

本模块是子进程路由的一部分：零 Qt、零第三方依赖（只用 ``ntpath`` + ``sys``）。
"""
from __future__ import annotations

import ntpath
import sys

#: 相对于执行文件目录的密封依赖目录名（PyInstaller onedir 的固定布局）。
DEPENDENCY_DIRECTORY = "_internal"

#: 布局校验失败时的固定错误文案（调用方按此判定，不解析细节）。
LAYOUT_ERROR = "frozen_runtime_layout"


def _local_absolute(path: str) -> tuple[str, str]:
    """把一条路径拆成 ``(盘符, 尾部)``，顺带拒绝所有非本机盘符的绝对形态。"""
    drive, tail = ntpath.splitdrive(path)
    if len(drive) != 2 or drive[1] != ":" or not tail.startswith("\\") or any(part in (".", "..") for part in tail.split("\\")):
        raise ValueError(LAYOUT_ERROR)
    return drive, tail


def activate_frozen_dependency_path() -> bool:
    """让执行文件自己的密封依赖目录以**扩展拼写**排在 ``sys.path`` 前面。

    普通拼写已经在 ``sys.path`` 里时**就地替换**（见模块 docstring 的实测依据：
    加载失败不会退到后面那条 path 条目）；缺席时追加。重复调用幂等。

    :returns: ``True`` = 本次真的改了 ``sys.path``；``False`` = 不需要动（源码
        运行、非 Windows、或已经是扩展拼写）。

    :raises ValueError: 冻结布局与 onedir 约定不符（``LAYOUT_ERROR``）。
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    root = getattr(sys, "_MEIPASS", None)
    executable = sys.executable
    if not isinstance(root, str) or not isinstance(executable, str):
        raise ValueError(LAYOUT_ERROR)
    # Win32 extended spelling must designate the same local drive, never UNC,
    # device namespaces or a different dependency root.
    root = root[4:] if root.startswith("\\\\?\\") else root
    executable = executable[4:] if executable.startswith("\\\\?\\") else executable
    for path in (root, executable):
        _local_absolute(path)
    expected = ntpath.join(ntpath.dirname(executable), DEPENDENCY_DIRECTORY)
    if ntpath.normcase(ntpath.normpath(root)) != ntpath.normcase(expected):
        raise ValueError(LAYOUT_ERROR)
    extended = "\\\\?\\" + ntpath.normpath(root)
    if extended in sys.path:
        return False
    folded = ntpath.normcase(ntpath.normpath(root))
    for index, entry in enumerate(sys.path):
        if isinstance(entry, str) and ntpath.normcase(ntpath.normpath(entry)) == folded:
            sys.path[index] = extended
            return True
    sys.path.append(extended)
    return True


__all__ = ["DEPENDENCY_DIRECTORY", "LAYOUT_ERROR", "activate_frozen_dependency_path"]
