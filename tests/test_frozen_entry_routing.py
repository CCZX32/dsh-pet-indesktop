# -*- coding: utf-8 -*-
"""冻结入口（``packaging/pet_entry*.py``）的参数分流：两种子进程都不许落到 ``pet.app``。

冻结包里 ``python -m pet`` 那条路由（``pet/__main__.py``）**不存在**——PyInstaller 执行
的是入口脚本本身，所以 ``--worker``（``pet/workers/supervisor.py::_resolve_command`` 冻结
态用 ``sys.executable --worker <id>``）与 ``--feature-package-probe``
（``pet/feature_package_preflight.py::probe_command`` 冻结态同形）这两条分流必须在入口里
各写一份。写漏了的后果不是"少一个功能"：子进程会去 import ``pet.app``，把整只桌宠
（窗口/托盘/素材库/ffmpeg）拉起来，并撞上主进程的单实例门——而那些子进程存在的唯一
理由就是**不背桌面 UI 依赖**。

判据打在真进程上（同 ``tests/test_workers_entry.py`` 与 ``tests/test_proactive_worker.py``
的边界探针范式）：``sitecustomize`` 装一个元路径拦截器，冻结入口一旦走进桌面 UI 图就抛
``AssertionError``；再配一次真握手 / 真探针回执，证明"没走桌面图"是**因为走了正确那条
路**，而不是因为入口提前死了。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = {
    "chat": ROOT / "packaging" / "pet_entry.py",
    "no_chat": ROOT / "packaging" / "pet_entry_no_chat.py",
}

#: worker 路由**绝不许**加载的模块（与 ``tests/test_workers_entry.py`` 同一份名单：
#: 桌面 UI 图 + 聊天域 + 配置域）。冻结入口比源码入口多背 ``pet.runtime_cleanup``
#: 那一步（onefile 运行目录归属标记），它只有标准库依赖。
_WORKER_BLOCKED = (
    "PySide6",
    "pet.app",
    "pet.window",
    "pet.chat",
    "pet.config",
    "pet.proactive",
    "pet.overlay_shell",
)

#: 探针路由的名单窄一档：探针子进程确实会用到配置无关的验证链，但**结构上**不该碰
#: 桌面 UI 那几块（``pet.app`` 是那条链的总闸）。
_PROBE_BLOCKED = ("pet.app", "pet.window", "pet.overlay_shell")

_BOUNDARY = '''\
import sys
from importlib.abc import MetaPathFinder

BLOCKED = __BLOCKED__


class NoDesktop(MetaPathFinder):
    def find_spec(self, fullname, *args):
        if any(fullname == item or fullname.startswith(item + ".") for item in BLOCKED):
            raise AssertionError("frozen entry crossed into the desktop app: " + fullname)
        return None


sys.meta_path.insert(0, NoDesktop())
'''


def _run_entry(
    entry: Path,
    args: list[str],
    tmp_path: Path,
    *,
    blocked: tuple[str, ...],
    timeout: float = 90.0,
) -> subprocess.CompletedProcess:
    """跑一次冻结入口（源码形态：入口脚本 + PYTHONPATH 指到仓库根）。"""
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "sitecustomize.py").write_text(
        _BOUNDARY.replace("__BLOCKED__", repr(list(blocked))), encoding="utf-8"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(probe_dir) + os.pathsep + str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, str(entry), *args],
        cwd=ROOT,
        env=env,
        input=b"",
        capture_output=True,
        timeout=timeout,
    )


def _assert_no_desktop_import(result: subprocess.CompletedProcess) -> None:
    text = result.stderr.decode("utf-8", "replace")
    assert "crossed into the desktop app" not in text, text
    assert "Traceback" not in text, text


# --------------------------------------------------------------------- 源码级守卫


class TestTheEntriesSplitBeforeImportingTheApp:
    """分流必须在 ``from pet.app import main`` **之前**（源码断言：行为测试看不到顺序）。"""

    @pytest.mark.parametrize("name", sorted(ENTRIES))
    def test_worker_and_probe_are_split_before_the_app_import(self, name):
        text = ENTRIES[name].read_text(encoding="utf-8")
        app_import = text.index("from pet.app import main")
        for flag in ("--worker", "--feature-package-probe"):
            assert flag in text, f"{name} 没有分流 {flag}"
            assert text.index(flag) < app_import, f"{name} 的 {flag} 分流排在 import pet.app 之后"
        # --settings 的既有纪律照旧：三条分流都在 app 之前。
        assert text.index("--settings") < app_import

    @pytest.mark.parametrize("name", sorted(ENTRIES))
    def test_the_split_reuses_the_single_implementation(self, name):
        """分流只许转发给 ``pet/__main__.py`` 里那一份实现（不许抄第二份路由）。"""
        text = ENTRIES[name].read_text(encoding="utf-8")
        assert "from pet.__main__ import _run_worker, _worker_id" in text
        assert "from pet.__main__ import _run_feature_probe" in text


# --------------------------------------------------------------------- 真进程守卫


class TestTheWorkerRouteStaysOutOfTheDesktopApp:
    @pytest.mark.parametrize("name", sorted(ENTRIES))
    def test_the_worker_handshake_comes_back_without_loading_the_app(self, name, tmp_path):
        result = _run_entry(ENTRIES[name], ["--worker", "proactive-screen"], tmp_path, blocked=_WORKER_BLOCKED)
        _assert_no_desktop_import(result)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        frames = [line for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
        assert frames, "worker 没有输出任何协议帧（入口没走到 worker 路由）"
        hello = json.loads(frames[0])
        assert hello["protocol"] == "pet-worker/v1"
        assert hello["worker_id"] == "proactive-screen"
        assert hello["type"] == "hello"


class TestTheProbeRouteStaysOutOfTheDesktopApp:
    @pytest.mark.parametrize("name", sorted(ENTRIES))
    def test_the_probe_writes_its_verdict_without_loading_the_app(self, name, tmp_path):
        from pet.feature_package_preflight import PROBE_SCHEMA, probe_policy
        from pet.feature_policy import local_package_verifier
        from tests._feature_import_package import DEFAULT_OWNER, build

        built, _zip = build(tmp_path / "pkg")
        verdict_path = tmp_path / "verdict.json"
        job_path = tmp_path / "job.json"
        job_path.write_text(
            json.dumps(
                {
                    "schema": PROBE_SCHEMA,
                    "package_root": str(built),
                    "verdict_path": str(verdict_path),
                    "policy": probe_policy(local_package_verifier(DEFAULT_OWNER, platform=sys.platform)),
                }
            ),
            encoding="utf-8",
        )
        result = _run_entry(ENTRIES[name], ["--feature-package-probe", str(job_path)], tmp_path, blocked=_PROBE_BLOCKED)
        _assert_no_desktop_import(result)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        assert verdict["ok"] is True, verdict
        assert verdict["metadata"]["owner"] == DEFAULT_OWNER

    @pytest.mark.parametrize("name", sorted(ENTRIES))
    def test_a_refused_probe_reports_its_own_exit_code(self, name, tmp_path):
        """拒绝路径也要走对分流：退出码 78 是子进程契约，不是桌面应用的退出码。"""
        result = _run_entry(
            ENTRIES[name], ["--feature-package-probe", str(tmp_path / "missing.json")], tmp_path, blocked=_PROBE_BLOCKED
        )
        _assert_no_desktop_import(result)
        assert result.returncode == 78
        assert b"feature package probe" in result.stderr
