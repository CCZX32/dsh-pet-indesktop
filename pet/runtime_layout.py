# -*- coding: utf-8 -*-
"""运行时数据布局：普通安装 / 显式便携。

普通安装与绿色包把配置、会话、插件、缓存放在平台数据目录
（Windows：``%APPDATA%/dsh-pet-standalone-<variant>``，见
:func:`pet.config._default_base`）。显式便携**只认一个身份**：exe 同目录的
``portable.json``。标记存在时，app 数据根解析到标记指定的相对目录，绝不静默
回退平台目录——否则用户以为数据在便携目录里，实际写回了 ``%APPDATA%``。

标记格式（canonical）：:

    {"schema":"dsh-pet-portable/v1","data":"data"}

``data`` 是相对 exe 目录的路径，解析后必须仍在 exe 目录内；v1 只支持 NTFS
（Windows），目标不可写、是 reparse point（junction/symlink）、或中间段逃出
exe 目录都直接报错。首版不支持 exFAT/FAT。

便携模式不动这些 OS 级契约（它们本来就不属于 app 数据）：开机自启登记项、
DSH 桥接目录（``<APPDATA>/dsh-pet-bridge``，由外部 DSH 插件读取）、Qt 的
``QStandardPaths`` 文档/应用数据位置。
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PORTABLE_MARKER = "portable.json"
PORTABLE_SCHEMA = "dsh-pet-portable/v1"
DEFAULT_DATA_DIR = "data"


class PortableLayoutError(RuntimeError):
    """``portable.json`` 存在但不可用（内容、路径或文件系统不满足）。"""


@dataclass(frozen=True)
class PortableLayout:
    exe_dir: Path
    data_dir: Path

    @property
    def marker_path(self) -> Path:
        return self.exe_dir / PORTABLE_MARKER


def executable_dir() -> Path:
    """exe 所在目录；源码运行时是仓库根（便于开发时手动放标记验证）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parents[1]


