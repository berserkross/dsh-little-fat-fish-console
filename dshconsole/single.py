"""单实例守卫：双击第二次不再弹第二个主窗口。

Windows 命名互斥体（Local 命名空间下的 DshConsole.SingleInstance）判重：已经存在就把已有窗口
拉到前台，找不到窗口就说明原因并正常退出（退出码 0，不是错误）。非 Windows 或 ctypes 不可用时
只是降级成「不拦」，绝不因此拦住启动。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

MUTEX_NAME = "Local\\DshConsole.SingleInstance"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

# 句柄必须活到进程退出：一旦被回收，互斥体就释放了，第二个实例会以为没人跑。
_HANDLE = None


@dataclass(frozen=True)
class Guard:
    """acquired: True=本进程是唯一实例；False=已有实例在跑；None=判定不了（已降级）。"""

    acquired: bool | None
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.acquired is False


def _win32():
    """拿 ctypes 与 wintypes；拿不到就抛，由调用方降级。"""
    import ctypes
    from ctypes import wintypes

    return ctypes, wintypes


def acquire(name: str = MUTEX_NAME) -> Guard:
    """尝试创建命名互斥体并保活句柄。

    注意 restype/argtypes 必须显式声明：ctypes 默认把返回值当 32 位 int，64 位句柄会被截断。
    """
    global _HANDLE
    if os.name != "nt":
        return Guard(None, "非 Windows 系统，跳过单实例检查")
    try:
        ctypes, wintypes = _win32()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateMutexW
        create.restype = wintypes.HANDLE
        create.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        handle = create(None, False, name)
        last_error = ctypes.get_last_error()
    except Exception as exc:  # noqa: BLE001 - 拿不到 ctypes 也要能启动
        return Guard(None, f"单实例检查不可用：{exc}")
    if not handle:
        return Guard(None, f"CreateMutexW 失败（错误码 {last_error}）")
    _HANDLE = handle
    if last_error == ERROR_ALREADY_EXISTS:
        return Guard(False, "已经有一个 DSH 控制台在运行")
    return Guard(True)


def focus_window(title: str) -> bool:
    """把标题完全匹配的已有窗口还原并拉到前台；找不到返回 False。"""
    if os.name != "nt":
        return False
    try:
        ctypes, wintypes = _win32()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001 - 拉前台失败只是体验降级，不影响退出码
        return False
