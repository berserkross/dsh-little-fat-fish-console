"""跟随真实日志文件（C2）。

原来日志框里的行是界面自己编的事件，看不到 DSH 自己说了什么。这里按字节偏移
跟随 dsh-web.stdout.log / dsh-web.stderr.log：只产出新追加的内容，文件被截断或
轮转时自动重定位；单行过长会截断（一串二进制垃圾不该撑爆日志框）。

每一行进入界面前都过 textutil.redact_text()（redact 的超集）：日志里带着访问
token，也可能带着别的密钥。这条是硬要求，不接受「先显示再想」。
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import textutil

MAX_LINE = 800           # 单行上限（字符）
TAIL_BYTES = 64 * 1024   # 首次跟随从尾部这么多字节开始：不重放整个历史
DEFAULT_INTERVAL = 0.4   # 轮询间隔（秒）；下限 0.3 —— 不许 busy loop
TRUNCATED_NOTE = "（日志被截断，从头开始跟随）"


class Follower:
    """按字节偏移跟随一个文件；只返回新追加的、已脱敏的行。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.offset: int | None = None
        self._partial = b""

    def _size(self) -> int | None:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def read(self) -> list[str]:
        size = self._size()
        if size is None:
            return []                      # 文件还没出现（DSH 还没起过）

        lines: list[str] = []
        first = self.offset is None
        if first:
            self.offset = max(0, size - TAIL_BYTES)
        elif size < self.offset:           # 被截断 / 轮转后变小
            self.offset = 0
            self._partial = b""
            lines.append(TRUNCATED_NOTE)
        if size == self.offset:
            return lines
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(size - self.offset)
        except OSError:
            return lines
        if not chunk:
            return lines
        self.offset += len(chunk)

        parts = (self._partial + chunk).split(b"\n")
        self._partial = parts.pop()         # 最后一段可能是半行，留着
        if first and self.offset > len(chunk) and parts:
            parts.pop(0)                   # 从字节偏移开头那行多半只有半截
        for raw in parts:
            lines.append(_clean(raw))
        return lines


def _clean(raw: bytes) -> str:
    line = raw.decode("utf-8", "replace").rstrip("\r")
    if len(line) > MAX_LINE:
        line = line[:MAX_LINE] + "…（本行过长，已截断）"
    return textutil.redact_text(line)


class LogTailer:
    """后台线程版：定时读所有被跟随的文件，把 (路径, 新行) 交给 sink。

    sink 在后台线程里被调用 —— 界面那边必须自己 after(0, ...) 投递。
    """

    def __init__(self, paths, sink, interval: float = DEFAULT_INTERVAL) -> None:
        self._followers = [Follower(path) for path in paths if path]
        self._sink = sink
        self.interval = max(0.3, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll(self) -> list[tuple[Path, list[str]]]:
        found = []
        for follower in self._followers:
            lines = follower.read()
            if lines:
                found.append((follower.path, lines))
        return found

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="dsh-log-tail", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            for path, lines in self.poll():
                try:
                    self._sink(path, lines)
                except Exception:          # 窗口正在销毁：安静收工
                    return

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def read_tail(path: Path | str, count: int = 500) -> str:
    """读文件最后 count 行（诊断包用），整段过 redact_text。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"（读不到 {path}：{exc}）"
    return textutil.redact_text("\n".join(text.splitlines()[-count:]))
