# -*- coding: utf-8 -*-
"""官方识屏包的 Worker 入口：Core 根自举 + 租约交接绑定的 Core Worker 运行时。

包内不复制 Worker 实现——Core 已含（``pet/workers/proactive_screen_worker.py``，
内置识屏在用）；本包的隔离边界是**进程 + 验签 + HANDOFF 租约交接**：
验签链保证这个入口就是包里的那份字节，``run_screen_worker_entry`` 在拿不到
宿主交接 token 时 fail-closed（77），绝不裸跑截图/视觉请求。
"""

from __future__ import annotations

import os
import sys

_CORE_ROOT = os.environ.get("DSH_PET_CORE_ROOT")
if _CORE_ROOT:
    sys.path.insert(0, _CORE_ROOT)


def main() -> int:
    from pet.workers.screen_entry import run_screen_worker_entry

    return run_screen_worker_entry()


if __name__ == "__main__":
    raise SystemExit(main())
