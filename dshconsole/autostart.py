"""开机自启动：往 HKCU 的 Run 键里放一条命令行，一颗芯片就能开关。

用 HKCU 而不是 HKLM：不需要 UAC，而且只影响当前用户——与「这台机器上的一个控制台」
的定位一致。登记值是一条带引号的完整命令行，路径里有空格也不会被拆开。

非 Windows 上 available() 为 False，界面据此把芯片显示成不可用，绝不假装成功。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VALUE_NAME = "DSHConsole"
RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"


def available() -> bool:
    """这台机器能不能登记自启动（只有 Windows 有 Run 键）。"""
    return os.name == "nt"


def target_command() -> str:
    """写进 Run 键的命令行：打包版就是 exe 自己，源码版带上脚本路径。"""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}"'
    script = Path(__file__).resolve().parent.parent / "dsh_gui.py"
    return f'"{exe}" "{script}"'


def _registry():
    import winreg      # 延迟导入：别的平台上根本不存在这个模块
    return winreg


def enabled(registry=None) -> bool:
    """Run 键里有没有本控制台的登记。读不到（键不存在/权限）就当没开。"""
    reg = registry or _registry()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = reg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return bool(str(value).strip())


def set_enabled(value: bool, registry=None) -> None:
    """登记或撤销自启动；撤销时值本来就不存在也算成功。"""
    reg = registry or _registry()
    command = target_command()
    with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
        if value:
            reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command)
            return
        try:
            reg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
