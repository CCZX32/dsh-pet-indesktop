# -*- coding: utf-8 -*-
"""Setup 首启回执消费（Phase 5B-1）。

安装器在 `{app}\\startup-receipt.json` 写下这次在盘上留下的官方包::

    {"schema":"dsh-pet-startup-receipt/v1","ai_chat":true,"screen":false}

产品侧首次启动读一次：对"回执 true + `features/<pkg>/manifest.json` 存在 +
当前没有 active 版本"的 owner 走一次 ``LocalFeatureRuntime.install_official``，
让 Setup 的勾选真正变成可用入口。规则：

* 每个 owner 独立 try/except；失败只记录，不阻塞启动、不影响下一个；
* 无论成败都删除回执（MOD 中心仍显示「安装」行；回执不是重试队列）；
* 坏回执只记录并删除，不抛异常（启动路径不允许被一个 JSON 文件拖垮）。

便携模式不会安装 Setup，所以通常没有回执；这里不做模式判断——没有文件就是空操作。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .official_features import (
    ACCOUNT_USAGE_FEATURE_ID,
    AI_FEATURE_ID,
    MUSIC_FEATURE_ID,
    SCREEN_FEATURE_ID,
    VOICE_CHIME_FEATURE_ID,
)

RECEIPT_NAME = "startup-receipt.json"
SCHEMA = "dsh-pet-startup-receipt/v1"
#: 延后到事件循环启动后的毫秒数：`install_official` 会拷贝/校验包文件，不能
#: 卡在 AppShell 构造里。1.5 s 足够让主窗与托盘先出现。
STARTUP_DELAY_MS = 1500

_LOG = logging.getLogger(__name__)

#: 回执键 → (official owner, features/ 下的目录名)。顺序即安装顺序。
_PACKAGES = (
    ("ai_chat", AI_FEATURE_ID, "ai-chat"),
    ("screen", SCREEN_FEATURE_ID, "screen-understanding"),
    ("account_usage", ACCOUNT_USAGE_FEATURE_ID, "account-usage"),
    ("music", MUSIC_FEATURE_ID, "music"),
    ("voice_chime", VOICE_CHIME_FEATURE_ID, "voice-chime"),
)


@dataclass(frozen=True)
class ReceiptResult:
    """一次消费的结果；字段都用于日志与测试，不参与 UI。"""

    app_dir: Path
    present: bool = False
    valid: bool = False
    requested: tuple[str, ...] = ()
    installed: tuple[str, ...] = ()
    skipped_active: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    removed: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


def _remove(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        _LOG.warning("启动回执删除失败：%s", path, exc_info=True)
        return False


def _load(path: Path) -> tuple[dict | None, bool]:
    """返回 (payload, valid)。读不到/坏 JSON/schema 不对都是 invalid。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        _LOG.warning("启动回执读取失败：%s", path, exc_info=True)
        return None, False
    try:
        payload = json.loads(text)
    except ValueError:
        _LOG.warning("启动回执不是合法 JSON：%s", path)
        return None, False
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        _LOG.warning("启动回执 schema 不匹配：%s", path)
        return None, False
    for key, _owner, _directory in _PACKAGES:
        if key in payload and not isinstance(payload[key], bool):
            _LOG.warning("启动回执字段 %s 不是布尔值：%s", key, path)
            return None, False
    return payload, True


def _present_packages(features_dir: Path) -> set[str]:
    """盘上真正有清单的包目录名（空目录不算，Setup 会清掉它们）。"""
    present: set[str] = set()
    for _key, _owner, directory in _PACKAGES:
        if (features_dir / directory / "manifest.json").is_file():
            present.add(directory)
    return present


def _observe_result(manager, owner: str) -> None:
    """把回执驱动的安装终态写进日志；不改变事务链的任何行为。"""
    signal = getattr(manager, "result_ready", None)
    if signal is None or not hasattr(signal, "connect"):
        return

    def _log_result(result, *, _owner=owner) -> None:
        _LOG.info(
            "回执安装结果 %s: status=%s reason=%s",
            _owner,
            getattr(result, "status", None),
            getattr(result, "reason", None),
        )

    try:
        signal.connect(_log_result)
    except (RuntimeError, TypeError):
        _LOG.debug("回执安装结果无法接上信号：%s", owner, exc_info=True)


def consume(app_dir: Path | str, runtime, *, features_dir: Path | str | None = None) -> ReceiptResult:
    """读一次回执、按盘上内容安装、删除回执。永不抛异常。"""
    root = Path(app_dir)
    path = root / RECEIPT_NAME
    if not path.is_file():
        return ReceiptResult(app_dir=root)

    payload, valid = _load(path)
    if not valid:
        return ReceiptResult(app_dir=root, present=True, valid=False, removed=_remove(path))

    selected = [
        (key, owner) for key, owner, _directory in _PACKAGES if payload.get(key) is True
    ]
    features_root = Path(features_dir) if features_dir is not None else root / "features"
    present = _present_packages(features_root)

    installed: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    failed: list[tuple[str, str]] = []
    try:
        current = set(runtime.official_packages()) if runtime is not None else set()
    except Exception:
        _LOG.exception("启动回执：读取已安装包状态失败")
        current = set()

    for _key, owner in selected:
        directory = next(d for k, o, d in _PACKAGES if o == owner)
        if directory not in present:
            missing.append(owner)
            continue
        if owner not in current:
            skipped.append(owner)
            continue
        try:
            outcome = runtime.install_official(owner, enabled=True)
            accepted = True
            if isinstance(outcome, tuple) and len(outcome) == 2:
                manager, accepted = outcome
                _observe_result(manager, owner)
            if not accepted:
                failed.append((owner, "submit_rejected"))
                continue
            installed.append(owner)
            current.discard(owner)
        except Exception as exc:  # noqa: BLE001 - 单个包失败不能影响其它包/启动
            _LOG.exception("启动回执：官方包安装失败 %s", owner)
            failed.append((owner, f"{type(exc).__name__}: {exc}"))

    removed = _remove(path)
    result = ReceiptResult(
        app_dir=root,
        present=True,
        valid=True,
        requested=tuple(owner for _key, owner in selected),
        installed=tuple(installed),
        skipped_active=tuple(skipped),
        missing=tuple(missing),
        failed=tuple(failed),
        removed=removed,
    )
    _LOG.info(
        "启动回执处理完成：requested=%s installed=%s skipped=%s missing=%s failed=%s",
        result.requested,
        result.installed,
        result.skipped_active,
        result.missing,
        result.failed,
    )
    return result


def schedule_consume(runtime, app_dir: Path | str | None = None, *, features_dir=None) -> bool:
    """把消费延后到事件循环启动后执行；返回是否排上了。

    不在这里同步安装：AppShell 构造阶段不能为 40 MB 的包拷贝卡住主窗。
    """
    if runtime is None:
        return False
    from PySide6.QtCore import QTimer

    from .runtime_layout import executable_dir

    target = Path(app_dir) if app_dir is not None else executable_dir()

    def _run() -> None:
        try:
            consume(target, runtime, features_dir=features_dir)
        except Exception:  # noqa: BLE001 - 回执消费永远不许拖垮启动
            _LOG.exception("启动回执消费失败")

    QTimer.singleShot(STARTUP_DELAY_MS, _run)
    return True
