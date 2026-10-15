# -*- coding: utf-8 -*-
"""官方识屏包的 Worker 入口：Core 根自举 + 租约交接认领 + Core Worker 运行时。

包内不复制 Worker 实现——Core 已含（``pet/workers/proactive_screen_worker.py``，
内置识屏在用）；本包的隔离边界是**进程 + 验签 + 租约交接**：

* 验签链保证这个入口就是包里的那份字节（``FeaturePackageLoader`` 按摘要装载）；
* 子进程必须认领宿主下发的租约交接（``DSH_PET_WORKER_HANDOFF_TOKEN`` +
  ``DSH_PET_FEATURE_DATA_ROOT`` + owner，经
  :func:`pet.workers.lease_bootstrap.claim_worker_lease_from_environment` 向
  租约协调器认领）——拿不到交接或认领失败一律 fail-closed（77），绝不裸跑
  截图/视觉请求（``mod_api.worker_v1.serve`` 的冻结态口径，这里源码态同样要求）。
"""

from __future__ import annotations

import os
import sys

_CORE_ROOT = os.environ.get("DSH_PET_CORE_ROOT")
if _CORE_ROOT:
    sys.path.insert(0, _CORE_ROOT)

#: 与 pet/workers/screen_entry.py 同口径：77 = 交接前提不成立。
EXIT_PRECONDITION_MISSING = 77


def main() -> int:
    try:
        from pet.workers.lease_bootstrap import claim_worker_lease_from_environment
    except ImportError:
        return EXIT_PRECONDITION_MISSING
    try:
        if not claim_worker_lease_from_environment():
            return EXIT_PRECONDITION_MISSING
    except Exception:
        return EXIT_PRECONDITION_MISSING
    from pet.workers.proactive_screen_worker import run_proactive_screen_worker

    return run_proactive_screen_worker()


if __name__ == "__main__":
    raise SystemExit(main())
