# -*- coding: utf-8 -*-
"""跨进程 MOD 收敛测试的**子进程**侧：真实设置进程角色的管理动作。

由 ``tests/test_mod_catalog_convergence.py`` 以 ``python -m tests._feature_management_child``
拉起（cwd=仓库根），stdin 收一份 JSON：

    {"base": "<Config base>", "action": "enable", "owner": "...", "value": true}
    {"base": "<Config base>", "action": "install", "package": "<构建产物目录>", "enabled": true}

子进程里装配的是 ``role="settings"`` 的 **真宿主**（与独立设置进程同一角色），
动作走完事务全链（验签/租约/状态账本/修订令牌落盘），stdout 回一行 JSON 结果。
不是替身：账本改动与 ``mod-catalog.revision`` 令牌都是生产代码写出的真字节。
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from pet.config import Config
    from pet.feature_management import LocalFeatureRuntime

    document = json.loads(sys.stdin.buffer.read(65537).decode("utf-8"))
    app = QApplication([])
    runtime = LocalFeatureRuntime(Config(base=document["base"]), role="settings")
    try:
        if document["action"] == "install":
            owner = runtime.route(document["package"])
            if owner is None:
                print(json.dumps({"status": "rejected", "reason": "route_failed"}))
                return 1
            manager = runtime.managers[owner]
            accepted = manager.submit_local_source(
                document["package"], auto_apply=True, enabled=bool(document.get("enabled", True)))
        else:
            manager = runtime.managers.get(document["owner"])
            if manager is None:
                print(json.dumps({"status": "rejected", "reason": "owner_unknown"}))
                return 1
            accepted = manager.submit(
                "enable", bool(document["value"]),
                expected_revision=manager.service.inspect().revision)
        if not accepted:
            print(json.dumps({"status": "rejected", "reason": "busy"}))
            return 1
        deadline = time.monotonic() + 60.0
        while manager.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        if manager.busy:
            print(json.dumps({"status": "timeout"}))
            return 1
        result = manager.last_result
        print(json.dumps({
            "status": getattr(result, "status", None),
            "reason": getattr(result, "reason", ""),
            "owner": manager.owner,
        }))
        return 0
    finally:
        runtime.close()
        app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
