"""Connect a verified official package to the generic, child-only launcher.

This is not an installation resolver: the host explicitly supplies a verified
version and a writable runtime directory it owns. Every restart acquires a new
lease and revalidates the signed files; a validation failure has no fallback.

Ported from the DLC branch ``pet/plugins/worker_launch.py``；两处宿主适配：

* **program/argv 由 Core 决定（作者不拼路径）**：冻结态跑包内 ``worker/*.exe``；
  源码态跑 ``sys.executable`` + 包内 worker 脚本（DLC 侧一律把 ``worker_path``
  当可执行文件，源码态在 Windows 上直接起不来）。
* **两个子进程引导字段**（Core 下发，不写进包、不许作者自造）：
  ``DSH_PET_FEATURE_DATA_ROOT``（子进程据此定位租约目录）与 ``DSH_PET_CORE_ROOT``
  （**仅源码态**下发本仓库根，供作者脚本 ``sys.path.insert`` 自举；冻结态子进程
  自带依赖，不下发）。租约握手 token 沿用 S2 的
  :data:`pet.workers.launch.HANDOFF_TOKEN_ENV`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

from ..feature_state_io import StateError, safe_path
from ..feature_version_lease import FeatureVersionLeaseCoordinator, FeatureVersionSelection, WorkerReservation
from ..workers.launch import HANDOFF_TOKEN_ENV, WorkerLaunch, isolated_worker_environment
from ..workers.lease_bootstrap import OWNER_ENV as LEASE_OWNER_ENV
from .feature_packages import FeaturePackageLoader, VerifiedFeatureDescriptor


#: 子进程定位租约目录的数据根（Core 下发；认领 worker 租约必需）。
FEATURE_DATA_ROOT_ENV = "DSH_PET_FEATURE_DATA_ROOT"
#: **仅源码态**下发的本仓库根，供作者脚本自举 ``sys.path``（冻结态不下发）。
CORE_ROOT_ENV = "DSH_PET_CORE_ROOT"


def worker_command(worker_path: Path, worker_args: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """One executable and its argv; the Core decides both, never the package."""
    if getattr(sys, "frozen", False):
        return str(worker_path), tuple(worker_args)
    return sys.executable, (str(worker_path), *worker_args)


def child_bootstrap_environment(*, data_root: Path | str | None, frozen: bool | None = None) -> dict[str, str]:
    """Core-issued bootstrap fields for a MOD worker; never written into a package."""
    values: dict[str, str] = {}
    if data_root is not None:
        values[FEATURE_DATA_ROOT_ENV] = str(data_root)
    if not (getattr(sys, "frozen", False) if frozen is None else bool(frozen)):
        values[CORE_ROOT_ENV] = str(Path(__file__).resolve().parents[2])
    return values


def verified_worker_launch(
    loader: FeaturePackageLoader,
    descriptor: VerifiedFeatureDescriptor,
    *,
    runtime_directory: Path,
    core_roots: Sequence[Path] = (),
    environment: Mapping[str, str] | None = None,
    selection: FeatureVersionSelection | None = None,
    lease_coordinator: FeatureVersionLeaseCoordinator | None = None,
) -> WorkerLaunch:
    """Hold the selected version until the supervisor confirms native exit.

    Runtime/log files stay outside executable trees. An installed portable
    selection may use only its Core-owned data/feature-runtime area. The caller
    creates the per-instance runtime directory; this function never creates or
    removes directories and cannot change the signed program or its arguments.
    """
    if (selection is None) != (lease_coordinator is None):
        raise ValueError("installed selection and lease coordinator must be supplied together")
    if selection is not None and selection.descriptor is not descriptor:
        raise ValueError("installed selection does not match descriptor")
    runtime = Path(runtime_directory)
    if not runtime.is_absolute():
        raise StateError("worker_runtime_boundary")
    try:
        # Check lexical ancestors before resolve: a link must not become an
        # apparently safe out-of-tree runtime through canonicalization.
        safe_path(runtime)
        runtime = runtime.resolve(strict=True)
        package = descriptor.root.resolve(strict=True)
        roots = tuple(Path(root).resolve() for root in core_roots)
        data = None if lease_coordinator is None else lease_coordinator.data_root.resolve(strict=True)
        owned = None if data is None else data / "feature-runtime"
        if not runtime.is_dir():
            raise StateError("worker_runtime_unavailable")
        if runtime.is_relative_to(package):
            raise StateError("worker_runtime_boundary")
        for root in roots:
            if runtime.is_relative_to(root) and not (data == root / "data" and owned is not None and runtime.is_relative_to(owned)):
                raise StateError("worker_runtime_boundary")
    except StateError as exc:
        if exc.code in {"worker_runtime_boundary", "worker_runtime_unavailable"}:
            raise
        raise StateError("worker_runtime_boundary") from None
    except OSError:
        raise StateError("worker_runtime_unavailable") from None
    reservation: WorkerReservation | None = None
    if selection is not None and lease_coordinator is not None:
        reservation = lease_coordinator.reserve_worker(selection)
    handle = None
    try:
        handle = loader.acquire_worker(descriptor)
        program, arguments = worker_command(*handle.command())
        child_environment = isolated_worker_environment(os.environ if environment is None else environment, core_roots=core_roots)
        child_environment.update(
            child_bootstrap_environment(data_root=None if lease_coordinator is None else lease_coordinator.data_root)
        )
        if reservation is None:
            return WorkerLaunch(str(program), tuple(arguments), str(runtime), child_environment, handle.close)
        assert lease_coordinator is not None
        token = reservation.handoff_token
        child_environment[LEASE_OWNER_ENV] = descriptor.id
        child_environment[HANDOFF_TOKEN_ENV] = token

        def confirm(child_pid: int | None) -> bool:
            confirmed = reservation.claim_child(child_pid=child_pid)
            if confirmed:
                reservation.close()
            return confirmed

        def abort() -> None:
            if not reservation.closed:
                reservation.abort_after_confirmed_failure()

        def release() -> None:
            handle.close()
            if not reservation.closed:
                reservation.abort_after_confirmed_failure()

        return WorkerLaunch(
            str(program),
            tuple(arguments),
            str(runtime),
            child_environment,
            release,
            on_handoff_confirmed=confirm,
            on_handoff_abort=abort,
            handoff_token=token,
        )
    except BaseException:
        if handle is not None:
            handle.close()
        if reservation is not None and not reservation.closed:
            reservation.abort_after_confirmed_failure()
        raise
