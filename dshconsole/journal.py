"""控制台自己的落盘日志：界面上那 2000 行滚动丢弃、窗口一关就没了，事后无从查起。

只做三件事：带时间戳追加一行、长到 1 MB 换一份、任何失败都不许抛（日志写不进去
不能反过来把界面搞崩）。源码运行写 config.json 同目录；用户目录内的打包版优先写安装
目录下的 logs/console.log，避免 AppData 被安全软件拒绝后现场没有证据。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from . import config, textutil

LOG_NAME = "console.log"
ROTATE_BYTES = 1024 * 1024        # 一条日志换一份：够翻上一次出事的全过程，又不会无限长
TAIL_LINES = 8                    # 失败时贴进界面的行数

_LOCK = threading.Lock()
_LAST_ERROR: str | None = None      # 上一次写失败的原因；None＝上一次是好的


def configured_path() -> Path:
    """跟随 config.json 的常规日志位置。"""
    return config.config_path().parent / LOG_NAME


def install_path() -> Path | None:
    """打包版位于用户目录时，exe 旁边的可写日志位置。"""
    if not getattr(sys, "frozen", False):
        return None
    try:
        install = Path(sys.executable).resolve().parent
        home = Path.home().resolve()
        if install.is_relative_to(home):
            return install / "logs" / LOG_NAME
    except OSError:
        pass
    return None


def path() -> Path:
    """当前主落点：打包版优先安装目录，源码运行跟随 config.json。"""
    return install_path() or configured_path()


def last_error() -> str | None:
    """主位置上一次写失败的原因；写成功过就回到 None。"""
    return _LAST_ERROR


def fallback_path() -> Path:
    """主位置写不进去时的备用落点：%LOCALAPPDATA%\dsh-console\console.log。

    主位置失败多半是权限/被占用，换另一棵目录树通常还能写：证据抄一份过去，
    两处都失败才算是真没救（那时界面会提醒一次）。
    """
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / config.APP_NAME / LOG_NAME
    return path()


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


def _append_to(dest: Path, line: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size + len(line.encode("utf-8")) > ROTATE_BYTES:
        _rotate(dest)
    with open(dest, "a", encoding="utf-8", errors="replace") as handle:
        handle.write(line)


def write(text: object, target: Path | None = None) -> bool:
    """追加一行。

    返回 True＝主位置写成功；False＝主位置失败（原因记在 last_error()，此时会尽力
    抄到 fallback_path()）。日志失败永远不抛给调用方：它是旁证，不是主路径。

    返回值唯一的用途是让调用方有机会把失败讲出来 —— 静默放弃过，
    结果事发现场一行证据都没有。
    """
    global _LAST_ERROR
    primary = target or path()
    line = _format(text)
    with _LOCK:
        failures = []
        for dest in _destinations(primary, include_configured=target is None):
            try:
                _append_to(dest, line)
            except OSError as exc:
                failures.append(f"{dest}（{type(exc).__name__}: {exc}）")
                continue
            if dest == primary:
                _LAST_ERROR = None
                return True
            _LAST_ERROR = "；".join(failures) + f"。已改存 {dest}"
            _append_failure_note(dest, failures)
            return False
        _LAST_ERROR = "；".join(failures) + "。本条未能落盘"
        return False


def _append_failure_note(dest: Path, failures: list[str]) -> None:
    """把回退原因也写进最终落点，避免异常只存在于易失的界面日志里。"""
    try:
        _append_to(dest, _format("主日志位置写入失败；回退原因：" + "；".join(failures)))
    except OSError:
        # 原事件已经写进 dest；附注再失败也不能把主流程带崩，完整原因仍在 last_error()。
        pass


def _destinations(primary: Path, include_configured: bool = False):
    yield primary
    spare = fallback_path()
    if spare != primary:
        yield spare
    install = install_path()
    if install is not None and install not in (primary, spare):
        yield install
    configured = configured_path()
    if include_configured and configured not in (primary, spare, install):
        yield configured


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
