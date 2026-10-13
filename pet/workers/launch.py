"""Explicit child-only launch lease; no Qt and no desktop-pet imports.

Ported from the DLC branch `pet/workers/launch.py` plus the package-independent
half of its `pet/plugins/worker_launch.py`.  That branch bound the launch to a
verified feature-package reservation; this topology has no package trust chain to
bind to, so the lease *shape* is kept — acquire, hold across the native child's
whole life, confirm the takeover, abort on a rejected launch, release only after
the child has exited — and it is driven by a host-supplied :class:`LaunchLease`.

Environment cleanup is necessary but is NOT proof of independent DLL loading.
Frozen artifact validation must additionally inspect actual loaded module paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence

from ..feature_state_io import StateError, safe_path

#: Environment field carrying the one-time takeover token to the child.
HANDOFF_TOKEN_ENV = "DSH_PET_WORKER_HANDOFF_TOKEN"


class WorkerLaunchRejected(ValueError):
    """Fixed reason code only: never carry OS paths, tokens or verifier input."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LaunchLease(Protocol):
    """A host-owned resource held for exactly one worker process generation."""

    def release(self) -> None:
        """Give the resource back; called once, after the native child exited."""

    def confirm_child(self, child_pid: int | None) -> bool:
        """Adopt *child_pid* as the owner; return ``False`` to reject the takeover."""

    def abort(self) -> None:
        """Drop the resource after a rejected launch, without a confirmed child."""


@dataclass
class WorkerLaunch:
    """One acquired launch lease. Release only after the native child has exited."""

    program: str
    arguments: tuple[str, ...]
    working_directory: str
    environment: Mapping[str, str]
    on_release: Callable[[], None]
    on_handoff_confirmed: Callable[[int | None], bool] | None = None
    on_handoff_abort: Callable[[], None] | None = None
    handoff_token: str | None = None
    _released: bool = field(default=False, init=False)
    _handoff_confirmed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not Path(self.program).is_absolute() or not Path(self.working_directory).is_absolute():
            raise ValueError("external Worker paths must be absolute")
        self.arguments = tuple(self.arguments)
        self.environment = MappingProxyType(dict(self.environment))
        if self.handoff_token is not None and not isinstance(self.handoff_token, str):
            raise ValueError("worker handoff token must be text")

    @property
    def requires_handoff(self) -> bool:
        return self.on_handoff_confirmed is not None

    @property
    def handoff_confirmed(self) -> bool:
        return self._handoff_confirmed

    def confirm_handoff(self, child_pid: int | None = None) -> bool:
        if self.on_handoff_confirmed is None:
            return True
        if self._handoff_confirmed:
            return True
        confirmed = bool(self.on_handoff_confirmed(child_pid))
        if confirmed:
            self._handoff_confirmed = True
        return confirmed

    def close(self) -> None:
        if not self._released:
            self._released = True
            if not self._handoff_confirmed and self.on_handoff_abort is not None:
                self.on_handoff_abort()
            self.on_release()


def isolated_worker_environment(
    source: Mapping[str, str],
    *,
    core_roots: Sequence[Path] = (),
) -> dict[str, str]:
    """Copy network/system settings but discard inherited Python/Qt/Core paths.

    Never mutate os.environ, the parent's DLL directories, or proxy/TLS policy.
    PATH relative and empty entries are discarded (they depend on Core's cwd).
    Caller supplies Core application/runtime roots, NOT the shared data root.
    """
    roots = tuple(Path(root).resolve() for root in core_roots)
    drop = {"QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"}
    result: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper.startswith(("PYTHON", "_PYI", "_MEIPASS")) or upper in drop:
            continue
        if upper == "PATH":
            kept = []
            for entry in value.split(os.pathsep):
                candidate = Path(entry.strip('"'))
                if not entry or not candidate.is_absolute():
                    continue
                resolved = candidate.resolve()
                if not any(resolved == root or root in resolved.parents for root in roots):
                    kept.append(entry)
            result[key] = os.pathsep.join(kept)
        else:
            result[key] = value
    return result


def _no_lease() -> None:
    """Release callback for a launch that holds no host resource."""


def _validated_runtime(runtime_directory: Path | str, core_roots: Sequence[Path], owned_root: Path | None) -> Path:
    """Resolve a child runtime directory that must stay outside every Core root.

    Lexical ancestors are checked before ``resolve``: a link must not become an
    apparently safe out-of-tree runtime through canonicalization.  ``owned_root``
    is the one host-owned runtime area a Core root may contain.
    """
    runtime = Path(runtime_directory)
    if not runtime.is_absolute():
        raise WorkerLaunchRejected("worker_runtime_boundary")
    try:
        safe_path(runtime)
        runtime = runtime.resolve(strict=True)
        roots = tuple(Path(root).resolve() for root in core_roots)
        owned = None if owned_root is None else Path(owned_root).resolve()
        if not runtime.is_dir():
            raise WorkerLaunchRejected("worker_runtime_unavailable")
        for root in roots:
            if runtime.is_relative_to(root) and not (owned is not None and runtime.is_relative_to(owned)):
                raise WorkerLaunchRejected("worker_runtime_boundary")
    except WorkerLaunchRejected:
        raise
    except StateError:
        raise WorkerLaunchRejected("worker_runtime_boundary") from None
    except OSError:
        raise WorkerLaunchRejected("worker_runtime_unavailable") from None
    return runtime


def lease_worker_launch(
    program: str,
    arguments: Sequence[str] = (),
    *,
    runtime_directory: Path | str,
    environment: Mapping[str, str] | None = None,
    core_roots: Sequence[Path] = (),
    owned_root: Path | None = None,
    lease: LaunchLease | None = None,
    handoff_token: str | None = None,
) -> WorkerLaunch:
    """Hold *lease* until the supervisor confirms the native child has exited.

    Runtime/log files stay outside executable trees.  The caller creates the
    per-instance runtime directory; this function never creates or removes
    directories and cannot change the child program or its arguments.  Once the
    lease is handed over, any rejection drops it: a launch that never started
    must never leave the resource held.
    """
    try:
        runtime = _validated_runtime(runtime_directory, core_roots, owned_root)
        child_environment = isolated_worker_environment(os.environ if environment is None else environment, core_roots=core_roots)
        if lease is None:
            return WorkerLaunch(str(program), tuple(arguments), str(runtime), child_environment, _no_lease)
        if handoff_token is None:
            return WorkerLaunch(str(program), tuple(arguments), str(runtime), child_environment, lease.release)
        child_environment[HANDOFF_TOKEN_ENV] = str(handoff_token)
        return WorkerLaunch(
            str(program),
            tuple(arguments),
            str(runtime),
            child_environment,
            lease.release,
            on_handoff_confirmed=lease.confirm_child,
            on_handoff_abort=lease.abort,
            handoff_token=str(handoff_token),
        )
    except BaseException:
        if lease is not None:
            lease.abort()
        raise


__all__ = [
    "HANDOFF_TOKEN_ENV",
    "LaunchLease",
    "WorkerLaunch",
    "WorkerLaunchRejected",
    "isolated_worker_environment",
    "lease_worker_launch",
]
