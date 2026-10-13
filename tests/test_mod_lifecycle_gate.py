# -*- coding: utf-8 -*-
"""D2 片 2：``FeatureHostLifecycle`` 草稿门（事务层 ``runtime=`` 的唯一消费方）。

两条判据（= 两个入口读同一份快照）：

* ``draft_blocked``（有未保存草稿）——设置面板在 GUI 线程把草稿名推进快照，
  事务层在后台线程只读它；
* ``awaiting_release``（别的活进程占着这些版本）——``install``/``upgrade``/
  ``rollback``/``uninstall`` 会因为「另一个程序还开着」而等；``disable`` 只翻一个
  布尔量、不碰版本目录，**不允许**被别的进程的租约卡住（否则两个宿主同时开着时
  停用一个扩展会永远做不到）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from pet.feature_lifecycle_contract import LifecyclePrepareRequest
from pet.plugins.lifecycle import FeatureHostLifecycle

ROOT = Path(__file__).resolve().parents[1]
OWNER = "demo.hello-local"
OP = "tx-" + "a" * 32


def _request(operation="uninstall", versions=("1.0.0",), live_owners=(), revision=3):
    return LifecyclePrepareRequest(OP, revision, operation, tuple(versions), tuple(live_owners), feature_id=OWNER)


def _other_owner():
    return (os.getpid() + 1, "b" * 32)


# ------------------------------------------------------------------- 草稿门

def test_no_drafts_means_ready():
    result = FeatureHostLifecycle().prepare(_request())
    assert result.status == "ready"
    assert result.reason is None
    assert result.blocked_versions == ()


def test_a_draft_blocks_the_operation_and_names_it():
    gate = FeatureHostLifecycle()
    gate.note_drafts(OWNER, ("消息编辑器",))
    result = gate.prepare(_request())
    assert result.status == "draft_blocked"
    assert result.reason == "unsaved_settings"
    assert tuple(result.details["drafts"]) == ("消息编辑器",)
    assert result.details["pid"] == os.getpid()


def test_a_draft_of_another_owner_never_blocks_this_one():
    gate = FeatureHostLifecycle()
    gate.note_drafts("demo.other", ("别的面板",))
    assert gate.prepare(_request()).status == "ready"


def test_clearing_the_draft_snapshot_reopens_the_gate():
    gate = FeatureHostLifecycle()
    gate.note_drafts(OWNER, ("消息编辑器",))
    assert gate.prepare(_request()).status == "draft_blocked"
    gate.note_drafts(OWNER, ())
    assert gate.prepare(_request()).status == "ready"
    assert gate.drafts(OWNER) == ()


def test_the_snapshot_is_a_copy_and_survives_mutation_of_the_source():
    gate = FeatureHostLifecycle()
    names = ["a", "b"]
    gate.note_drafts(OWNER, names)
    names.append("c")  # 调用方事后改自己的列表：快照必须不受影响
    assert gate.drafts(OWNER) == ("a", "b")
    # 草稿空名与重复名一律归一（空名不算草稿）
    gate.note_drafts(OWNER, ("a", "", "a"))
    assert gate.drafts(OWNER) == ("a",)


def test_the_prepare_request_is_never_mutated():
    gate = FeatureHostLifecycle()
    gate.note_drafts(OWNER, ("x",))
    request = _request(live_owners=(_other_owner(),))
    before = request.document()
    gate.prepare(request)
    assert request.document() == before


# --------------------------------------------------------------- 跨进程占用

def test_another_live_owner_blocks_a_version_removing_operation():
    result = FeatureHostLifecycle().prepare(_request("uninstall", live_owners=(_other_owner(),)))
    assert result.status == "awaiting_release"
    assert result.reason == "version_in_use"
    assert result.blocked_versions == ("1.0.0",)
    assert tuple(result.details["owners"]) == (_other_owner(),)


def test_disable_is_never_blocked_by_another_process():
    """停用只翻一个布尔量：别的进程开着设置页不能让它做不到。"""
    result = FeatureHostLifecycle().prepare(_request("disable", live_owners=(_other_owner(),)))
    assert result.status == "ready"


def test_our_own_pid_is_not_a_foreign_owner():
    mine = (os.getpid(), "c" * 32)
    result = FeatureHostLifecycle().prepare(_request("uninstall", live_owners=(mine,)))
    assert result.status == "ready"


def test_a_first_install_with_no_installed_version_is_ready():
    result = FeatureHostLifecycle().prepare(_request("install", versions=(), live_owners=(_other_owner(),)))
    assert result.status == "ready"
    assert result.blocked_versions == ()


def test_drafts_win_over_foreign_owners():
    """两个判据同时命中时报草稿：那是用户当场能解决的那一个。"""
    gate = FeatureHostLifecycle()
    gate.note_drafts(OWNER, ("消息编辑器",))
    result = gate.prepare(_request("uninstall", live_owners=(_other_owner(),)))
    assert result.status == "draft_blocked"


# ------------------------------------------------------------- 并发纪律

def test_the_background_thread_only_reads_the_snapshot():
    """派发前在 GUI 线程取快照；后台线程只读，绝不碰面板对象。"""
    gate = FeatureHostLifecycle()
    seen = []
    started = threading.Event()

    def worker():
        started.set()
        seen.append(gate.prepare(_request("uninstall")))

    gate.note_drafts(OWNER, ("消息编辑器",))  # 「GUI 线程」先取快照
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(10)
    assert started.is_set() and not thread.is_alive()
    assert [row.status for row in seen] == ["draft_blocked"]


def test_the_gate_imports_without_qt():
    """后台线程路径：本模块连同 ``prepare`` 只吃 stdlib，不许把 Qt 拉进导入图。"""
    probe = (
        "import sys;"
        "from pet.plugins.lifecycle import FeatureHostLifecycle;"
        "from pet.feature_lifecycle_contract import LifecyclePrepareRequest;"
        "FeatureHostLifecycle().prepare(LifecyclePrepareRequest('tx-' + 'a' * 32, 0, 'disable', ()));"
        "assert not [m for m in sys.modules if m.split('.')[0] == 'PySide6'], sorted(sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
