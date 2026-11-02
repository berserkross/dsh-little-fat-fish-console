"""异常显式化：未捕获异常一律在日志里留下可读、脱敏、可定位的 traceback。

v1 只有 except 分支里记一句「出错：{exc}」，栈帧信息全丢：用户报「按钮点了没反应」时无从下手。
这里把「格式化 + 脱敏 + 截断」收成一处，sys.excepthook / threading.excepthook /
Tk.report_callback_exception 三个入口共用同一个出口。
"""
from __future__ import annotations

import sys
import threading
import traceback
from typing import Callable

from . import textutil

FRAME_LIMIT = 12          # traceback 保留的栈帧数：够看出调用链，又不会灌满日志框
MAX_CHARS = 2000          # 单条异常写进日志的最大字符数（保留尾部：类型与消息在最后）
TRUNCATED = "…（前面已截断）\n"

Sink = Callable[[str], None]


def summarize(exc_type, exc, tb, *, limit: int = FRAME_LIMIT,
              max_chars: int = MAX_CHARS) -> str:
    """把一次异常整理成一段脱敏文本；格式化本身失败也不能再抛。"""
    try:
        raw = "".join(traceback.format_exception(exc_type, exc, tb, limit=limit))
    except Exception:  # noqa: BLE001 - 连格式化都失败时至少留下异常名与消息
        raw = f"{getattr(exc_type, '__name__', exc_type)!s}: {exc!r}"
    text = textutil.redact(raw.strip())
    if len(text) > max_chars:
        return TRUNCATED + text[-max_chars:]
    return text


def _emit(sink: Sink, header: str, text: str) -> None:
    """出口自身出错时退回 stderr，绝不让「报错的代码」把进程再炸一次。"""
    message = f"{header}\n{text}" if header else text
    try:
        sink(message)
    except Exception:  # noqa: BLE001
        try:
            print(message, file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass


def install(sink: Sink) -> None:
    """装上三处入口里的两处；Tk 的 report_callback_exception 由 GUI 自己挂。"""
    def excepthook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return                      # Ctrl-C 是用户的意图，不是错误
        _emit(sink, "未捕获异常：", summarize(exc_type, exc, tb))

    def threadhook(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = getattr(args.thread, "name", "?")
        _emit(sink, f"后台线程异常（{name}）：",
              summarize(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = threadhook
