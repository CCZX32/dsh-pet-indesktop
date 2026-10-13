# -*- coding: utf-8 -*-
"""主动识屏 worker 的**跨进程可见**状态快照。

设置页「主动识屏」要让「走 worker 还是在进程内」这件事如实可见（S3 的硬要求），
但设置页可能是**独立进程**（``python -m pet --settings``）、也可能与主进程同进程，
而 worker 只活在主进程里。所以状态落在配置目录下的一个小 JSON 里：主进程在
worker 状态**发生变化**时写一次（不是轮询、不是每次识屏都写），任何一侧读它即可。

设计约束（与 `pet/proactive_limiter.py` 的状态文件同口径）：

* 原子替换（临时文件 + ``os.replace`` 重试），读者永远看不到半截文件；
* 有界：写入前整段序列化并卡上限，超限直接放弃写入（状态是诊断信息，不值得为它
  破坏配置目录）；
* 只读侧永不抛异常：文件缺失/损坏/权限不足一律当作"未知"，由调用方如实展示；
* 快照里的诊断字段已经过 `pet/workers/worker_diagnostics.safe_diagnostic` 白名单
  过滤，不含路径、token 或子进程 stderr 原文。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger(__name__)

#: 文件名（落在配置目录，与 proactive_screen_state.json 同级）。
STATUS_FILE_NAME = "proactive_worker_status.json"

#: 上限 4 KiB：状态快照是诊断信息，写不下就该裁剪而不是撑爆配置目录。
STATUS_MAX_BYTES = 4096

#: worker 模式（``proactive_screen.execution``）的两个合法取值。
EXECUTION_WORKER = "worker"
EXECUTION_IN_PROCESS = "in_process"


def status_path(config_dir: os.PathLike[str] | str) -> Path:
    return Path(config_dir) / STATUS_FILE_NAME


def write_status(config_dir: os.PathLike[str] | str, snapshot: Mapping[str, Any]) -> bool:
    """原子写入状态快照；失败只记日志并返回 False（诊断信息不值得打断产品路径）。"""
    payload = dict(snapshot)
    payload["updated_at"] = time.time()
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        log.warning("主动识屏 worker 状态无法序列化，跳过写入")
        return False
    if len(raw.encode("utf-8")) > STATUS_MAX_BYTES:
        log.warning("主动识屏 worker 状态超出 %d 字节上限，跳过写入", STATUS_MAX_BYTES)
        return False
    directory = Path(config_dir)
    temp = directory / f".{STATUS_FILE_NAME}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temp.write_text(raw, encoding="utf-8")
        from .config import atomic_replace_with_retry

        atomic_replace_with_retry(temp, status_path(directory))
        return True
    except OSError:
        log.warning("主动识屏 worker 状态写入失败", exc_info=True)
        try:
            temp.unlink()
        except OSError:
            pass
        return False


def read_status(config_dir: os.PathLike[str] | str) -> dict[str, Any]:
    """读取状态快照；任何失败都返回空 dict（调用方按「未知」展示）。"""
    try:
        raw = status_path(config_dir).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def worker_mode(raw_config: Any) -> str:
    """从配置里取执行位置（非法值回退 worker：默认就是子进程执行）。"""
    if isinstance(raw_config, Mapping):
        value = str(raw_config.get("execution", EXECUTION_WORKER)).strip().lower()
        if value in {EXECUTION_WORKER, EXECUTION_IN_PROCESS}:
            return value
    return EXECUTION_WORKER


def describe(snapshot: Mapping[str, Any] | None) -> tuple[str, str]:
    """把快照翻成设置页那一行要显示的（值, 说明）。

    「未知」是一个如实结论，不是兜底话术：主进程没跑过识屏时这里本来就没有事实
    可说，编一句"正常"才是谎报。
    """
    data = snapshot if isinstance(snapshot, Mapping) else {}
    if not data:
        return "未知（本机尚未运行过识屏）", "主进程还没启动过识屏 worker，所以这里没有可报的状态。"
    mode = str(data.get("mode", ""))
    state = str(data.get("state", ""))
    if mode == "in_process":
        return ("进程内执行", "当前设置为进程内执行：识屏在桌宠自己这个进程里跑，不启子进程。")
    if mode == "disabled":
        return ("已关闭", "识屏执行位置设为关闭：识屏不会运行。")
    if state == "ready":
        return ("worker 子进程（就绪）", "识屏在独立子进程里执行：截图与视觉请求都不占用桌宠主进程。")
    if state in {"starting", "handshaking"}:
        return ("worker 子进程（启动中）", "worker 正在启动并完成握手；这段时间内的识屏请求会被跳过。")
    if state == "crashed":
        return ("worker 崩溃，等待重启", "worker 进程异常退出，正在按重启阶梯拉起；未改用进程内执行。")
    if state == "fault":
        hint = str(data.get("hint") or "").strip()
        reason = str(data.get("last_reason") or data.get("last_stage") or "").strip()
        detail = hint or ("原因：" + reason if reason else "原因未知")
        return ("worker 故障，识屏已停止", detail + "（本版本不会静默改用进程内执行）")
    if state in {"stopping", "stopped", "disabled"}:
        return ("worker 未运行", "worker 当前没有在跑；开启主动识屏后会自动拉起。")
    return (f"worker 子进程（{state or '状态未知'}）", "worker 状态无法归类，详见 pet.log 中的 worker 诊断。")


__all__ = [
    "EXECUTION_IN_PROCESS",
    "EXECUTION_WORKER",
    "STATUS_FILE_NAME",
    "describe",
    "read_status",
    "status_path",
    "worker_mode",
    "write_status",
]
