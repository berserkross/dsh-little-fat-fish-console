"""界面操作的串行队列（C5）。

原来是全局 _busy：一个慢操作（UAC 弹窗卡住、等端口监听）会把整个窗口锁死几十
秒。改成串行队列：操作入队 → 队首执行 → 其余显示「排队中（前面还有 N 个）」。
每个任务有状态；排队中的可以取消，正在执行的不强杀 —— 它可能正拿着跨进程的
句柄，硬中断比等它自然结束更危险。

线程模型：队列自带一个后台线程跑任务（Tk 主线程绝不能被 join 住）。回调一律经
post 投递 —— 界面那边传的就是 after(0, ...)。
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class State(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        if self is State.QUEUED:
            return "排队中"
        if self is State.RUNNING:
            return "执行中"
        if self is State.DONE:
            return "成功"
        if self is State.FAILED:
            return "失败"
        return "已取消"


@dataclass
class Task:
    id: int
    name: str
    work: Callable[[], Any]
    on_done: Callable[["Task"], None] | None = None
    state: State = State.QUEUED
    result: Any = None
    error: BaseException | None = None

    @property
    def settled(self) -> bool:
        return self.state in (State.DONE, State.FAILED, State.CANCELLED)


class TaskQueue:
    """串行 FIFO：一次只跑一个任务，其余排队。"""

    def __init__(self, post: Callable[..., None] | None = None,
                 on_change: Callable[[], None] | None = None) -> None:
        self._post = post or (lambda fn, *args: fn(*args))
        self._on_change = on_change
        self._queue: deque[Task] = deque()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._running: Task | None = None
        self._thread: threading.Thread | None = None
        self._idle = threading.Event()
        self._idle.set()

    # ---- 提交 / 取消 -------------------------------------------------
    def submit(self, name: str, work: Callable[[], Any],
               on_done: Callable[[Task], None] | None = None) -> Task:
        with self._lock:
            task = Task(id=next(self._ids), name=name, work=work, on_done=on_done)
            self._queue.append(task)
            self._idle.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="dsh-task-queue",
                                                daemon=True)
                self._thread.start()
        self._changed()
        return task

    def cancel(self, task_id: int) -> bool:
        """只取消还在排队的任务；返回是否真的取消了。"""
        with self._lock:
            for task in self._queue:
                if task.id == task_id:
                    self._queue.remove(task)
                    task.state = State.CANCELLED
                    if not self._queue and self._running is None:
                        self._idle.set()
                    break
            else:
                return False
        self._changed()
        return True

    def cancel_all_pending(self) -> int:
        with self._lock:
            pending = list(self._queue)
        return sum(1 for task in pending if self.cancel(task.id))

    # ---- 查询 --------------------------------------------------------
    def pending(self) -> list[Task]:
        with self._lock:
            return list(self._queue)

    @property
    def running(self) -> Task | None:
        return self._running

    def ahead(self, task: Task) -> int:
        """在它前面还有几个任务（含正在执行的那个）。"""
        with self._lock:
            for index, queued in enumerate(self._queue):
                if queued.id == task.id:
                    return index + (1 if self._running is not None else 0)
        return 0

    def describe(self, task: Task) -> str:
        if task.state is State.QUEUED:
            return f"{task.name}：排队中（前面还有 {self.ahead(task)} 个）"
        return f"{task.name}：{task.state.label}"

    def idle(self) -> bool:
        return self._idle.is_set()

    def wait_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = 5.0 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                return self.idle()
            if self._idle.wait(min(remaining, 5.0)):
                return True

    # ---- 内部 --------------------------------------------------------
    def _changed(self) -> None:
        if self._on_change is not None:
            try:
                self._post(self._on_change)
            except Exception:      # 界面已销毁：状态照样要落定
                pass

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._running = None
                    self._thread = None
                    self._idle.set()
                    return
                task = self._queue.popleft()
                task.state = State.RUNNING
                self._running = task
            self._changed()
            try:
                task.result = task.work()
                task.state = State.DONE
            except BaseException as exc:      # 一个任务炸掉不能让队列停摆
                task.error = exc
                task.state = State.FAILED
            with self._lock:
                self._running = None
            if task.on_done is not None:
                try:
                    self._post(task.on_done, task)
                except Exception:
                    pass
            self._changed()
