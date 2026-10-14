# -*- coding: utf-8 -*-
"""apply 重试阶梯 × 宿主装回：两条都走**真链路**（真事务层 + 真宿主 + 真控制器）。

既有的两条用例各自只盖住一半：``tests/test_feature_management.py::
test_a_failed_apply_puts_the_old_version_back_in_the_host`` 把 ``service.apply``
整个换掉（测的是"装回"这件事本身），``tests/test_mod_center_controller.py`` 用替身
管理器测重试阶梯。两条合起来才能看见的真缺陷是这里这两条（盲审 N1 / N2）：

* **N1**：装回会把本进程的版本 pin 重新占上，而控制器的重试阶梯恰好要在**已交还**
  的状态下才走得通——重试于是被自己挡死（``version_in_use``），用户拿到一句
  "等待相关程序自然退出后完成操作"，而挡路的正是他自己这只桌宠，退出也解不开。
* **N2**：事务在 ``state_pending`` 之后失败时（落盘的 active 已经指向候选版本），
  装回会走进 ``load_pending`` 的启动确认路；本进程不是那个启动方，
  ``startup_permit`` 以 ``not_awaiting_startup`` 拒绝，"装回"于是变成一次
  ``host.fault``——菜单没了，理由还是假的（``startup_load_failed``）。

装配复用 ``tests/test_mod_center_end_to_end.py`` 的真链路夹具（示例包真构建、宿主
运行时真装配、``ModCenterController`` 真队列），不引入第二份替身。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import tests.test_mod_center_end_to_end as e2e
from pet.feature_state_io import open_kernel_lock
from pet.feature_version_lease import FeatureVersionSelection

app = QApplication.instance() or QApplication([])

OWNER = e2e.OWNER


def _key() -> str:
    return e2e._key(OWNER)


def test_the_retry_ladder_finishes_the_delete_after_releasing_the_restored_binding(tmp_path):
    """N1：第一段交还后装回（M2），重试时**必须再交还一次**，否则阶梯被自己挡死。

    第一阶段用"另一个进程正持着管理操作锁"制造一次可重试的失败
    （``_single_operation_owner`` 的非重入闸 → ``management_lock_busy``，什么都不落盘），
    断言三件事同时成立：

    1. 失败当场旧版本被装回宿主（M2 的那一半没被这次修复拿走）；
    2. 那把锁放开（= 那个进程退出）之后，重试阶梯把删除做完；
    3. 用户看到的是成功，不是"等待相关程序自然退出"（挡路的是本进程自己的 pin）。
    """
    runtime, controller, results = e2e._install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        e2e._settle(controller)
        manager = runtime.managers[OWNER]
        assert runtime.host.state(OWNER) == "enabled"

        lock = open_kernel_lock(manager.service.operation_lock_path)
        try:
            assert controller.perform("delete", [_key()]) is True
            assert e2e._pump(
                lambda: getattr(manager.last_operation, "reason", None) == "management_lock_busy",
                timeout=30.0,
            ), manager.last_operation
            # 1) M2：第一段交还出去的绑定被装回，菜单与会话都在
            assert runtime.host.state(OWNER) == "enabled"
            assert runtime.menu_owners() == (OWNER,)
            assert manager.last_result.status == "completed"
        finally:
            lock.close()  # = 那个进程退出了

        e2e._settle(controller)
        # 2) N1：重试阶梯在**重新交还**之后把删除做完
        assert manager.service.inspect().active is None
        assert runtime.host.state(OWNER) == "absent"
        # 3) 用户看到的是成功
        assert results[-1][1].success is True, results[-1][1]
        assert results[-1][1].message == "已删除安装副本，个人数据保留"
    finally:
        runtime.close()


def test_an_accepted_transaction_is_never_loaded_back_into_the_host(tmp_path):
    """N2：事务已被接受时不许装回——那条路只能把宿主打成 fault。

    另一个进程还占用着这个版本（这里用本进程的一份**额外**租约代表它：占用判据
    只看租约，不看是谁）时，事务会**先接受**（``state_pending``）再卡在版本占用上。
    此时落盘的 active 已经指向候选版本，``load_current`` 会走 ``load_pending`` 的
    启动确认路，而本进程不是启动方——装回于是变成 ``host.fault("startup_load_failed")``。
    """
    runtime, controller, results = e2e._install(tmp_path)
    try:
        assert controller.perform("enable", [_key()]) is True
        e2e._settle(controller)
        manager = runtime.managers[OWNER]
        service = manager.service
        selection = FeatureVersionSelection.from_resolution(service.store.resolve_verified(service.verifier))
        # 这一份租约全程不放：事务会先接受、再卡在版本占用上（这条用例要的就是这个局面）
        pin = service.leases.acquire_host(selection)
        try:
            assert controller.perform("delete", [_key()]) is True
            e2e._settle(controller)
            # 这条用例必须真的落在"已被接受"的那条路上，否则它退化成上面那条用例
            assert service.inspect().pending_transaction is not None, service.inspect()
            assert manager.last_operation.reason == "version_in_use", manager.last_operation
            # 事务的结论照原样回报，而不是一次伪装的装载失败
            assert manager.last_result.status == "awaiting_release", manager.last_result
            assert manager.last_result.reason == "version_in_use"
            assert "startup_load_failed" not in runtime.host.diagnostics().values()
            # 宿主停在"第一段已经交还"的样子（absent）：这一半的菜单要等启动确认那条路
            # 回来，本进程**不能**在这里把它装回（装回就是上面那条 fault）。
            assert runtime.host.state(OWNER) == "absent"
            assert runtime.menu_owners() == ()
            assert results[-1][1].success is False
            assert "startup_load_failed" not in results[-1][1].message
        finally:
            pin.close()
    finally:
        runtime.close()
