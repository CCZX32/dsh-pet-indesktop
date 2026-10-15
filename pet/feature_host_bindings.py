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

识屏包线（DLC 第三片）新增 :func:`bind_screen_context`：官方识屏包（owner 闭集里的
``official.screen-understanding``）的绑定。与本地 MOD 的差异就是它的授权面——
凭据库 / 偏好 / 窗口 / 桌面查询四个端口按 4A 同风格注入；配置命名空间带 journal
侧车（视觉凭据事务的写前日志）；窗口端口不绑单窗——overlay 单窗拓扑下由
:func:`register_screen_presentation` 注册的**进程级呈现提供方**（生产是
``MultiWindowProxy`` 语义面）在每次调用时惰性解析，没注册就全部安全降级
（snapshot 不可见、enabled False、气泡不投递）。

信任口径：本地 MOD 是用户自己选择信任的 Python 代码，与桌宠同权限运行；这里的端口是
**能力面**的表达，不是沙箱。
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from .api_ports import unsupported_api_port
from .feature_ports import (
    FeatureConfigurationPort,
    FeatureDocumentPort,
    FeatureHostContext,
    FeatureStateDocumentPort,
    FeatureUserDataPort,
    FeatureWindowPorts,
    FeatureWindowState,
)
from .feature_state_io import StateError, atomic_write, open_kernel_lock, read_bytes, safe_path
from .official_features import AI_FEATURE_ID, SCREEN_FEATURE_ID, is_valid_feature_id

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
    read_journal: Callable[[], dict | None]
    write_journal: Callable[[dict], None]


