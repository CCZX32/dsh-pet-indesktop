# -*- coding: utf-8 -*-
"""`python -m pet --worker <id>` 子进程入口：白名单、退出码与导入边界。

这一片的守卫是**真进程**的：worker 进程存在的唯一理由就是「不背桌面 UI 依赖」，
所以判据必须打在子进程实际加载的模块上，而不是打在源码里 grep 出来的 import 上。
探针用 sitecustomize + atexit 把子进程的已加载模块写盘（形态照 DLC 的
``test_worker_entry_does_not_import_desktop_ui``）。

时序纪律：只用有界轮询 / `subprocess.run(timeout=...)`，不猜时序、不固定 sleep。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 子进程**绝不许**加载的模块前缀（桌面 UI 图 + 聊天域 + 配置域）。
#: 注意 pet.config 也在名单里：它连带 Qt，且 worker 的策略全由宿主喂进来。
_BLOCKED_PREFIXES = (
    "PySide6",
    "pet.app",
    "pet.window",
    "pet.chat",
    "pet.config",
    "pet.proactive",
    "pet.overlay_shell",
)

_IMPORT_PROBE = '''\
import atexit, json, os, sys
from pathlib import Path

@atexit.register
def _write_probe():
    target = os.environ.get("PET_WORKER_IMPORT_PROBE")
    if not target:
        return
    blocked = __BLOCKED__
    loaded = sorted(
        name for name in sys.modules
        if any(name == item or name.startswith(item + ".") for item in blocked)
    )
    Path(target).write_text(json.dumps(loaded), encoding="utf-8")
'''


def _run(args, *, env_extra=None, stdin=None, timeout=90):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pet", *args],
        cwd=ROOT,
        env=env,
        input=stdin,
        capture_output=True,
        timeout=timeout,
    )


def _probe_dir(tmp_path: Path) -> tuple[Path, Path]:
    """建一个自带 sitecustomize 导入探针的目录，返回 (PYTHONPATH 目录, 报告文件)。"""
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir(exist_ok=True)
    (probe_dir / "sitecustomize.py").write_text(
        _IMPORT_PROBE.replace("__BLOCKED__", repr(list(_BLOCKED_PREFIXES))), encoding="utf-8"
    )
    return probe_dir, tmp_path / "worker-imports.json"


def _pythonpath(probe_dir: Path) -> str:
    inherited = os.environ.get("PYTHONPATH", "")
    return str(probe_dir) + (os.pathsep + inherited if inherited else "")


# ------------------------------------------------------------- 白名单与退出码

def test_unknown_worker_id_is_refused_with_exit_code_two():
    result = _run(["--worker", "not-a-worker"], stdin=b"")
    assert result.returncode == 2
    assert b"unknown worker" in result.stderr
    # 拒绝路径不许顺手把 worker 实现拉起来，也不许吐协议帧。
    assert result.stdout == b""


def test_missing_worker_id_is_refused_with_exit_code_two():
    """`--worker` 后面没跟 id：一样拒绝（退出码 2），绝不落到主程序分流。"""
    result = _run(["--worker"], stdin=b"")
    assert result.returncode == 2
    assert b"unknown worker" in result.stderr
    assert result.stdout == b""


def test_worker_entry_main_reports_the_allowlist(monkeypatch):
    from pet.workers import worker_entry

    monkeypatch.setattr(
        "pet.workers.proactive_screen_worker.run_proactive_screen_worker", lambda: 0, raising=False
    )
    assert worker_entry.main("proactive-screen", []) == 0  # 名单内：交给 worker 实现
    assert worker_entry.main("agent-link-events", []) == 2  # DLC 有、本拓扑没有
    assert worker_entry.main("", []) == 2


# ------------------------------------------------------------- 真进程导入边界

def test_worker_route_does_not_import_the_desktop_ui(tmp_path: Path):
    """worker 路由的导入图必须与桌面 UI 无关（真进程 + 已加载模块探针）。"""
    probe_dir, report = _probe_dir(tmp_path)
    result = _run(
        ["--worker", "proactive-screen"],
        env_extra={"PYTHONPATH": _pythonpath(probe_dir), "PET_WORKER_IMPORT_PROBE": str(report)},
        stdin=b"",
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert report.exists(), "探针没写出报告：sitecustomize 未被加载"
    assert json.loads(report.read_text(encoding="utf-8")) == []
    assert result.stderr == b""


def test_worker_route_handshake_frame_is_written_before_stdin_closes(tmp_path: Path):
    """真 CLI 路由发得出 hello：父进程读到的是协议帧而不是半截输出。"""
    result = _run(["--worker", "proactive-screen"], stdin=b"")
    assert result.returncode == 0
    lines = [line for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
    assert lines, "worker 没有输出任何协议帧"
    first = json.loads(lines[0])
    assert first["protocol"] == "pet-worker/v1"
    assert first["worker_id"] == "proactive-screen"
    assert first["type"] == "hello"
    assert first["payload"]["capabilities"] == [
        "foreground.read",
        "screenshot.capture",
        "vision.request",
        "logging.write",
    ]
    assert first["payload"]["lease_claimed"] is False


def test_worker_reports_the_handoff_lease_it_was_launched_with(tmp_path: Path):
    """交接契约：宿主下发 token → 子进程在 hello 里如实认领（S2 §六-5 落地）。"""
    from pet.workers.launch import HANDOFF_TOKEN_ENV

    result = _run(
        ["--worker", "proactive-screen"],
        env_extra={HANDOFF_TOKEN_ENV: "unit-test-token"},
        stdin=b"",
    )
    assert result.returncode == 0
    hello = json.loads(result.stdout.decode("utf-8").splitlines()[0])
    assert hello["payload"]["lease_claimed"] is True


# ------------------------------------------------------------- 独立入口 screen_entry

def _shutdown_frame() -> bytes:
    from pet.workers.protocol import build_message, encode_message

    return encode_message(build_message("proactive-screen", "shutdown", {}))


def test_screen_entry_refuses_an_unknown_argument():
    from pet.workers.screen_entry import run_screen_worker_entry

    assert run_screen_worker_entry(["--something-else"]) == 78


def test_screen_entry_probe_is_fail_closed_without_the_frozen_sandbox():
    """探针模式要求原生沙箱确实生效；本拓扑没有该 bundle（冻结态缺口，S4），
    所以一律 77 退出——**不得**在没有沙箱时跑探针。"""
    import io

    from pet.workers import screen_entry

    assert screen_entry.sandbox_enforced() is False
    assert screen_entry.run_screen_worker_entry(
        ["--feature-package-probe"], source=io.BytesIO(b""), output=io.BytesIO()
    ) == 77


def test_screen_entry_probe_handshakes_inside_an_enforced_sandbox(monkeypatch):
    import io

    from pet.workers import screen_entry

    monkeypatch.setattr(screen_entry, "sandbox_enforced", lambda: True)
    output = io.BytesIO()
    code = screen_entry.run_screen_worker_entry(
        ["--feature-package-probe"], source=io.BytesIO(_shutdown_frame()), output=output
    )
    assert code == 0
    hello = json.loads(output.getvalue().decode("utf-8").splitlines()[0])
    assert hello["payload"] == {"probe": True, "capabilities": []}


def test_screen_entry_probe_rejects_a_foreign_reply(monkeypatch):
    import io

    from pet.workers import screen_entry
    from pet.workers.protocol import build_message, encode_message

    monkeypatch.setattr(screen_entry, "sandbox_enforced", lambda: True)
    foreign = encode_message(build_message("other-worker", "shutdown", {}))
    assert screen_entry.run_screen_worker_entry(
        ["--feature-package-probe"], source=io.BytesIO(foreign), output=io.BytesIO()
    ) == 78


def test_screen_entry_is_fail_closed_without_a_handoff(monkeypatch):
    from pet.workers import screen_entry
    from pet.workers.launch import HANDOFF_TOKEN_ENV

    monkeypatch.delenv(HANDOFF_TOKEN_ENV, raising=False)
    assert screen_entry.run_screen_worker_entry([]) == 77


def test_screen_entry_runs_the_worker_once_the_handoff_is_claimed(monkeypatch):
    from pet.workers import screen_entry
    from pet.workers.launch import HANDOFF_TOKEN_ENV

    monkeypatch.setenv(HANDOFF_TOKEN_ENV, "unit-test-token")
    assert screen_entry.run_screen_worker_entry([], run_runtime=lambda: 0) == 0


@pytest.mark.parametrize("module", ["pet.workers.worker_entry", "pet.workers.proactive_screen_worker", "pet.workers.screen_entry"])
def test_worker_modules_import_without_qt(module: str):
    """模块级导入不碰 Qt：子进程只导协议层与 worker 实现，绝不背 GUI 依赖。"""
    script = (
        "import sys, json\n"
        f"import {module}\n"
        "loaded = sorted(n for n in sys.modules if n.startswith('PySide6'))\n"
        "print(json.dumps(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert json.loads(result.stdout.decode("utf-8").strip()) == []
