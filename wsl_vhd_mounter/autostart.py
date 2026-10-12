"""开机自启：写 HKCU Run 注册表（免管理员权限）。

仅打包后的 exe 支持（sys.frozen）；源码运行时不可用。
"""

from __future__ import annotations

import sys
import winreg

APP_NAME = "WslVhdMounter"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe() -> str:
    return sys.executable if is_frozen() else ""


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    """enabled=True 时写入当前 exe 路径；False 时删除注册表项。"""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            if not is_frozen():
                raise RuntimeError("仅打包后的 exe 支持开机自启")
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{current_exe()}"')
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass
