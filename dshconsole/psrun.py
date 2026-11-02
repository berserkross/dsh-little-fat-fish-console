"""结构化调用 PowerShell：每次调用返回 PsResult，失败原因放进 error 字段。

v1 的 run_ps_cmd 把异常拼成字符串 `ERR ...` 返回，调用方再用正则从这串文本里抠
PID / IP —— PowerShell 一出错，错误信息里的数字就被当成 PID，界面于是把「查不到」
显示成「未运行」。这里把成功、退出码、stdout、stderr、失败原因拆成五个字段，
调用方只能看字段，「从输出里抠值」这条路彻底堵死。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SYSTEM_PS = "powershell.exe"
CREATE_NO_WINDOW = 0x08000000
ENCODING = "utf-8"
# PowerShell 5.1 默认按控制台代码页写 stdout（简中 GBK），中文路径会被
# errors="replace" 打成问号；每条 -Command 前先把它掰成 UTF-8，JSON 里的中文路径
# 才不会被破坏。
UTF8_PREAMBLE = (
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
)

Spawn = Callable[..., Any]


@dataclass(frozen=True)
class PsResult:
    """一次 PowerShell 调用的完整结果。"""

    ok: bool                 # 进程成功退出且没有被判定为错误
    code: int | None         # 退出码；进程没起来时为 None
    stdout: str
    stderr: str
    error: str | None        # 超时 / 找不到 powershell / 启动失败 的原因

    @property
    def text(self) -> str:
        """stdout + stderr 拼接：只给日志看，不要拿来抠值。"""
        return (self.stdout or "") + (self.stderr or "")

    def why(self) -> str:
        """失败原因的人话版本；成功时返回空串。"""
        if self.ok:
            return ""
        if self.error:
            return self.error
        lines = [ln.strip() for ln in (self.stderr or self.stdout or "").splitlines() if ln.strip()]
        detail = f"退出码 {self.code}" if self.code is not None else "没有退出码"
        return f"{detail}：{lines[-1][:200]}" if lines else detail


def _creationflags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def execute(argv: list[str], timeout: int, spawn: Spawn | None = None) -> PsResult:
    """跑一条命令并归一化成 PsResult；任何失败都不抛异常。"""
    runner = spawn or subprocess.run
    try:
        done = runner(
            argv, capture_output=True, text=True, encoding=ENCODING, errors="replace",
            stdin=subprocess.DEVNULL, creationflags=_creationflags(), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return PsResult(False, None, "", "", f"超时：{timeout} 秒内没有返回")
    except FileNotFoundError:
        return PsResult(False, None, "", "", f"找不到 {SYSTEM_PS}：系统里没有可用的 PowerShell")
    except OSError as exc:  # noqa: BLE001 - 启动失败一律归到这里
        return PsResult(False, None, "", "", f"启动 {SYSTEM_PS} 失败：{exc}")
    code = getattr(done, "returncode", None)
    return PsResult(code == 0, code, getattr(done, "stdout", "") or "",
                    getattr(done, "stderr", "") or "", None)


def run_ps(script: Path, *args: str, timeout: int = 60, spawn: Spawn | None = None) -> PsResult:
    """-File 跑随包发布的 ps1（无窗口、超时、编码全部在这里定死）。"""
    argv = [SYSTEM_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return execute(argv, timeout, spawn)


def decode_native(raw: bytes) -> str:
    """原生命令（netsh 等）的输出解码：控制台代码页随环境变，按 utf-8 → oem → mbcs 试。"""
    for encoding in ("utf-8", "oem", "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def run_native(argv: list[str], timeout: int = 20, spawn: Spawn | None = None) -> PsResult:
    """直接跑一个原生 EXE（netsh / tailscale），不经过 PowerShell：省掉一次约 1 秒的冷启动。

    退出码非 0 不代表「没问到东西」——netsh 的「没有这条规则」就是非 0，
    所以调用方要按 text + code 判断，不能只看 ok。
    """
    runner = spawn or subprocess.run
    try:
        done = runner(
            argv, capture_output=True, text=False,
            stdin=subprocess.DEVNULL, creationflags=_creationflags(), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return PsResult(False, None, "", "", f"超时：{timeout} 秒内没有返回")
    except FileNotFoundError:
        return PsResult(False, None, "", "", f"找不到 {argv[0]}：系统里没有这个命令")
    except OSError as exc:  # noqa: BLE001 - 启动失败一律归到这里
        return PsResult(False, None, "", "", f"启动 {argv[0]} 失败：{exc}")
    code = getattr(done, "returncode", None)
    stdout = decode_native(getattr(done, "stdout", b"") or b"")
    stderr = decode_native(getattr(done, "stderr", b"") or b"")
    return PsResult(code == 0, code, stdout, stderr, None)


def run_ps_cmd(command: str, timeout: int = 30, spawn: Spawn | None = None) -> PsResult:
    """-Command 执行一段 PowerShell；自动加 UTF-8 前置语句。"""
    argv = [SYSTEM_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            UTF8_PREAMBLE + command]
    return execute(argv, timeout, spawn)
