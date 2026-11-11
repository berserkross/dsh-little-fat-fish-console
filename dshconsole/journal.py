"""控制台自己的落盘日志：界面上那 2000 行滚动丢弃、窗口一关就没了，事后无从查起。

只做三件事：带时间戳追加一行、长到 1 MB 换一份、任何失败都不许抛（日志写不进去
不能反过来把界面搞崩）。位置与 config.json 同目录，测试用 DSH_CONSOLE_CONFIG 整体改道。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import config, textutil

LOG_NAME = "console.log"
ROTATE_BYTES = 1024 * 1024        # 一条日志换一份：够翻上一次出事的全过程，又不会无限长
TAIL_LINES = 8                    # 失败时贴进界面的行数

_LOCK = threading.Lock()


def path() -> Path:
    """%APPDATA%\\dsh-console\\console.log（跟着 config.json 走）。"""
    return config.config_path().parent / LOG_NAME


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _format(text: object) -> str:
    body = str(text).replace("\r\n", "\n").rstrip("\n")
    return f"[{_stamp()}] {textutil.redact(body)}\n"


def _rotate(target: Path) -> None:
    """超限就把现有一份改名成 .1（覆盖旧的 .1）：只留一份历史，够用且不占地方。"""
    backup = target.with_name(target.name + ".1")
    try:
        os.replace(target, backup)
    except OSError:
        pass


def write(text: object, target: Path | None = None) -> None:
    """追加一行。写不进去就静默放弃 —— 这是旁证，不是主路径。"""
    dest = target or path()
    line = _format(text)
    with _LOCK:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size + len(line.encode("utf-8")) > ROTATE_BYTES:
                _rotate(dest)
            with open(dest, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(line)
        except OSError:
            pass


def tail_lines(source: Path | str | None, limit: int = TAIL_LINES) -> list[str]:
    """读文件末尾若干「非空行」：启动失败时贴进界面，比一句「请查看」有用。"""
    if not source:
        return []
    try:
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = [row.rstrip() for row in text.splitlines() if row.strip()]
    return rows[-max(1, int(limit)):]
