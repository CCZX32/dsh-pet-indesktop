# -*- coding: utf-8 -*-
"""D3：本地功能包的**装前子进程预检**（元信息提取 + 装前失败检查）。

这一片要钉住的是「探针到底在做什么、又不做什么」：

1. 它真的在**另一个进程**里把包装一次（回执带子进程 pid），本进程不留痕迹
   （包的命名空间不进宿主 ``sys.modules``）；
2. 它读得回包的公开元信息（owner / 契约 / 贡献 / 有没有 Runtime 与设置）；
3. 它只在**拒绝**方向有权威：包装不起来、``create_host()`` 说的 owner 与清单不符、
   host-only 却要 Worker、策略不是"本地用户信任"，各自给一个固定原因码；
4. 它**不声称隔离**：没有 OS 沙箱，环境清理与超时都不是安全边界，超时只表示
   "这个包卡住了，装之前就拒掉"，不是什么"沙箱挡住了它"。

材料是仓库里真的示例包（``examples/mods/hello-local``）经 ``scripts.build_mod_example``
打的成品包——不是替身。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pet import __version__
from pet.feature_package_preflight import (
    CHILD_REASONS,
    PROBE_FLAG,
    LocalPackageProbe,
    parse_verdict,
    probe_command,
)
from pet.plugins.package_trust import FeaturePackageVerifier
from tests._feature_import_package import DEFAULT_OWNER as OWNER
from tests._feature_import_package import ROOT, build, build_tree, source_tree

CAPABILITIES = frozenset({"menu.contribute", "settings.contribute"})


def _verifier(*, owner=OWNER, allow_local=True, anchors=None) -> FeaturePackageVerifier:
    return FeaturePackageVerifier(
        core_version=__version__,
        api_version="1",
        feature_id=owner,
        allowed_capabilities=CAPABILITIES,
        allow_local_packages=allow_local,
        platform=sys.platform,
        trust_anchors=anchors or {},
    )


def _run_probe(package: Path, *, timeout: float | None = None, verifier=None):
    verifier = verifier or _verifier()
    descriptor = verifier.verify(package)
    probe = LocalPackageProbe() if timeout is None else LocalPackageProbe(timeout=timeout)
    return probe.run(descriptor, verifier)


# ------------------------------------------------------------- 正路径与元信息

def test_the_probe_loads_the_package_in_another_process(tmp_path):
    """回执里的 pid 必须不是本进程——这是"真起了子进程"的机器证据。

    这个 pid 由**父侧**的 ``Popen`` 给出（见 ``parse_verdict``），不是子进程的自述。
    """
    package, _archive = build(tmp_path / "pkg")
    before = set(sys.modules)
    verdict = _run_probe(package)
    assert verdict.ok is True and verdict.reason is None
    assert verdict.child_pid is not None and verdict.child_pid != os.getpid()
    # 本进程不留痕迹：包代码的命名空间一个都没进宿主的 sys.modules
    # （装载 + pin 全发生在子进程里，宿主的 host 租约没有被这次预检占住）。
    assert {name for name in set(sys.modules) - before if name.startswith("_pet_official_screen")} == set()


def test_the_child_pid_comes_from_the_parent_not_from_the_receipt(tmp_path):
    """回执里自报的 pid 不算数：真 pid 只有父侧的 ``Popen`` 知道。

    包代码就在子进程里跑，它能改写自己的回执（甚至 ``os.getpid``）。父侧从进程对象
    拿到的那个 pid 才是"这次预检起了哪个进程"的证据，所以回执里那一栏一律不看——
    既不采信，也不拿它跟真值对质（自述与真值不一致时没有更好的结论可言）。
    """
    path = tmp_path / "verdict.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "ok": True,
                "child_pid": 4242,
                "metadata": {
                    "owner": OWNER,
                    "mount_contract": "mod/v1",
                    "contributions": [],
                    "has_runtime": True,
                    "has_settings": True,
                },
            }
        ),
        encoding="utf-8",
    )
    verdict = parse_verdict(path, returncode=0, child_pid=os.getpid())
    assert verdict.ok is True
    assert verdict.child_pid == os.getpid(), "回执自报的 pid 被当成真值了"


def test_the_probe_reads_back_the_public_metadata(tmp_path):
    package, _archive = build(tmp_path / "pkg")
    metadata = _run_probe(package).metadata
    assert metadata is not None
    assert metadata.owner == OWNER
    assert metadata.mount_contract == "mod/v1"
    assert metadata.contributions == (("hello", "menu", "hello"),)
    assert metadata.has_runtime is True and metadata.has_settings is True
    assert metadata.document()["contributions"] == [["hello", "menu", "hello"]]


def test_the_probe_subprocess_does_not_load_qt(tmp_path):
    """子进程的导入图必须与桌面 UI 无关——判据打在子进程**实际加载的模块**上。

    照 ``tests/test_workers_entry.py`` 的形态：sitecustomize 在解析期记账，atexit 写盘。
    """
    package, _archive = build(tmp_path / "pkg")
    verifier = _verifier()
    descriptor = verifier.verify(package)
    from pet.feature_package_probe import probe_policy

    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    report = tmp_path / "loaded.json"
    (probe_dir / "sitecustomize.py").write_text(
        "import atexit, json, os, sys\n"
        "from pathlib import Path\n"
        "@atexit.register\n"
        "def _write():\n"
        "    Path(os.environ['PET_PROBE_IMPORT_REPORT']).write_text("
        "json.dumps(sorted(n for n in sys.modules if n.split('.')[0] == 'PySide6')), encoding='utf-8')\n",
        encoding="utf-8",
    )
    job = tmp_path / "job.json"
    verdict_path = tmp_path / "verdict.json"
    job.write_text(
        json.dumps({"schema": 1, "package_root": str(descriptor.root), "verdict_path": str(verdict_path), "policy": probe_policy(verifier)}),
        encoding="utf-8",
    )
    program, arguments, cwd = probe_command()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(probe_dir)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PET_PROBE_IMPORT_REPORT"] = str(report)
    completed = subprocess.run(
        [program, *arguments, str(job)], cwd=cwd, env=environment, capture_output=True, timeout=180, check=False
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert report.is_file(), "探针没写出报告：sitecustomize 未被加载"
    assert json.loads(report.read_text(encoding="utf-8")) == []
    assert parse_verdict(verdict_path, returncode=0).ok is True


def test_the_probe_command_covers_both_source_and_frozen_routes(tmp_path, monkeypatch):
    """源码态走解释器的 ``-m``（工作目录钉在包根），冻结态走应用自身的入口分流。"""
    program, arguments, cwd = probe_command()
    assert program == sys.executable
    assert arguments == ("-m", "pet.feature_package_preflight")
    assert Path(cwd) == ROOT

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    program, arguments, cwd = probe_command()
    assert arguments == (PROBE_FLAG,)
    assert Path(program).name == Path(sys.executable).name
    assert Path(cwd) == Path(sys.executable).parent


# ------------------------------------------------------------------- 拒绝路径

def test_the_probe_refuses_host_code_that_does_not_import(tmp_path):
    tree = source_tree(tmp_path / "src")
    (tree / "host" / "factory.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    package, _archive = build_tree(tree, tmp_path / "built")
    verdict = _run_probe(package)
    assert verdict.ok is False and verdict.reason == "probe_import_failed"
    assert verdict.metadata is None


def test_the_probe_refuses_a_factory_that_raises(tmp_path):
    tree = source_tree(tmp_path / "src")
    (tree / "host" / "factory.py").write_text("def create_host():\n    raise SystemExit(3)\n", encoding="utf-8")
    package, _archive = build_tree(tree, tmp_path / "built")
    assert _run_probe(package).reason == "probe_factory_failed"


def test_the_probe_refuses_a_factory_that_never_returns(tmp_path):
    """卡住的包在**装之前**就被拒（超时是有界的等待，不是节拍器）。"""
    tree = source_tree(tmp_path / "src")
    (tree / "host" / "factory.py").write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    package, _archive = build_tree(tree, tmp_path / "built")
    assert _run_probe(package, timeout=3.0).reason == "probe_timeout"


def test_the_probe_refuses_a_definition_that_claims_another_owner(tmp_path):
    """代码说的 owner 与清单说的不是一个：装之前就拒，别等装载阶段才发现。"""
    tree = source_tree(tmp_path / "src")
    factory = tree / "host" / "factory.py"
    factory.write_text(factory.read_text("utf-8").replace(f'OWNER = "{OWNER}"', 'OWNER = "demo.somebody-else"'), "utf-8")
    package, _archive = build_tree(tree, tmp_path / "built")
    assert _run_probe(package).reason == "probe_owner_mismatch"


def test_the_probe_refuses_a_host_only_definition_that_asks_for_a_worker(tmp_path):
    tree = source_tree(tmp_path / "src")
    factory = tree / "host" / "factory.py"
    factory.write_text(
        factory.read_text("utf-8").replace(
            "settings,", "settings,\n                         worker_launch_factory=lambda: None,", 1
        ),
        encoding="utf-8",
    )
    package, _archive = build_tree(tree, tmp_path / "built")
    assert _run_probe(package).reason == "probe_execution_kind_mismatch"


def test_the_probe_refuses_an_unsupported_policy(tmp_path):
    """子进程只认"用户自选的本地包"这一种策略；带信任锚的签名策略不猜、直接拒。"""
    package, _archive = build(tmp_path / "pkg")
    job = tmp_path / "job.json"
    verdict_path = tmp_path / "verdict.json"
    job.write_text(
        json.dumps({"schema": 1, "package_root": str(package), "verdict_path": str(verdict_path), "policy": {"allow_local_packages": False}}),
        encoding="utf-8",
    )
    program, arguments, cwd = probe_command()
    completed = subprocess.run([program, *arguments, str(job)], cwd=cwd, capture_output=True, timeout=180, check=False)
    assert completed.returncode == 78
    verdict = parse_verdict(verdict_path, returncode=completed.returncode)
    assert verdict.ok is False and verdict.reason == "probe_policy_unsupported"


def test_the_probe_refuses_bytes_that_changed_after_verification(tmp_path):
    """父进程验过之后字节又变了：子进程按**当下磁盘**重新验，对不上就拒。

    这条同时说明了"探针说行"为什么不能被当授权：它每次只看它自己那一刻的字节，
    真正的执行授权仍由宿主按同一套完整校验链给。
    """
    package, _archive = build(tmp_path / "pkg")
    verifier = _verifier()
    descriptor = verifier.verify(package)
    payload = package / "host" / "factory.py"
    payload.write_bytes(payload.read_bytes() + b"\n# tampered\n")
    verdict = LocalPackageProbe().run(descriptor, verifier)
    assert verdict.ok is False and verdict.reason == "probe_verification_failed"


def test_the_child_refuses_a_missing_or_unusable_job(tmp_path):
    program, arguments, cwd = probe_command()
    completed = subprocess.run([program, *arguments], cwd=cwd, capture_output=True, timeout=180, check=False)
    assert completed.returncode == 78
    assert b"missing job" in completed.stderr

    broken = tmp_path / "job.json"
    broken.write_text("{ not json", encoding="utf-8")
    completed = subprocess.run([program, *arguments, str(broken)], cwd=cwd, capture_output=True, timeout=180, check=False)
    assert completed.returncode == 78


# --------------------------------------------------------- 父侧信任缝（解析）

@pytest.mark.parametrize(
    "content, returncode",
    [
        (b"", 0),
        (b"{ not json", 0),
        (b"[]", 0),
        (json.dumps({"schema": 99, "ok": True}).encode(), 0),
        (json.dumps({"schema": 1, "ok": True}).encode(), 1),  # 回执说行、退出码说不行
        (json.dumps({"schema": 1, "ok": False, "reason": "whatever"}).encode(), 78),
        (json.dumps({"schema": 1, "ok": True, "metadata": {"owner": ""}}).encode(), 0),
    ],
)
def test_an_untrustworthy_verdict_is_always_a_refusal(tmp_path, content, returncode):
    """子进程写的东西一律先按形状拒：错 schema / 未知原因码 / 自相矛盾 ⇒ ``probe_failed``。"""
    path = tmp_path / "verdict.json"
    path.write_bytes(content)
    verdict = parse_verdict(path, returncode=returncode)
    assert verdict.ok is False
    assert verdict.reason == "probe_failed"


def test_a_missing_verdict_file_is_a_refusal(tmp_path):
    verdict = parse_verdict(tmp_path / "absent.json", returncode=1)
    assert verdict.ok is False and verdict.reason == "probe_failed"


def test_every_child_reason_code_is_prefixed_and_known(tmp_path):
    """父子两侧的原因码是同一张闭集表：父侧只会把它们加 ``probe_`` 前缀转出去。"""
    assert "job_invalid" in CHILD_REASONS and "verification_failed" in CHILD_REASONS
    path = tmp_path / "verdict.json"
    for reason in sorted(CHILD_REASONS):
        path.write_text(json.dumps({"schema": 1, "ok": False, "reason": reason}), encoding="utf-8")
        assert parse_verdict(path, returncode=78).reason == "probe_" + reason
