from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("petcore.platform.autostart")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "dsh-pet-core"


def command_text() -> str:
    """开机自启命令行；打包后直接运行 exe，源码运行走 pythonw -m petcore。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    return f'"{executable}" -m petcore'


def _command() -> str:
    return command_text()


def _open_key(write: bool = False):
    import winreg

    access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, access)


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with _open_key() as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
        return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        logger.debug("read autostart failed", exc_info=True)
        return False


def enable() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with _open_key(write=True) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command())
        return True
    except OSError:
        logger.debug("enable autostart failed", exc_info=True)
        return False


def disable() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with _open_key(write=True) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        logger.debug("disable autostart failed", exc_info=True)
        return False


def cleanup_stale_entries() -> int:
    if os.name != "nt" or not is_enabled():
        return 0
    return 0
