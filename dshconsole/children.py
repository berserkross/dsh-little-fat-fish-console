"""DSH 子进程账本：控制台退出后，它拉起的 node 还活着并占着 3080。

没有这份账本，「启动」只能靠端口开着猜——端口开着就以为「已经在运行」，
于是对着一个没有主人的遗留实例点「重启」看起来毫无反应；而它是不是上一次
控制台留下的、那次有没有正常退出，事后一概查不到。

三条约定：
- 写入走 tmp + os.replace：被硬杀也不会留下半份 JSON；
- 任何读写失败都吞掉：账本是旁证，不能反过来把控制台搞崩；
- 只记控制台自己拉起的进程。别的安装里的 DSH 不进账，停止时也永远不碰。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from . import config

VERSION = 1
LEDGER_NAME = "children.json"

STATUS_RUNNING = "running"        # 控制台正持有这些进程
STATUS_STOPPED = "stopped"        # 控制台主动停掉了
STATUS_LEFT = "left-running"      # 控制台退出了，进程可能还活着


def path() -> Path:
    """账本落在配置目录，和 console.log 同一个地方，诊断包一起带走。"""
    return config.config_path().parent / LEDGER_NAME


def _now() -> float:
    return time.time()


def _write(target: Path, payload: dict) -> bool:
    tmp = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".children-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, target)
        return True
    except Exception:      # noqa: BLE001 - 记账失败不该影响任何操作
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def record(console_pid: int, entries, status: str = STATUS_RUNNING,
           target: Path | None = None, bin_js=None) -> bool:
    """写一份「这些 pid 是我拉起的」。entries 可以是 pid 列表或 {"pid": …} 字典列表。"""
    me = int(console_pid)
    items = []
    for entry in entries or ():
        raw = entry.get("pid") if isinstance(entry, dict) else entry
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == me:
            continue
        started = entry.get("startedAt") if isinstance(entry, dict) else None
        try:
            started_at = float(started) if started else _now()
        except (TypeError, ValueError):
            started_at = _now()
        items.append({"pid": pid, "startedAt": started_at})
    payload = {
        "version": VERSION,
        "consolePid": me,
        "status": status,
        "updatedAt": _now(),
        "binJs": str(bin_js) if bin_js else None,
        "dsh": items,
    }
    return _write(target or path(), payload)


def load(target: Path | None = None) -> dict | None:
    """读账本；缺文件、坏 JSON、版本不符一律当作「没有账本」。"""
    try:
        data = json.loads((target or path()).read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    return data


def mark(status: str, target: Path | None = None, console_pid: int | None = None) -> bool:
    """只改状态。给了 console_pid 就只认自己那份账（别的实例的账不许我改）。

    STOPPED 是结论，不能被后来的一次退出盖成 LEFT：真的停了就是真的停了。
    """
    target = target or path()
    ledger = load(target)
    if ledger is None:
        return False
    if console_pid is not None and int(ledger.get("consolePid") or 0) != int(console_pid):
        return False
    if status == STATUS_LEFT and ledger.get("status") == STATUS_STOPPED:
        return False
    ledger["status"] = status
    ledger["updatedAt"] = _now()
    return _write(target, ledger)


def entries(ledger: dict | None) -> list[dict]:
    """账本里的条目，形状统一成 {"pid": int, "startedAt": float}。"""
    if not isinstance(ledger, dict):
        return []
    out = []
    for entry in ledger.get("dsh") or ():
        if not isinstance(entry, dict):
            continue
        try:
            pid = int(entry.get("pid"))
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        try:
            started_at = float(entry.get("startedAt") or 0.0)
        except (TypeError, ValueError):
            started_at = 0.0
        out.append({"pid": pid, "startedAt": started_at})
    return out


def leftovers(ledger: dict | None, alive_pids, current_pid: int) -> list[dict]:
    """上一次控制台留下、现在仍活着的 DSH 进程。

    alive_pids 是「当前存在且命令行走同一个 bin.js」的 pid 集合（由
    probe.dsh_processes 判定），所以 PID 被系统回收到别的程序上不会误认。
    """
    if not isinstance(ledger, dict):
        return []
    if ledger.get("status") == STATUS_STOPPED:
        return []
    try:
        console = int(ledger.get("consolePid") or 0)
    except (TypeError, ValueError):
        console = 0
    if console == int(current_pid):
        return []                      # 就是本进程自己的账，不是遗留
    try:
        alive = {int(pid) for pid in (alive_pids or ())}
    except (TypeError, ValueError):
        return []
    return [item for item in entries(ledger) if item["pid"] in alive]


def describe(item: dict) -> str:
    """给日志用的一行：PID 1234（11-13 06:10 起）。"""
    started_at = item.get("startedAt") or 0.0
    when = time.strftime("%m-%d %H:%M", time.localtime(started_at)) if started_at else "时间未知"
    return f"PID {item.get('pid')}（{when} 起）"
