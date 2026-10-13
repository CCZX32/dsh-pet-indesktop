# -*- coding: utf-8 -*-
"""冻结版 onedir 依赖目录的长路径查找（S4 冻结态缺口补齐）。

本文件是 ``pet/frozen_runtime_paths.py`` 的行为门。它守的是一条**实测过**的
Windows 事实：目录总长超过 MAX_PATH 时，CPython 能 import 纯 ``.py``，但
``LoadLibrary`` 加载 ``.pyd`` 会以 ``ERROR_FILENAME_EXCED_RANGE``（文件名或
扩展名太长）失败；只有把 ``\\\\?\\`` 扩展拼写的目录放进 ``sys.path`` 才能拿到
那个扩展模块。复现脚本与修复前/后原始输出见
``.scratch/dlc-fusion/S4-HANDOFF.md``。

为什么重要：探针模式（``--feature-package-probe``）的第一步就是
``import _dsh_probe_native``。这个 ``.pyd`` 只存在于冻结版密封依赖目录里，
路径一长就找不到 ⇒ ``sandbox_enforced()`` 恒 False ⇒ 探针恒 77 ⇒
``worker_probe_failed``。
"""
from __future__ import annotations

import sys

import pytest

from pet import frozen_runtime_paths


@pytest.fixture(autouse=True)
def _restore_sys_path():
    """``sys.path`` 是进程级单例：每个用例跑完必须还原成原样。"""
    snapshot = list(sys.path)
    yield
    sys.path[:] = snapshot


def _frozen(monkeypatch, tmp_path, *, meipass="auto", executable="auto"):
    """把进程装成一台冻结版 onedir 安装，返回 ``(exe, root)``。

    ``meipass`` / ``executable`` 显式给值可绕过默认拼装，用于造出"布局对不上"
    的坏样本。
    """
    exe = tmp_path / "App" / "dsh-pet-core-webm.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    root = exe.parent / "_internal"
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe) if executable == "auto" else executable)
    monkeypatch.setattr(sys, "_MEIPASS", str(root) if meipass == "auto" else meipass, raising=False)
    return exe, root


