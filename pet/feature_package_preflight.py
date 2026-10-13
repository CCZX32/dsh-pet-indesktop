# -*- coding: utf-8 -*-
"""本地功能包的**子进程预检**：元信息提取 + 装前失败检查。**不是沙箱。**

本模块回答一个很窄的问题：**这个包真的能装载吗？它自己声明的 owner / 执行形态与
清单一致吗？** 做法是把包的 ``host/factory.py`` 在**另一个进程**里按同一份验签字节
导入一次，读回它 ``create_host()`` 返回的 ``FeatureDefinition``，然后立刻丢掉那个进程。

为什么值得单起一个进程（而不是在管理器里直接 import）：

* 包代码可以抛任何东西、可以卡死、可以在导入期做它想做的任何事——子进程把这些
  影响挡在本进程之外（``probe_timeout`` 就是这条的机器证据），也**不占用本进程的
  host 租约**（``FeaturePackageLoader`` 的 ``imported`` 旗标只在子进程里被立起来）；
* 管理器进程（GUI / 后台线程）不该为一次"能不能装"的判断付一份永久 pin 的代价；
* 失败在**装之前**说清楚：包坏了/owner 对不上/声明与代码矛盾，这几件事在现有链路上
  只能等到装载阶段才暴露，那时状态已经落盘，用户看到的是"安装状态已保存，但加载未完成"。

**它不声称任何隔离**（与 ``pet/feature_package_probe.py`` 里那条 LPAC 契约的区别）：

* 没有 OS 沙箱——同一个用户、同样的权限、同一份文件系统；
* 环境变量清理 / 临时目录 / 超时**都不是安全边界**（``pet.feature_package_probe``
  的模块 docstring 已经把这条写死，本模块不推翻它）；
* 超时只做一件事：杀掉**这次直接起的那个**子进程，不让一个卡住的包拖住安装动作。
  包代码自己再拉起的进程不在管辖范围（那正是"不是沙箱"的意思），也**不**冒充分级进程树清理；
* 探针的 ``ok`` **不授权任何执行**。它只在"拒绝"方向有权威（说不行的就是不行），
  说行的那一半仍由宿主进程按完整验签链自己重新回答——子进程的结论永远不当作证据。
* 子进程只**读**包，绝不调用 Runtime / settings / Worker：不截图、不读凭据、不请求模型。

ZIP 与目录在这里没有分叉：两条路在 ``feature_package_transactions._preflight`` 里就已
归一成同一个已解包目录，探针看到的只有那份 ``staged_root``。

零 Qt：本模块既是父侧运行器，也是子侧入口（``python -m pet.feature_package_preflight
<job.json>`` / 冻结态 ``<exe> --feature-package-probe <job.json>``），子进程里连
QApplication 的影子都不该有。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .feature_package_probe import probe_policy
from .plugins.package_trust import FeaturePackageVerifier, PackageVerificationError, VerificationLimits
from .workers.launch import isolated_worker_environment

#: 父子两侧共用的作业/回执版本号。形状变了就要升它（父侧旧版本一律拒收）。
PROBE_SCHEMA = 1

#: 冻结态的子进程分流参数（``pet/__main__.py``）；源码态走 ``-m pet.feature_package_preflight``。
PROBE_FLAG = "--feature-package-probe"

#: 一次探针的默认预算。与 Phase 4B 的 30s 同口径（单条上限，不是节拍器）。
DEFAULT_TIMEOUT = 30.0

#: 作业与回执的有界读取上限（子进程写的东西一律不信，先按尺寸拒）。
_IO_LIMIT = 64 * 1024

#: 子进程允许回报的原因码（**闭集**）。父侧只认这几个，其余一律折成 ``probe_failed``
#: ——子进程的 stderr / 异常文本不进宿主的原因码，也不进 UI 文案。
CHILD_REASONS = frozenset(
    {
        "job_invalid",
        "policy_unsupported",
        "verification_failed",
        "import_failed",
        "factory_unavailable",
        "factory_failed",
        "definition_invalid",
        "owner_mismatch",
        "execution_kind_mismatch",
    }
)

#: 元信息的保守上界（子进程写回的结构一样要有界）。
_MAX_CONTRIBUTIONS = 64
_MAX_TEXT = 256


@dataclass(frozen=True)
class ProbeMetadata:
    """子进程从 ``create_host()`` 的返回值里读回的公开元信息（有界、只读）。"""

    owner: str
    mount_contract: str
    contributions: tuple[tuple[str, str, str], ...]
    has_runtime: bool
    has_settings: bool

    def document(self) -> dict:
        return {
            "owner": self.owner,
            "mount_contract": self.mount_contract,
            "contributions": [list(item) for item in self.contributions],
            "has_runtime": self.has_runtime,
            "has_settings": self.has_settings,
        }


@dataclass(frozen=True)
class ProbeVerdict:
    """一次探针的结论。

    ``reason`` 只会是两张闭集里的值：子进程回报的（:data:`CHILD_REASONS`，父侧加
    ``probe_`` 前缀）与父侧自己产生的（``probe_unavailable`` / ``probe_timeout`` /
    ``probe_failed``）。子进程的异常文本、stderr、包内路径**都不进**这里。
    """

    ok: bool
    reason: str | None = None
    metadata: ProbeMetadata | None = None
    child_pid: int | None = None


# --------------------------------------------------------------------- 父侧


def probe_command() -> tuple[str, tuple[str, ...], str]:
    """``(program, 固定参数, 工作目录)``——探针子进程怎么起。

    与 ``WorkerSupervisor._resolve_command`` 同源：冻结态用应用自身的入口分流
    （``sys.executable`` 就是那个 exe），源码态用解释器的 ``-m``。源码态必须把工作目录
    钉在包根上——``isolated_worker_environment`` 会丢掉 ``PYTHON*/_PYI/_MEIPASS``，
    ``-m`` 靠工作目录把 ``pet`` 放进 ``sys.path[0]``。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, (PROBE_FLAG,), str(Path(sys.executable).parent)
    return sys.executable, ("-m", "pet.feature_package_preflight"), str(Path(__file__).resolve().parents[1])


