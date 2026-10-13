# -*- coding: utf-8 -*-
"""内置 worker 入口白名单（`python -m pet --worker <id>`）。

移植自 DLC 分支 `pet/workers/worker_entry.py`，只保留本拓扑真正实现的 worker：
DLC 还有 `agent-link-events`，但主线 `agent_link`（6303 行）+ 多 DSH 分区是现行
权威（PLAN.md 判定「暂不移植」），所以白名单里没有它——留一个必然
``ModuleNotFoundError`` 的分支比没有分支更糟。

**本模块是子进程路由的一部分，禁止导入任何桌面 UI/Qt**：`pet/__main__.py` 的
`--worker` 分流必须早于 `pet.app`，事件采集/识屏进程不得初始化 QApplication、
窗口或 Chat UI。守卫见 `tests/test_workers_entry.py` 的真进程导入探针。
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

#: 允许多少个内置 worker 就写多少个；白名单之外一律拒绝（退出码 2）。
_WORKERS = frozenset({"proactive-screen"})


def main(worker_id: str | None = None, argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    selected = worker_id or (args[0] if args else "")
    if selected not in _WORKERS:
        sys.stderr.write(f"unknown worker: {selected or '<missing>'}\n")
        return 2
    if selected == "proactive-screen":
        # 延迟导入：白名单校验先于任何 worker 实现加载，拒绝路径不付导入成本。
        from .proactive_screen_worker import run_proactive_screen_worker

        return run_proactive_screen_worker()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