def _bind_configuration(path: Path) -> FeatureConfigurationPort:
    # 视觉凭据事务的写前日志侧车（上游 journal_path 的等价物）：识屏包的
    # VisionConfigService.apply/recover 靠它做"已落 keyring 但未提交"的回收。
    # 两把锁与上游同口径：commit 用 ``.write.lock``，operation()（recover/apply
    # 外层事务）用 journal 的锁——同一把会非重入自锁（apply 里先 operation 再 commit）。
    journal_path = path.with_suffix(".journal.json")

    def commit(value: dict, *, expected_revision: str, source_guard: Callable[[dict], None] | None = None) -> None:
        with open_kernel_lock(path.with_suffix(path.suffix + ".write.lock")):
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

    def read_journal() -> dict | None:
        if not journal_path.is_file():
            return None
        return _read_document(journal_path)

    def write_journal(value: dict) -> None:
        _write_document(journal_path, dict(value))

    return _BoundConfiguration(
        lambda: _read_document(path),
        lambda: namespace_revision(_read_document(path)),
        commit,
        lambda: open_kernel_lock(journal_path.with_suffix(journal_path.suffix + ".lock")),
        read_journal,
        write_journal,
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


# ---------------------------------------------------------------- 官方识屏包

#: 识屏策略偏好的授权字段集（上游 ``_SCREEN_FIELDS`` 逐字）：包只能 stage 这些键。
_SCREEN_PREFERENCE_FIELDS = frozenset(
    {
        "enabled",
        "dry_run",
        "preset",
        "allow_when_mouse_through",
        "whitelist",
        "dwell_seconds",
        "require_idle",
        "min_idle_seconds",
        "cooldown_minutes",
        "daily_cap",
        "min_request_interval_seconds",
        "change_threshold",
        "prefer_free_provider",
        "pre_cue",
    }
)

#: 进程级呈现提供方工厂（AppShell 注册；``None`` = 无呈现面，全部安全降级）。
_SCREEN_PRESENTATION: Callable[[], object] | None = None


def register_screen_presentation(factory: Callable[[], object] | None) -> None:
    """注册/清除官方识屏包的呈现提供方工厂（``None`` 清除；测试收口用）。"""
    global _SCREEN_PRESENTATION
    if factory is not None and not callable(factory):
        raise TypeError("screen presentation factory must be callable")
    _SCREEN_PRESENTATION = factory


class _BoundPreferences:
    """字段白名单 + 草稿两段写：``stage`` 只进草稿，``flush`` 才原子落盘。"""

    def __init__(self, path: Path, fields: frozenset[str]) -> None:
        self._path = path
        self._fields = frozenset(fields)
        self._staged: dict | None = None

    def read(self) -> dict:
        if self._staged is not None:
            return copy.deepcopy(self._staged)
        try:
            return _read_document(self._path)
        except StateError:
            return {}

    def stage(self, values: dict) -> None:
        if not isinstance(values, dict) or set(values) - self._fields:
            raise PermissionError("preference_not_granted")
        merged = self.read()
        merged.update(copy.deepcopy(values))
        self._staged = merged

    def flush(self) -> bool:
        if self._staged is None:
            return True
        try:
            _write_document(self._path, self._staged)
        except (OSError, StateError):
            return False
        return True


def _screen_presentation():
    factory = _SCREEN_PRESENTATION
    if factory is None:
        return None
    try:
        return factory()
    except Exception:
        return None


def _bind_screen_window(cfg, owner: str, *, authorized: Callable[[], bool] | None, host=None) -> FeatureWindowPorts:
    """overlay 单窗拓扑的窗口端口：不持窗对象，每次调用经呈现提供方惰性解析。

    提供方的语义面与 ``MultiWindowProxy`` 对齐（``isVisible`` / ``_dragging`` /
    ``_physics_mode`` / ``_click_effect_phase`` / ``mouse_through`` /
    ``agent_link_manager`` / ``show_bubble`` / ``hold_bubble`` / ``on_look_synced``）。
    """

    def alive_provider():
        provider = _screen_presentation()
        if provider is None:
            return None
        try:
            import shiboken6
            from PySide6.QtCore import QObject

            if isinstance(provider, QObject) and not shiboken6.isValid(provider):
                return None
        except Exception:
            pass
        return provider

    def enabled() -> bool:
        return bool(authorized is not None and authorized())

    def snapshot() -> FeatureWindowState:
        provider = alive_provider()
        from . import catalog

        character = str(cfg.get("character", catalog.DEFAULT_CHARACTER))
        namer = getattr(cfg, "character_display_name", None)
        display = str(namer(character)) if callable(namer) else character
        interacting = False
        mouse_through = False
        visible = False
        if provider is not None:
            visible = bool(getattr(provider, "isVisible", lambda: False)())
            interacting = bool(
                getattr(provider, "_dragging", False)
                or getattr(provider, "_physics_mode", None) is not None
                or (getattr(provider, "_click_effect_phase", 0) or 0) > 0
            )
            mouse_through = bool(getattr(provider, "mouse_through", False))
        return FeatureWindowState(
            "screen-package",
            str(getattr(cfg, "instance_id", "") or "primary"),
            character,
            display,
            visible,
            interacting,
            mouse_through,
        )

    def agent_busy(process: str, title: str) -> bool:
        provider = alive_provider()
        manager = getattr(provider, "agent_link_manager", None) if provider is not None else None
        checker = getattr(manager, "busy_agent_owns_process", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(process, title))
        except Exception:
            return False

    def show_bubble(text: str, duration_ms: int) -> None:
        provider = alive_provider()
        callback = getattr(provider, "show_bubble", None) if provider is not None else None
        if enabled() and callable(callback):
            callback(str(text), duration_ms=int(duration_ms))

    def hold_bubble(seconds: float) -> None:
        provider = alive_provider()
        callback = getattr(provider, "hold_bubble", None) if provider is not None else None
        if enabled() and callable(callback):
            callback(float(seconds))

    def sync_text(user_text: str, reply: str) -> None:
        provider = alive_provider()
        callback = getattr(provider, "on_look_synced", None) if provider is not None else None
        if enabled() and callable(callback):
            callback(str(user_text), str(reply))

    def external_text(result_id: str, kind: str, user_text: str, reply: str) -> None:
        provider = alive_provider()
        callback = getattr(provider, "on_external_text", None) if provider is not None else None
        if not enabled():
            return
        if callable(callback):
            callback(str(result_id), str(kind), str(user_text), str(reply))
        else:
            sync_text(user_text, reply)  # 无对接面的宿主回退纯文本同步（上游同口径）

    def bind_lifecycle(stop, resume, dispose) -> Callable[[], None]:
        # 无单窗销毁语义：dispose 由 Runtime 包装器的 close() 显式调；
        # stop/resume 钉在宿主的 owner 级执行转换上（未给 host 时惰性空转）。
        del dispose
        if host is None:
            return lambda: None
        return host.bind_execution(owner, stop, resume)

    return FeatureWindowPorts(snapshot, agent_busy, show_bubble, hold_bubble, sync_text, external_text, enabled, bind_lifecycle)


def bind_screen_context(
    cfg,
    *,
    owner: str = SCREEN_FEATURE_ID,
    vault=None,
    authorized: Callable[[], bool] | None = None,
    host=None,
) -> FeatureHostContext:
    """官方识屏包的宿主绑定：凭据/偏好/窗口/桌面四端口 + 带 journal 的配置。

    ``vault`` 与 ``authorized``/``host`` 都是宿主侧注入口：测试给假后端与固定判据，
    生产由管理器给 ``host.enabled(owner)`` 与宿主本体。``legacy_secret_reader``
    恒为 ``None``——本仓库不移植 legacy 迁移（内置识屏并存，包装的是独立新配置）。
    """
    if owner != SCREEN_FEATURE_ID or not is_valid_feature_id(owner):
        raise ValueError("invalid_feature_owner")
    from .credentials import CredentialVaultPort
    from .desktop_query import get_desktop_query

    root = Path(cfg.dir) / _DATA_DIRECTORY / owner
    safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    safe_path(root)

    if vault is None:
        scope = str(Path(cfg.path).resolve()) if hasattr(cfg, "path") else str(root.resolve())
        vault = CredentialVaultPort(owner, scope)

    return FeatureHostContext(
        owner=owner,
        configuration=_bind_configuration(root / "configuration.json"),
        credentials=vault,
        legacy_secret_reader=None,
        preferences=_BoundPreferences(root / "preferences.json", _SCREEN_PREFERENCE_FIELDS),
        documents=MappingProxyType({"memory": _bind_document(root / "memory.json")}),
        state_documents=MappingProxyType(
            {
                "state": _bind_state_document(root / "state.json"),
                "dry_state": _bind_state_document(root / "dry_state.json"),
            }
        ),
        desktop=get_desktop_query(),
        window=_bind_screen_window(cfg, owner, authorized=authorized, host=host),
        api=None,
    )


# ---------------------------------------------------------------- 官方聊天包

#: 聊天包偏好的授权字段集（上游 ``bind_ai_context`` 逐字）：包只能 stage 这些键。
#:
#: 与上游的一处**有意分歧**：上游把这份字段集绑在 app 配置树的 ``chat`` 节点上
#: （包与内置聊天共用一份 provider 配置）。本仓库不让包进配置树——包的那份
#: preferences 落在 ``feature-data/<owner>/preferences.json``（见下文），于是
#: 内置聊天与包各持一本自己的账，谁都不动谁（本片的口径：两套聊天实现并存，
#: 不合并）。
_AI_PREFERENCE_FIELDS = frozenset(
    {
        "enabled",
        "active_provider",
        "default_system_prompt",
        "history_message_limit",
        "history_char_limit",
        "providers",
    }
)


def bind_ai_context(
    cfg,
    *,
    owner: str = AI_FEATURE_ID,
    vault=None,
    authorized: Callable[[], bool] | None = None,
    host=None,
) -> FeatureHostContext:
    """官方聊天包的宿主绑定：自己的数据根 + 自己那本配置 + 凭据库。

    与识屏绑定（:func:`bind_screen_context`）的差异就是"不给什么"：**不给**桌面
    查询端口、**不给**窗口操作面、**不给** Core 的 API 端口（``api=None``）——
    换句话说，包要联网只能走它自己命名空间里的 provider 配置 + 凭据库里的 key，
    读不到 Core 内置聊天的那一份。``legacy_secret_reader`` 是"调用即拒绝"的显式
    口子（包会主动调它，见 ``host/config.py``），而不是识屏那边的 ``None``。
    """
    if owner != AI_FEATURE_ID or not is_valid_feature_id(owner):
        raise ValueError("invalid_feature_owner")
    from .credentials import CredentialError, CredentialVaultPort

    root = Path(cfg.dir) / _DATA_DIRECTORY / owner
    safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    safe_path(root)

    if vault is None:
        scope = str(Path(cfg.path).resolve()) if hasattr(cfg, "path") else str(root.resolve())
        vault = CredentialVaultPort(owner, scope)

    def deny_legacy(ref: str) -> str:
        raise CredentialError("legacy_import_authorization_required")

    def read_display() -> Mapping:
        return MappingProxyType(
            {
                "character": cfg.get("character"),
                "self_talk_bubble_style": cfg.get("self_talk_bubble_style", "classic_top"),
            }
        )

    return FeatureHostContext(
        owner=owner,
        configuration=_bind_configuration(root / "configuration.json"),
        credentials=vault,
        legacy_secret_reader=deny_legacy,
        preferences=_BoundPreferences(root / "preferences.json", _AI_PREFERENCE_FIELDS),
        documents=MappingProxyType({}),
        state_documents=MappingProxyType({}),
        desktop=None,
        window=None,
        api=None,
        user_data=FeatureUserDataPort(
            root,
            str(getattr(cfg, "instance_id", "") or ""),
            read_display,
            lambda character: str(cfg.character_alias(character) or ""),
        ),
    )
