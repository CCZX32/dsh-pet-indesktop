# -*- coding: utf-8 -*-
"""独立识屏入口：沙箱探针模式，或**租约绑定**的正常执行。

移植自 DLC 分支 `pet/workers/screen_entry.py`。它和 ``pet/__main__.py`` 的
``--worker`` 分流是**两条不同的路由**：

* ``--worker``（in-Core 路由，见 `pet/workers/worker_entry.py`）——内置 worker，
  由宿主进程的 supervisor 直接拉起；
* 本入口——给**独立安装的可执行包**用：拿不到交接就 fail-closed，绝不在
  「我是谁」没被证明的情况下执行截图/视觉请求。

宿主面改动（S4 收口后的现状）：

1. **DLC 首行的 ``activate_frozen_dependency_path()`` 已补齐并接通**（S3 登记为
   冻结态缺口 #1）。冻结版 onedir 下，``_dsh_probe_native.pyd`` 位于执行文件自己的
   密封依赖目录；安装路径一长，``LoadLibrary`` 就以「文件名或扩展名太长」失败，
   探针因此永远拿不到沙箱证据。实测与依据见 `pet/frozen_runtime_paths.py` 的模块
   docstring（修复前/后原始输出在 ``.scratch/dlc-fusion/S4-HANDOFF.md``）。
2. DLC 的 ``claim_worker_lease_from_environment()``（``lease_bootstrap``）绑在功能包
   版本租约子系统上，本拓扑未移植（S2 判定）。这里用 S2 定下的**通用**交接契约：
   宿主经 :data:`pet.workers.launch.HANDOFF_TOKEN_ENV` 下发一次性 token，子进程
   见到它才算认领（同 ``hello.payload.lease_claimed`` 的判据）。
3. 探针模式（``--feature-package-probe``）依赖原生沙箱 ``_dsh_probe_native``。
   **沙箱没生效就不跑探针**这条纪律不变；S4 起它不再是一句没有内容的 77——
   :func:`sandbox_verdict` 把四种前置状态分开，:func:`_probe` 在 77 时往 stderr
   写一行有界 JSON。原因见 ``pet/mod_center_controller.py`` 的缺陷指针对照。

**本模块是子进程路由的一部分，禁止导入任何桌面 UI/Qt。**
"""

from __future__ import annotations

import json
import os
import sys

from ..frozen_runtime_paths import activate_frozen_dependency_path

#: 探针模式的唯一合法参数（与宿主侧拼的 argv 逐字对应）。
FEATURE_PACKAGE_PROBE = "--feature-package-probe"

#: 退出码语义（与 DLC 逐字相同）：77 = 沙箱/租约前提不成立，78 = 用法或协议不符。
EXIT_PRECONDITION_MISSING = 77
EXIT_USAGE_INVALID = 78

#: 探针前置状态的四种取值（``sandbox_verdict`` 的返回面）。
SANDBOX_ENFORCED = "enforced"
SANDBOX_MODULE_MISSING = "module_missing"
SANDBOX_MODULE_UNUSABLE = "module_unusable"
SANDBOX_NOT_ENFORCED = "not_enforced"

#: stderr 诊断行的上限（有界，绝不把异常文本整篇倒出去）。
_REFUSAL_LINE_LIMIT = 512


def sandbox_verdict() -> str:
    """探针沙箱前置条件的**如实**判定（四种取值，见常量面）。

    为什么不是一句 bool：``_dsh_probe_native`` 缺席、存在但说沙箱没生效、以及
    导入/调用本身炸了（缺 DLL 的典型形态），是三种不同的缺陷，修法完全不同。
    DLC 的缺陷登记里 ``hello-local`` 的准确 reason 至今是"待补信息"——
    上游看到的所有形态都只是同一个 77。
    """
    try:
        import _dsh_probe_native
    except ImportError:
        return SANDBOX_MODULE_MISSING
    except (OSError, AttributeError):
        return SANDBOX_MODULE_UNUSABLE
    try:
        return SANDBOX_ENFORCED if _dsh_probe_native.sandbox_enforced() is True else SANDBOX_NOT_ENFORCED
    except (OSError, AttributeError, ValueError):
        return SANDBOX_MODULE_UNUSABLE


