# -*- coding: utf-8 -*-
"""把一份用户自选的本地功能包绑到**只属于它自己**的端口。

Ported from the DLC branch ``pet/feature_host_bindings.py``；只保留 ``bind_local_context``
那一半，其余（``bind_screen_context`` / ``bind_ai_context`` / ``runtime_for`` /
``manual_for``）绑的是本仓库没有的官方内置域（识屏 / AI）与凭据库，随那条线一起做。

与 DLC 的两处差异，都是本仓库的既定口径：

* **端口根是 ``feature-data/<owner>/``**（不是 app 配置树的 ``plugins.<owner>`` 节点）：
  MOD 自有配置/数据不进 :class:`pet.config.Config`，也就不进 ``settings_default_marks`` /
  出厂默认表 / 搜索别名（见 ``docs/SETTINGS-CHANGE-GATES.md``）；
* 落盘走 :mod:`pet.feature_state_io`（``safe_path`` / ``atomic_write`` / ``read_bytes`` /
  ``open_kernel_lock``）——字节级 I/O、原子写与内核锁都只有这一套实现。
* ``api`` 端口固定为"调用即抛 ``unsupported_capability``"（D2-d 未落地），不返回半成品
  对象、不静默 ``None``。

信任口径：本地 MOD 是用户自己选择信任的 Python 代码，与桌宠同权限运行；这里的端口是
**能力面**的表达，不是沙箱。
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from .api_ports import unsupported_api_port
from .feature_ports import FeatureConfigurationPort, FeatureDocumentPort, FeatureHostContext, FeatureStateDocumentPort
from .feature_state_io import StateError, atomic_write, open_kernel_lock, read_bytes, safe_path
from .official_features import is_valid_feature_id

#: 一份作者文档 / 配置的有界读取上限（与验签清单同一量级的保守值）。
_DOCUMENT_LIMIT = 1 << 20
_DATA_DIRECTORY = "feature-data"


def namespace_revision(value: dict) -> str:
    """命名空间内容摘要；CAS 的 ``expected_revision`` 就是它（与 DLC 同口径）。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read_document(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = read_bytes(path, _DOCUMENT_LIMIT)
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateError("feature_document_invalid") from exc
    if not isinstance(value, dict):
        raise StateError("feature_document_invalid")
    return value


def _write_document(path: Path, value: dict) -> None:
    if not isinstance(value, dict):
        raise StateError("feature_document_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class _BoundConfiguration:
    """Bound callables: no Config object, no caller-selected path or namespace."""

    read_namespace: Callable[[], dict]
    revision: Callable[[], str]
    commit_namespace: Callable[..., None]
    operation: Callable[[], AbstractContextManager[None]]


def _bind_configuration(path: Path) -> FeatureConfigurationPort:
    def commit(value: dict, *, expected_revision: str, source_guard: Callable[[dict], None] | None = None) -> None:
        with open_kernel_lock(path.with_suffix(path.suffix + ".lock")):
            latest = _read_document(path)
            if namespace_revision(latest) != expected_revision:
                raise StateError("configuration_changed")
            if source_guard is not None:
                # 本拓扑没有独立的"迁移来源"（配置根就在 feature-data/<owner>/ 下）：
                # 守卫看到的是提交前的命名空间本身，并发改动先由上面的 CAS 拦下。
                source_guard(dict(latest))
            if not isinstance(value, dict):
                raise StateError("configuration_invalid")
            _write_document(path, dict(value))

    return _BoundConfiguration(
        lambda: _read_document(path),
        lambda: namespace_revision(_read_document(path)),
        commit,
        lambda: open_kernel_lock(path.with_suffix(path.suffix + ".lock")),
    )


@dataclass(frozen=True, slots=True)
class _BoundDocument:
    read: Callable[[], dict]
    write: Callable[[dict], None]
    clear: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _BoundStateDocument:
    read: Callable[[], dict]
    write: Callable[[dict], None]
    clear: Callable[[], None]
    locked: Callable[[], AbstractContextManager[None]]


def _bind_document(path: Path) -> FeatureDocumentPort:
    def clear() -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return

    return _BoundDocument(lambda: _read_document(path), lambda value: _write_document(path, value), clear)


def _bind_state_document(path: Path) -> FeatureStateDocumentPort:
    document = _bind_document(path)
    return _BoundStateDocument(
        document.read,
        document.write,
        document.clear,
        lambda: open_kernel_lock(path.with_suffix(path.suffix + ".lock")),
    )


def bind_local_context(cfg, owner: str) -> FeatureHostContext:
    """Bind a user-selected local package to only generic, owner-scoped ports.

    Local packages are trusted executable Python, not sandboxed code.  This
    binding deliberately exposes no desktop/window ports, no credentials and no
    preference field set: 作者拿到的是自己那份目录上的配置/文档/状态，
    包声明的 capabilities 只是兼容上限声明，不是运行期权限。
    """
    if not is_valid_feature_id(owner):
        raise ValueError("invalid_feature_owner")
    root = Path(cfg.dir) / _DATA_DIRECTORY / owner

    safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    safe_path(root)

    return FeatureHostContext(
        owner=owner,
        configuration=_bind_configuration(root / "configuration.json"),
        documents=MappingProxyType({"memory": _bind_document(root / "memory.json")}),
        state_documents=MappingProxyType({"state": _bind_state_document(root / "state.json")}),
        desktop=None,
        worker_launch_factory=None,
        allow_in_process=True,
        api=unsupported_api_port(),
    )
