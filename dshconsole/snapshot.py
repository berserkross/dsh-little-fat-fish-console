"""刷新用的短 TTL 缓存。

一次探测要 spawn 一次 PowerShell（本机约 1.2 秒），窗口刚打开、来回切、连点刷新
时都不该重复扫。TTL 内的结果直接复用，手动刷新用 force=True 穿透 —— 「手动刷新
必须真的去查一次」是用户点下去时的预期，缓存不能把它吞掉。

只用 monotonic 时钟：改系统时间不会让缓存永久有效。
"""

from __future__ import annotations

import time
from typing import Any, Callable

DEFAULT_TTL = 3.0


class Snapshot:
    """拿着一个取值函数，按 TTL 决定「复用上次结果」还是「真的再取一次」。"""

    def __init__(self, load: Callable[[], Any], ttl: float = DEFAULT_TTL,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._load = load
        self.ttl = float(ttl)
        self._clock = clock
        self._value: Any = None
        self._at: float | None = None

    def get(self, *, force: bool = False) -> tuple[Any, bool]:
        """(值, 是否来自缓存)。取值失败原样抛出 —— 失败不进缓存。"""
        now = self._clock()
        if not force and self._at is not None and now - self._at < self.ttl:
            return self._value, True
        value = self._load()
        self._value = value
        self._at = self._clock()
        return value, False

    def invalidate(self) -> None:
        self._at = None

    def age(self) -> float | None:
        """上次取值的年龄（秒）；还没有值时为 None。界面拿它写「x 秒前」。"""
        if self._at is None:
            return None
        return max(0.0, self._clock() - self._at)