def sandbox_enforced() -> bool:
    """原生沙箱是否真的在生效（只有冻结版探针 bundle 提供这个模块）。"""
    return sandbox_verdict() == SANDBOX_ENFORCED


def claim_worker_handoff() -> bool:
    """认领宿主下发的交接 token（S2 的通用租约契约）。

    没有 token 就是「没被交接」——本入口 fail-closed，不猜、不超时兜底。
    """
    from .launch import HANDOFF_TOKEN_ENV

    return bool(os.environ.get(HANDOFF_TOKEN_ENV))


def _refuse(stderr, reason: str) -> None:
    """把 77 的原因写成一行有界 JSON；stderr 不可用就放弃诊断，绝不因此改变退出码。"""
    if stderr is None:
        return
    line = json.dumps({"schema": 1, "kind": "probe_refused", "reason": reason}, sort_keys=True) + "\n"
    try:
        stderr.write(line[:_REFUSAL_LINE_LIMIT])
        stderr.flush()
    except (OSError, ValueError, AttributeError):
        return


def _probe(source, output, stderr=None) -> int:
    """沙箱内自证：只在沙箱确实生效时握手，否则 77（不跑探针）。"""
    verdict = sandbox_verdict()
    if verdict != SANDBOX_ENFORCED:
        _refuse(stderr, verdict)
        return EXIT_PRECONDITION_MISSING
    from .protocol import MAX_MESSAGE_BYTES, WorkerProtocolError, build_message, decode_message, encode_message

    output.write(encode_message(build_message("proactive-screen", "hello", {"probe": True, "capabilities": []})))
    output.flush()
    try:
        raw = source.readline(MAX_MESSAGE_BYTES + 1)
        if not raw or not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE_BYTES:
            return EXIT_USAGE_INVALID
        message = decode_message(raw)
        if message.worker_id != "proactive-screen" or message.type != "shutdown" or message.payload:
            return EXIT_USAGE_INVALID
        return 0
    except (WorkerProtocolError, OSError, ValueError):
        return EXIT_USAGE_INVALID


def run_screen_worker_entry(argv=None, *, source=None, output=None, stderr=None, run_runtime=None) -> int:
    """独立入口主体：探针模式或租约绑定的正常执行。

    ``run_runtime`` / ``source`` / ``output`` / ``stderr`` 四个注入口只为测试存在
    （生产调用一律走默认），前三个语义与 DLC 相同；``stderr`` 是 S4 加的 77 诊断口。

    首行修冻结版依赖目录的长路径查找，是 DLC 原文的次序——**在参数解析之前**，
    两条路由都要走（探针要 import 的 ``_dsh_probe_native`` 就在那个密封目录里）。
    布局与 onedir 约定不符时它抛 :class:`ValueError`，这里**不捕**：那是构建缺陷，
    静默降级成 77 正是原缺陷难以定位的成因。
    """
    activate_frozen_dependency_path()
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        if args != [FEATURE_PACKAGE_PROBE]:
            return EXIT_USAGE_INVALID
        return _probe(source or sys.stdin.buffer, output or sys.stdout.buffer, stderr or sys.stderr)
    # 这一 import（含租约机制）在探针模式里是禁止的：上面已先行返回。
    try:
        if not claim_worker_handoff():
            return EXIT_PRECONDITION_MISSING
    except Exception:
        return EXIT_PRECONDITION_MISSING
    if run_runtime is not None:
        return run_runtime()
    from .proactive_screen_worker import run_proactive_screen_worker

    return run_proactive_screen_worker()


if __name__ == "__main__":
    raise SystemExit(run_screen_worker_entry())