def test_source_run_never_touches_sys_path(monkeypatch, tmp_path):
    """源码运行（没有 sys.frozen）：这是绝大多数开发/测试现场，必须零副作用。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    before = list(sys.path)
    assert frozen_runtime_paths.activate_frozen_dependency_path() is False
    assert sys.path == before


def test_non_windows_frozen_run_never_touches_sys_path(monkeypatch, tmp_path):
    """非 Windows 的冻结版（macOS/Linux onedir 不用这套 Win32 扩展拼写）。"""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    before = list(sys.path)
    assert frozen_runtime_paths.activate_frozen_dependency_path() is False
    assert sys.path == before


def test_frozen_onedir_appends_the_extended_spelling_of_the_sealed_directory(monkeypatch, tmp_path):
    """正常 onedir 布局：把 ``\\\\?\\<exe 目录>/_internal`` 追加进 sys.path。"""
    _exe, root = _frozen(monkeypatch, tmp_path)
    extended = "\\\\?\\" + str(root)
    assert extended not in sys.path
    assert frozen_runtime_paths.activate_frozen_dependency_path() is True
    assert sys.path[-1] == extended


def test_activation_is_idempotent(monkeypatch, tmp_path):
    """第二次调用不得重复追加（worker 可能走多条入口路径）。"""
    _frozen(monkeypatch, tmp_path)
    assert frozen_runtime_paths.activate_frozen_dependency_path() is True
    count = sys.path.count("\\\\?\\" + str(tmp_path / "App" / "_internal"))
    assert frozen_runtime_paths.activate_frozen_dependency_path() is False
    assert sys.path.count("\\\\?\\" + str(tmp_path / "App" / "_internal")) == count == 1


def test_the_plain_spelling_is_replaced_in_place_not_appended_after_it(monkeypatch, tmp_path):
    """普通拼写已经在 ``sys.path`` 里时，必须**就地替换**。

    这是本实现与 DLC 原文的唯一有意偏离，依据是本机实测：FileFinder 的 stat 在
    长路径上会成功，于是它认定"模块就在这里"，随后 ``LoadLibrary`` 才失败，而
    importlib **不会**因为加载失败退到后面那条 path 条目。所以"追加"在
    ``['plain', 'extended']`` 这种布局下等于没改。
    """
    _exe, root = _frozen(monkeypatch, tmp_path)
    plain, extended = str(root), "\\\\?\\" + str(root)
    sys.path.insert(3, plain)
    assert frozen_runtime_paths.activate_frozen_dependency_path() is True
    assert sys.path[3] == extended
    assert plain not in sys.path
    assert sys.path.count(extended) == 1


def test_an_unrelated_path_entry_is_left_alone(monkeypatch, tmp_path):
    """只动那一格：其它 path 条目（含 ``''`` 与 zip 条目）原样保留。"""
    _exe, root = _frozen(monkeypatch, tmp_path)
    others = ["", str(tmp_path / "extra.zip"), "C:\\elsewhere"]
    sys.path[:0] = others
    assert frozen_runtime_paths.activate_frozen_dependency_path() is True
    assert sys.path[: len(others)] == others


def test_an_already_extended_meipass_is_normalized_not_duplicated(monkeypatch, tmp_path):
    """``_MEIPASS`` 本身带扩展前缀时，先归一化再比对，避免拼出双前缀。"""
    _exe, root = _frozen(monkeypatch, tmp_path, meipass="\\\\?\\" + str(tmp_path / "App" / "_internal"))
    assert frozen_runtime_paths.activate_frozen_dependency_path() is True
    assert sys.path[-1] == "\\\\?\\" + str(root)
    assert not any(entry.startswith("\\\\?\\\\\\?\\") for entry in sys.path)


@pytest.mark.parametrize(
    "meipass",
    [
        None,
        "",
        "relative/_internal",
        "\\\\server\\share\\_internal",
        "\\\\?\\UNC\\server\\share\\_internal",
        "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\_internal",
        "C:relative\\_internal",
    ],
)
def test_a_layout_that_is_not_the_executables_own_dependency_directory_is_refused(monkeypatch, tmp_path, meipass):
    """布局对不上就抛错，绝不把任意路径塞进 ``sys.path``（那等于关掉 PYZ 优先级）。

    拒绝面：相对路径、UNC、设备命名空间、盘符相对路径、与 exe 不同根的绝对路径。
    """
    _frozen(monkeypatch, tmp_path, meipass=meipass)
    before = list(sys.path)
    with pytest.raises(ValueError, match="frozen_runtime_layout"):
        frozen_runtime_paths.activate_frozen_dependency_path()
    assert sys.path == before


def test_a_sibling_directory_that_is_not_internal_is_refused(monkeypatch, tmp_path):
    """邻居目录（例如 ``<exe 目录>/feature-probe``）不是本函数的目标。"""
    _exe, root = _frozen(monkeypatch, tmp_path)
    sibling = root.parent / "feature-probe"
    sibling.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(sibling), raising=False)
    with pytest.raises(ValueError, match="frozen_runtime_layout"):
        frozen_runtime_paths.activate_frozen_dependency_path()


def test_an_exe_at_a_different_root_is_refused(monkeypatch, tmp_path):
    """``_MEIPASS`` 指向另一个盘的 ``_internal`` 时不得放行。"""
    other = tmp_path / "Other" / "App"
    other.mkdir(parents=True)
    (other / "_internal").mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "App" / "dsh-pet-core-webm.exe"))
    (tmp_path / "App" / "_internal").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(other / "_internal"), raising=False)
    with pytest.raises(ValueError, match="frozen_runtime_layout"):
        frozen_runtime_paths.activate_frozen_dependency_path()


def test_dot_segments_are_refused(monkeypatch, tmp_path):
    """含 ``.`` / ``..`` 段的布局一律拒绝（可能是拼接错误，也可能是穿越尝试）。"""
    _frozen(monkeypatch, tmp_path, meipass=str(tmp_path / "App" / "sub" / ".." / "_internal"))
    with pytest.raises(ValueError, match="frozen_runtime_layout"):
        frozen_runtime_paths.activate_frozen_dependency_path()
