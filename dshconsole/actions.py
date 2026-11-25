"""动作簿：把「控制台此刻在做什么」写进一个独立小文件。

窗口被外部硬杀时来不及写日志（journal 里一行都不会有），但已经落盘的动作名与当前步骤
还在。下次启动把它读出来，就能说出上次断在哪一步 —— 这是「点重启把窗口一起带走」唯一
留下的现场。写不进去只是少一条线索，绝不允许拦住动作本身。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import journal

FILE_NAME = "action.json"


def path() -> Path:
    """跟落盘日志同目录：日志换了地方，动作簿跟着走。"""
    return journal.path().parent / FILE_NAME


def _write(payload: dict) -> None:
    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def read() -> dict | None:
    try:
        payload = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def begin(name: str, step: str = "") -> None:
    """动作开始：先落盘，再动手。"""
    _write({"name": name, "step": step, "startedAt": time.time(), "pid": os.getpid()})


def step(text: str) -> None:
    """走到哪一步了：每换一步写一次，越近的现场越值钱。"""
    current = read()
    if current is None:
        return
    current["step"] = text
    _write(current)


def finish() -> None:
    """动作收尾：抹掉现场。没走到这里的动作就是「断在半路」。"""
    try:
        path().unlink()
    except OSError:
        pass


def unfinished() -> dict | None:
    """上次没走到 finish 的动作。"""
    current = read()
    if current is None or not current.get("name"):
        return None
    return current


def describe(current: dict) -> str:
    """给日志看的一句话，带上断点时间与步骤。"""
    stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(current.get("startedAt") or 0)))
    where = str(current.get("step") or "开始").strip() or "开始"
    return f"上次「{current.get('name')}」在 {stamp} 断在「{where}」，没有正常收尾。"