def canonical_marker_text() -> str:
    """构建脚本写进便携 zip 的 canonical 标记（与读取端共用一份定义）。"""
    return json.dumps(
        {"schema": PORTABLE_SCHEMA, "data": DEFAULT_DATA_DIR},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _is_reparse_point(path: Path) -> bool:
    """symlink / Windows junction / 其它 reparse point。"""
    try:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _filesystem_name(path: Path) -> str:
    """所在卷的文件系统名；Windows 之外或查询失败时返回空串。"""
    if os.name != "nt":
        return ""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        volume = ctypes.create_unicode_buffer(261)
        name = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        if not kernel32.GetVolumePathNameW(str(path), volume, 261):
            return ""
        if not kernel32.GetVolumeInformationW(
            volume.value, name, 261, None, None, None, filesystem, 261
        ):
            return ""
        return filesystem.value
    except Exception:
        return ""


def _reject_reparse_below(root: Path, target: Path) -> None:
    """目标路径与 root 之间任何已存在的段都不许是 reparse point。"""
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise PortableLayoutError(
                f"便携数据目录不能是链接/junction：{current}"
            )


def _probe_writable(directory: Path) -> None:
    try:
        handle, probe = tempfile.mkstemp(prefix=".dsh-pet-write-", dir=directory)
    except OSError as exc:
        raise PortableLayoutError(f"便携数据目录不可写：{directory}（{exc}）") from exc
    os.close(handle)
    try:
        os.unlink(probe)
    except OSError:
        pass


def read_portable_layout(exe_dir: Path | str) -> PortableLayout | None:
    """解析 ``<exe_dir>/portable.json``；没有标记返回 None，标记不可用即报错。

    校验顺序：标记形态 → JSON/schema → 相对路径 → 解析后仍在 exe 目录内 →
    无 reparse 段 → NTFS（Windows）→ 创建数据目录 → 可写探针。
    """
    root = Path(exe_dir)
    marker = root / PORTABLE_MARKER
    # 没有标记就不做任何路径解析：安装态的启动/缓存热路径不该为一个不存在的
    # 文件付 resolve 的系统调用（tests/test_click_sound.py 钉了这条）。
    if not marker.exists() and not marker.is_symlink():
        return None
    try:
        root = root.resolve(strict=False)
    except OSError as exc:
        raise PortableLayoutError(f"无法解析程序目录：{exe_dir}（{exc}）") from exc
    if not root.is_dir():
        raise PortableLayoutError(f"程序目录不存在：{root}")

    marker = root / PORTABLE_MARKER
    if _is_reparse_point(marker):
        raise PortableLayoutError(f"便携标记不能是链接/junction：{marker}")
    if not marker.is_file():
        raise PortableLayoutError(f"便携标记不是普通文件：{marker}")

    try:
        text = marker.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PortableLayoutError(f"无法读取便携标记：{marker}（{exc}）") from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise PortableLayoutError(f"便携标记不是合法 JSON：{marker}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise PortableLayoutError(f"便携标记必须是 JSON 对象：{marker}")
    if payload.get("schema") != PORTABLE_SCHEMA:
        raise PortableLayoutError(
            f"便携标记 schema 必须是 {PORTABLE_SCHEMA!r}：{marker}"
        )

    raw = payload.get("data")
    if not isinstance(raw, str) or not raw.strip():
        raise PortableLayoutError(f"便携标记缺少 data 相对目录：{marker}")
    raw = raw.strip()
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        raise PortableLayoutError(f"便携 data 必须是相对路径：{raw!r}")
    parts = [part for part in raw.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PortableLayoutError(f"便携 data 不能包含 ..：{raw!r}")

    data_dir = root.joinpath(*parts).resolve(strict=False)
    if not data_dir.is_relative_to(root):
        raise PortableLayoutError(f"便携 data 逃出程序目录：{raw!r} → {data_dir}")

    _reject_reparse_below(root, data_dir)
    filesystem = _filesystem_name(root)
    if os.name == "nt":
        # 失败即拒绝：查不到卷信息时不能当成"大概是 NTFS"放行（v1 明确只支持
        # NTFS；网络盘/异常挂载应当在启动期报出来，而不是运行中写坏数据）。
        if not filesystem:
            raise PortableLayoutError(f"无法确认便携目录所在卷的文件系统：{root}")
        if filesystem.upper() != "NTFS":
            raise PortableLayoutError(
                f"便携模式首版只支持 NTFS，当前卷是 {filesystem}：{root}"
            )

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PortableLayoutError(f"无法创建便携数据目录：{data_dir}（{exc}）") from exc
    if not data_dir.is_dir():
        raise PortableLayoutError(f"便携数据目录不是目录：{data_dir}")
    if _is_reparse_point(data_dir):
        raise PortableLayoutError(f"便携数据目录不能是链接/junction：{data_dir}")

    _probe_writable(data_dir)
    return PortableLayout(exe_dir=root, data_dir=data_dir)


_UNSET: object = object()
_LAYOUT_CACHE: object = _UNSET


def reset_layout_cache() -> None:
    """测试与运行时布局切换用的缓存复位。"""
    global _LAYOUT_CACHE
    _LAYOUT_CACHE = _UNSET


def portable_layout() -> PortableLayout | None:
    """进程内只解析一次（标记与目录在运行期不换）。"""
    global _LAYOUT_CACHE
    if _LAYOUT_CACHE is _UNSET:
        _LAYOUT_CACHE = read_portable_layout(executable_dir())
    return _LAYOUT_CACHE  # type: ignore[return-value]


def portable_active() -> bool:
    return portable_layout() is not None


def app_data_dir(default_base: Path | str | None = None) -> Path:
    """app 数据根（配置/会话/日志/插件/缓存都从它派生）。

    便携：标记指定的目录本身（不再附加 ``APP_DIR_NAME``，与安装态布局分开）；
    安装态：``base/APP_DIR_NAME``，``base`` 缺省取平台数据目录。
    """
    layout = portable_layout()
    if layout is not None:
        return layout.data_dir
    if default_base is None:
        from .config import _default_base

        default_base = _default_base()
    from .config import APP_DIR_NAME

    return Path(default_base) / APP_DIR_NAME
