# -*- coding: utf-8 -*-
"""Opt-in MOD runtime mounting; legacy feature adapters are not double-mounted.

Ported from the DLC branch ``pet/mod_runtime.py``；本片只搬 **GenericModMounts**
（挂载面：scope、贡献注册、撤销、``sync()``、``close()``）。DLC 同文件的
``append_mod_menu`` 是**菜单 UI**，本仓库由 ``pet/mod_menu.py`` 的
``append_extension_submenu`` 统一承载（避免两套拓扑各写一份追加逻辑），
属后续切片；本片运行时可在无 GUI 下验证。
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)


class GenericModMounts:
    scope = "mod:v1:core"

    def __init__(self, host, context_for):
        self.host, self.context_for = host, context_for
        self.runtimes = {}
        self.running = set()
        self._unsubscribe = host.subscribe(self._changed)
        self.sync()

    def _stop(self, owner):
        if owner in self.running:
            self.running.remove(owner)
            self.runtimes[owner].stop()

    def _changed(self, owner, state):
        if state != "enabled":
            self._stop(owner)
        self.sync()

    def sync(self):
        for owner in self.host.owners():
            definition = self.host.definition(owner)
            if definition is None or definition.mount_contract != "mod/v1" or not self.host.enabled(owner):
                continue
            try:
                if owner not in self.runtimes:
                    context = self.context_for(owner)
                    if context is None:
                        continue
                    runtime = self.host.runtime(context)
                    if runtime is None:
                        continue
                    commands = runtime.commands
                    if not isinstance(commands, dict) or any(not isinstance(key, str) or not callable(value) for key, value in commands.items()):
                        raise TypeError("MOD commands must be a callable mapping")
                    for method in ("start", "stop", "close"):
                        if not callable(getattr(runtime, method, None)):
                            raise TypeError("MOD lifecycle is incomplete")
                    self.runtimes[owner] = runtime
                    self.host.attach(owner, self.scope, commands, lambda owner=owner: self._stop(owner))
                if owner not in self.running:
                    # Register before start so a failed start is stopped by fault.
                    self.running.add(owner)
                    self.runtimes[owner].start()
            except Exception:
                _LOG.exception("MOD runtime could not start: %s", owner)
                self.host.fault(owner, "mod_runtime_failed")

    def close(self):
        self._unsubscribe()
        for owner, runtime in tuple(self.runtimes.items()):
            try:
                self._stop(owner)
                runtime.close()
            except Exception:
                _LOG.exception("MOD runtime could not close: %s", owner)
            finally:
                self.host.detach(owner, self.scope)
        self.runtimes.clear()