def _core_roots() -> tuple[Path, ...]:
    """冻结态的 Core 根（与 ``ProductionFeatureStartup._core_roots`` 同一判据）。"""
    if not getattr(sys, "frozen", False):
        return ()
    return (Path(sys.executable).parent, Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))


def _bounded_text(value) -> str:
    return value if isinstance(value, str) and len(value) <= _MAX_TEXT else ""


def parse_verdict(path: Path | str, *, returncode: int) -> ProbeVerdict:
    """严格读回子进程写的回执；任何不符形状的输入都折成 ``probe_failed``。

    这是**父侧唯一的信任缝**：schema、原因码闭集、元信息形状逐项校验，子进程多写的
    字段一律不看（也不透传）。
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        # 子进程死在写回执之前（导入期崩、解释器起不来）——超时由 run() 自己判。
        return ProbeVerdict(False, "probe_failed")
    if not raw or len(raw) > _IO_LIMIT:
        return ProbeVerdict(False, "probe_failed")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ProbeVerdict(False, "probe_failed")
    if not isinstance(payload, dict) or payload.get("schema") != PROBE_SCHEMA or type(payload.get("ok")) is not bool:
        return ProbeVerdict(False, "probe_failed")
    pid = payload.get("child_pid")
    child_pid = pid if type(pid) is int and pid > 0 else None
    if payload["ok"] is True:
        if returncode != 0:
            # 回执说行、退出码说不行：两边不一致就按不行算，不猜。
            return ProbeVerdict(False, "probe_failed", child_pid=child_pid)
        metadata = _parse_metadata(payload.get("metadata"))
        if metadata is None:
            return ProbeVerdict(False, "probe_failed", child_pid=child_pid)
        return ProbeVerdict(True, None, metadata, child_pid)
    reason = payload.get("reason")
    if reason not in CHILD_REASONS:
        return ProbeVerdict(False, "probe_failed", child_pid=child_pid)
    return ProbeVerdict(False, "probe_" + reason, child_pid=child_pid)


def _parse_metadata(value) -> ProbeMetadata | None:
    if not isinstance(value, dict):
        return None
    owner = _bounded_text(value.get("owner"))
    if not owner:
        return None
    contract = value.get("mount_contract")
    contributions = value.get("contributions")
    if not isinstance(contract, str) or len(contract) > _MAX_TEXT or not isinstance(contributions, list) or len(contributions) > _MAX_CONTRIBUTIONS:
        return None
    items = []
    for entry in contributions:
        if not isinstance(entry, list) or len(entry) != 3 or any(not isinstance(part, str) or len(part) > _MAX_TEXT for part in entry):
            return None
        items.append(tuple(entry))
    return ProbeMetadata(
        owner=owner,
        mount_contract=contract,
        contributions=tuple(items),
        has_runtime=value.get("has_runtime") is True,
        has_settings=value.get("has_settings") is True,
    )


@dataclass(frozen=True)
class LocalPackageProbe:
    """把一份已验签的包交给子进程做一次预检（元信息 + 装前失败检查）。

    不是沙箱：见模块 docstring。``timeout`` 是单次上限，不是节拍器。
    """

    timeout: float = DEFAULT_TIMEOUT

    def run(self, descriptor, verifier: FeaturePackageVerifier) -> ProbeVerdict:
        root = getattr(descriptor, "root", None)
        if root is None or not isinstance(verifier, FeaturePackageVerifier):
            return ProbeVerdict(False, "probe_unavailable")
        program, arguments, cwd = probe_command()
        try:
            with tempfile.TemporaryDirectory(prefix="dsh-pet-feature-probe-") as scratch:
                job_path, verdict_path = Path(scratch) / "job.json", Path(scratch) / "verdict.json"
                job = {
                    "schema": PROBE_SCHEMA,
                    "package_root": str(root),
                    "verdict_path": str(verdict_path),
                    "policy": probe_policy(verifier),
                }
                job_path.write_text(json.dumps(job, ensure_ascii=True), encoding="utf-8")
                environment = isolated_worker_environment(os.environ, core_roots=_core_roots())
                # 子进程只读包、只在私有临时目录里写回执；不写 __pycache__。
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                try:
                    completed = subprocess.run(
                        [program, *arguments, str(job_path)],
                        cwd=cwd,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=self.timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    return ProbeVerdict(False, "probe_timeout")
                return parse_verdict(verdict_path, returncode=completed.returncode)
        except (OSError, ValueError, subprocess.SubprocessError):
            return ProbeVerdict(False, "probe_unavailable")


__all__ = [
    "CHILD_REASONS",
    "DEFAULT_TIMEOUT",
    "PROBE_FLAG",
    "PROBE_SCHEMA",
    "LocalPackageProbe",
    "ProbeMetadata",
    "ProbeVerdict",
    "child_main",
    "parse_verdict",
    "probe_command",
]


# --------------------------------------------------------------------- 子侧


def _verifier_from_policy(policy) -> FeaturePackageVerifier | None:
    """只有"用户自选的本地包"这一种策略能在子进程里重建。

    带信任锚 / 非本地激活的策略要求 Core 自己的密钥材料，子进程不持有，也不猜
    ——直接按 ``policy_unsupported`` 拒绝。
    """
    if not isinstance(policy, Mapping) or policy.get("allow_local_packages") is not True:
        return None
    if policy.get("trust_anchors") or policy.get("anchor_policy"):
        return None
    limits = policy.get("limits")
    capabilities = policy.get("allowed_capabilities")
    if not isinstance(limits, Mapping) or not isinstance(capabilities, list):
        return None
    try:
        return FeaturePackageVerifier(
            core_version=policy["core_version"],
            api_version=policy["api_version"],
            platform=policy["platform"],
            allowed_capabilities=frozenset(capabilities),
            allow_local_packages=True,
            limits=VerificationLimits(**dict(limits)),
            feature_id=policy["feature_id"],
        )
    except (KeyError, TypeError, ValueError, PackageVerificationError):
        return None


def _metadata(definition, *, owner: str) -> ProbeMetadata:
    contributions = getattr(definition, "menus", ())
    items = []
    if isinstance(contributions, (list, tuple)):
        for item in contributions[:_MAX_CONTRIBUTIONS]:
            items.append((_bounded_text(getattr(item, "id", "")), _bounded_text(getattr(item, "kind", "")), _bounded_text(getattr(item, "command", ""))))
    return ProbeMetadata(
        owner=owner,
        mount_contract=_bounded_text(getattr(definition, "mount_contract", "")),
        contributions=tuple(items),
        has_runtime=callable(getattr(definition, "runtime_factory", None)),
        has_settings=callable(getattr(definition, "settings_factory", None)),
    )


def _verdict(ok: bool, reason: str | None, *, metadata: ProbeMetadata | None = None) -> dict:
    if not ok and reason not in CHILD_REASONS:
        reason = "import_failed"
    return {
        "schema": PROBE_SCHEMA,
        "ok": ok,
        "reason": reason,
        "child_pid": os.getpid(),
        "metadata": metadata.document() if metadata is not None else None,
    }


def _inspect_definition(definition, descriptor) -> tuple[ProbeMetadata | None, str | None]:
    """把 ``create_host()`` 的返回值对照清单逐项核；不符就给出固定的原因码。"""
    from .plugins.feature_host import FeatureDefinition

    if not isinstance(definition, FeatureDefinition):
        return None, "definition_invalid"
    if definition.owner != descriptor.id:
        return None, "owner_mismatch"
    if not callable(getattr(definition, "settings_factory", None)):
        return None, "definition_invalid"
    if descriptor.execution_kind == "host-only" and (definition.worker_launch_factory is not None or definition.allow_in_process is not True):
        # 与 ``plugins/package_binding.bind_verified_feature`` 的同一条判据：
        # host-only 不许要 Worker（端点装配会在装载时才拒，这里提前说清楚）。
        return None, "execution_kind_mismatch"
    return _metadata(definition, owner=descriptor.id), None


def _job(raw: bytes | None) -> dict | None:
    if raw is None or not raw or len(raw) > _IO_LIMIT:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != PROBE_SCHEMA:
        return None
    root = payload.get("package_root")
    if not isinstance(root, str) or not root:
        return None
    return payload


def _extract(argv: Sequence[str]) -> Path | None:
    """从两种入口形态里取那个作业文件（源码态 ``-m … <job>`` / 冻结态 ``--flag <job>``）。"""
    positionals = [item for item in argv if item and not item.startswith("--")]
    return Path(positionals[0]) if len(positionals) == 1 else None


def child_main(argv: Sequence[str] | None = None) -> int:
    """子进程入口：读作业 → 预检 → 写回执。退出码 0 = ``ok``，78 = 拒绝。"""
    args = list(sys.argv[1:] if argv is None else argv)
    job_path = _extract(args)
    if job_path is None:
        sys.stderr.write("feature package probe: missing job file\n")
        return 78
    try:
        raw = job_path.read_bytes()
    except OSError:
        sys.stderr.write("feature package probe: job unreadable\n")
        return 78
    if raw and len(raw) > _IO_LIMIT:
        raw = raw[:_IO_LIMIT]
    try:
        payload = _job(raw)
    except (OSError, ValueError, TypeError):
        payload = None
    if payload is None:
        sys.stderr.write("feature package probe: invalid job\n")
        return 78
    verdict_path = Path(payload.get("verdict_path") or "")
    try:
        result = _probe(payload)
    except BaseException:  # 包代码抛什么都由这个进程接住；宿主不许看到它的 traceback
        result = _verdict(False, "import_failed")
    try:
        verdict_path.write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    except (OSError, ValueError):
        return 78
    return 0 if result["ok"] else 78


def _probe(payload: Mapping) -> dict:
    verifier = _verifier_from_policy(payload.get("policy"))
    if verifier is None:
        return _verdict(False, "policy_unsupported")
    root = Path(str(payload["package_root"]))
    try:
        descriptor = verifier.verify(root)
    except (PackageVerificationError, OSError, ValueError, TypeError, RecursionError):
        return _verdict(False, "verification_failed")
    from .plugins.feature_packages import FeaturePackageLoader

    try:
        handle = FeaturePackageLoader(verifier).load_host(descriptor)
    except BaseException:
        # 包代码在导入期抛什么都在这里收口；异常文本不进回执（只给固定原因码）。
        return _verdict(False, "import_failed")
    try:
        try:
            factory = handle.factory
        except (PackageVerificationError, OSError, ValueError):
            return _verdict(False, "factory_unavailable")
        try:
            definition = factory()
        except BaseException:
            return _verdict(False, "factory_failed")
        metadata, reason = _inspect_definition(definition, descriptor)
        return _verdict(False, reason) if reason is not None else _verdict(True, None, metadata=metadata)
    finally:
        try:
            handle.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(child_main())
