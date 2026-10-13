# -*- coding: utf-8 -*-
"""独立识屏入口：沙箱探针模式，或**租约绑定**的正常执行。

移植自 DLC 分支 `pet/workers/screen_entry.py`。它和 ``pet/__main__.py`` 的
``--worker`` 分流是**两条不同的路由**：

* ``--worker``（in-Core 路由，见 `pet/workers/worker_entry.py`）——内置 worker，
  由宿主进程的 supervisor 直接拉起；
* 本入口——给**独立安装的可执行包**用：拿不到交接就 fail-closed，绝不在
  「我是谁」没被证明的情况下执行截图/视觉请求。

宿主面改动与缺口（如实登记，不在本片修）：

1. DLC 首行的 ``pet.frozen_runtime_paths.activate_frozen_dependency_path()``
   本拓扑没有该模块（它只服务冻结版 onedir 的扩展长路径 `_internal` 查找）。
   **这是冻结态缺口**：冻结版下依赖查找依赖 PyInstaller 默认行为；与 PLAN.md
   标注的「绑冻结版探针 bundle」缺口同一族，属 S4（探针 bundle 一轮）。
2. DLC 的 ``claim_worker_lease_from_environment()``（``lease_bootstrap``）绑在功能包
   版本租约子系统上，本拓扑未移植（S2 判定）。这里用 S2 定下的**通用**交接契约：
   宿主经 :data:`pet.workers.launch.HANDOFF_TOKEN_ENV` 下发一次性 token，子进程
   见到它才算认领（同 ``hello.payload.lease_claimed`` 的判据）。
3. 探针模式（``--feature-package-probe``）依赖原生沙箱 ``_dsh_probe_native``，
   本拓扑没有：``sandbox_enforced()`` 恒为 False，探针一律以 77 退出（**沙箱未
   生效就不跑探针**）。这正是 PLAN.md 里 ZIP 导入探针缺陷的同一条根因，
   **不得表述为已修复**。

**本模块是子进程路由的一部分，禁止导入任何桌面 UI/Qt。**
"""

from __future__ import annotations

import os
import sys

#: 探针模式的唯一合法参数（与宿主侧拼的 argv 逐字对应）。
FEATURE_PACKAGE_PROBE = "--feature-package-probe"

#: 退出码语义（与 DLC 逐字相同）：77 = 沙箱/租约前提不成立，78 = 用法或协议不符。
EXIT_PRECONDITION_MISSING = 77
EXIT_USAGE_INVALID = 78


def sandbox_enforced() -> bool:
    """原生沙箱是否真的在生效（只有冻结版探针 bundle 提供这个模块）。"""
    try:
        import _dsh_probe_native

        return _dsh_probe_native.sandbox_enforced() is True
    except (ImportError, OSError, AttributeError):
        return False


def claim_worker_handoff() -> bool:
    """认领宿主下发的交接 token（S2 的通用租约契约）。

    没有 token 就是「没被交接」——本入口 fail-closed，不猜、不超时兜底。
    """
    from .launch import HANDOFF_TOKEN_ENV

    return bool(os.environ.get(HANDOFF_TOKEN_ENV))


def _probe(source, output) -> int:
    """沙箱内自证：只在沙箱确实生效时握手，否则 77（不跑探针）。"""
    if not sandbox_enforced():
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


def run_screen_worker_entry(argv=None, *, source=None, output=None, run_runtime=None) -> int:
    """独立入口主体：探针模式或租约绑定的正常执行。

    ``run_runtime`` / ``source`` / ``output`` 三个注入口只为测试存在（生产调用
    一律走默认），语义与 DLC 相同。
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        if args != [FEATURE_PACKAGE_PROBE]:
            return EXIT_USAGE_INVALID
        return _probe(source or sys.stdin.buffer, output or sys.stdout.buffer)
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
