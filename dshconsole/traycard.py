"""托盘右键卡片：系统菜单给不了的东西（彩色状态行、分隔线、两击确认）都放这里。

不继承 widgets._PopLayer —— 那个会 grab_set 并且居中在 master 上；卡片要贴在光标旁，
而且不能让 grab 把托盘点击吞掉。只沿用它的骨架约定：无边框、Esc 关、点外面关。
本模块只管「长什么样 + 怎么关」，每一行动作都由调用方 dsh_gui 传进来。
"""
from __future__ import annotations

import ctypes
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Callable, Sequence

import customtkinter as ctk

from . import status as app_status
from . import ui_theme

# 状态灯：绿=正常，琥珀=要人看一眼，灰=没开（正常停机不算报警，所以用暗灰不用红）
TONE_COLORS = {"ok": ui_theme.GREEN, "warn": ui_theme.AMBER, "off": ui_theme.GREY_DARK}
TONE_TEXT = {"ok": ui_theme.TEXT, "warn": ui_theme.AMBER, "off": ui_theme.FAINT}

Action = tuple[str, Callable[[], None], bool]      # (文案, 动作, 是否破坏性)


@dataclass(frozen=True)
class Row:
    label: str      # 「DSH」「3080」「手机」
    text: str
    tone: str       # ok / warn / off


def _pid_text(pids: Sequence[int]) -> str:
    shown = "、".join(str(pid) for pid in list(pids)[:2])
    more = "" if len(pids) <= 2 else f" 等 {len(pids)} 个"
    return f"PID {shown}{more}"


def describe(st: app_status.Status, *, port: int) -> list[Row]:
    """三行状态：DSH 进程 / 端口应答 / 手机入口。

    None 一律读成「没查到」，不读成「没开」—— status 模块的三态就是为这个存在的。
    """
    phase = st.phase
    if phase is app_status.Phase.RUNNING:
        dsh = Row("DSH", f"在跑 · {_pid_text(st.pids)}" if st.pids else "在跑", "ok")
    elif phase is app_status.Phase.STARTING:
        dsh = Row("DSH", "启动中", "warn")
    elif phase is app_status.Phase.DEGRADED:
        extra = f" · 占用 PID {st.others[0][0]}" if st.others else ""
        dsh = Row("DSH", f"异常{extra}", "warn")
    elif phase is app_status.Phase.STOPPED:
        dsh = Row("DSH", "没在跑", "off")
    else:
        dsh = Row("DSH", "没查到", "off")

    if st.port_open is False:
        port_row = Row(str(port), "没在监听", "off")
    elif st.port_open is None:
        port_row = Row(str(port), "没查到", "off")
    elif st.serving is True:
        port_row = Row(str(port), "通 · 会答 HTTP", "ok")
    elif st.serving is False:
        port_row = Row(str(port), "通 · 不答 HTTP", "warn")
    else:
        port_row = Row(str(port), "通（没测应答）", "warn")

    if st.residue:
        phone = Row("手机", "转发残留", "warn")
    elif st.phone_open is True:
        phone = Row("手机", f"可达 · {st.ts_ip}" if st.ts_ip else "可达", "ok")
    elif st.phone_open is False:
        phone = Row("手机", "没开", "off")
    else:
        phone = Row("手机", "没查到", "off")
    return [dsh, port_row, phone]


def card_position(cursor: tuple[int, int], size: tuple[int, int],
                  work: tuple[int, int, int, int], *,
                  gap: int = 8, align: int = 18) -> tuple[int, int]:
    """卡片贴光标上方、右缘对着图标，再按监视器工作区夹住。

    work 是 (left, top, right, bottom)，right/bottom 不含；用工作区而不是屏幕，
    任务栏在左、在上、竖屏都不会把卡片塞到栏下面。
    """
    width, height = size
    left, top, right, bottom = work
    cx, cy = cursor
    x = min(max(cx - width + align, left), max(left, right - width))
    y = min(max(cy - height - gap, top), max(top, bottom - height))
    return int(x), int(y)


def work_area(cursor: tuple[int, int]) -> tuple[int, int, int, int]:
    """光标所在那块屏幕的工作区（已去掉任务栏）。

    多屏、任务栏在任意一侧、竖屏都靠它兜住；问不到就返回空矩形，
    由调用方退回 `winfo_screenwidth/height`。
    """
    try:
        user32 = ctypes.windll.user32          # type: ignore[attr-defined]

        class _Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class _Rect(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _Info(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect),
                        ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]

        monitor = user32.MonitorFromPoint(_Point(*cursor), 2)      # 2 = NEAREST
        info = _Info()
        info.cbSize = ctypes.sizeof(_Info)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            area = info.rcWork
            return int(area.left), int(area.top), int(area.right), int(area.bottom)
    except Exception:          # noqa: BLE001  非 Windows 或 user32 不可用
        pass
    return 0, 0, 0, 0


class RepeatConfirm:
    """破坏性动作的两击确认：第一击改成「再点一次确认」，窗口过后自己复原。"""

    def __init__(self, label: str, confirm_label: str, *, window: float = 2.0) -> None:
        self.label = label
        self.confirm_label = confirm_label
        self.window = float(window)
        self._armed_at: float | None = None

    def armed(self, now: float) -> bool:
        return self._armed_at is not None and now - self._armed_at <= self.window

    def text(self, now: float) -> str:
        return self.confirm_label if self.armed(now) else self.label

    def press(self, now: float) -> bool:
        """True = 这一击算确认；False = 只是把按钮上膛。"""
        if self.armed(now):
            self._armed_at = None
            return True
        self._armed_at = now
        return False

    def reset(self) -> None:
        self._armed_at = None


class TrayCard(ctk.CTkToplevel):
    """贴在托盘图标旁的卡片。弹出即快照：它不自己轮询状态，要新数据就重开一张。"""

    WIDTH = 300
    ROW_H = 22          # 手绘行高：ctk 控件的默认高度会把卡片撑成一片空白
    ACTION_H = 28

    def __init__(self, master, *, rows: Sequence[Row], actions: Sequence[Action],
                 version: str = "", on_close=None) -> None:
        super().__init__(master)
        self.withdraw()
        # CTk 只缩放自己的控件和窗口尺寸，手绘的 tk 控件不归它管，所以这里自己乘一遍；
        # 不乘的话卡片会被撑成 1.5 倍空白（本机 150% 缩放的实测结果）。
        self._scale = float(ctk.ScalingTracker.get_window_scaling(self) or 1.0)
        self.overrideredirect(True)
        self.configure(fg_color=ui_theme.BORDER)
        self._on_close = on_close
        self._closed = False
        self._poll_job = None
        self._labels: dict[str, tk.Label] = {}
        self._handlers: dict[str, Callable[[], object]] = {}
        self._confirms: dict[str, RepeatConfirm] = {}
        self.card = ctk.CTkFrame(self, fg_color=ui_theme.CARD, corner_radius=12)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)
        self._build(list(rows), list(actions), version)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Button-1>", self._on_root_click)

    # ---- 画 ----------------------------------------------------------
    def _px(self, value: float) -> int:
        return int(round(value * self._scale))

    def _font(self, size: int, weight: str = "normal") -> tkfont.Font:
        # size 传负数 = 像素高度，跟 ctk 的 CTkFont(size=...) 一个口径
        return tkfont.Font(family=ui_theme.FONT, size=-self._px(ui_theme.type_size(size)),
                           weight=weight)

    def _build(self, rows: list[Row], actions: list[Action], version: str) -> None:
        pad = self._px(12)
        head = tk.Frame(self.card, bg=ui_theme.CARD)
        head.pack(fill="x", padx=pad, pady=(self._px(10), self._px(6)))
        tk.Label(head, text="小肥鱼控制台", bg=ui_theme.CARD, fg=ui_theme.TEXT,
                 font=self._font(13, "bold")).pack(side="left")
        if version:
            tk.Label(head, text=version, bg=ui_theme.CARD, fg=ui_theme.FAINT,
                     font=self._font(9)).pack(side="right")

        for row in rows:
            line = tk.Frame(self.card, bg=ui_theme.CARD, height=self._px(self.ROW_H))
            line.pack(fill="x", padx=pad)
            line.pack_propagate(False)
            tk.Label(line, text="●", width=2, anchor="w", bg=ui_theme.CARD,
                     fg=TONE_COLORS.get(row.tone, ui_theme.GREY_DARK),
                     font=self._font(8)).pack(side="left")
            tk.Label(line, text=row.label, width=4, anchor="w", bg=ui_theme.CARD,
                     fg=ui_theme.FAINT, font=self._font(10)).pack(side="left")
            tk.Label(line, text=row.text, anchor="w", bg=ui_theme.CARD,
                     fg=TONE_TEXT.get(row.tone, ui_theme.TEXT),
                     font=self._font(10)).pack(side="left", fill="x", expand=True)

        tk.Frame(self.card, height=1, bg=ui_theme.BORDER).pack(
            fill="x", padx=pad, pady=(self._px(6), self._px(5)))
        for index, (label, action, danger) in enumerate(actions):
            last = index == len(actions) - 1
            self._add_action(label, action, danger, pad=pad, last=last)

    def _add_action(self, label: str, action: Callable[[], None], danger: bool, *,
                    pad: int, last: bool) -> None:
        wrap = tk.Frame(self.card, bg=ui_theme.CARD, height=self._px(self.ACTION_H))
        wrap.pack(fill="x", padx=self._px(4),
                  pady=(self._px(1), max(pad, self._px(6)) if last else self._px(1)))
        wrap.pack_propagate(False)
        text = tk.Label(wrap, text=label, anchor="w", bg=ui_theme.CARD,
                        fg=ui_theme.RED if danger else ui_theme.TEXT, font=self._font(11))
        text.pack(fill="both", expand=True, padx=self._px(10))
        pair = (wrap, text)
        for widget in pair:
            widget.bind("<Enter>", lambda _event, w=pair: self._paint(w, ui_theme.CARD2))
            widget.bind("<Leave>", lambda _event, w=pair: self._paint(w, ui_theme.CARD))
            widget.bind("<Button-1>", lambda _event, key=label: self._fire(key))
        self._labels[label] = text
        self._handlers[label] = action

    @staticmethod
    def _paint(widgets: tuple[tk.Widget, ...], color: str) -> None:
        for widget in widgets:
            try:
                widget.configure(bg=color)
            except Exception:      # noqa: BLE001  窗口正在销毁时改色失败，不用管
                pass

    def _fire(self, label: str) -> None:
        """跑一个动作：返回 False 表示「还要再点一次」，卡片就先留着。"""
        handler = self._handlers.get(label)
        if handler is None or self._closed:
            return
        if handler() is not False:
            self.close()

    # ---- 弹 / 关 ------------------------------------------------------
    def popup(self, x: int, y: int) -> "TrayCard":
        self.update_idletasks()
        # geometry 的宽高会被 CTk 再乘一次缩放，所以这里先除回去，量到多少就是多少
        height = (self.card.winfo_reqheight() + 2) / self._scale
        self.geometry(f"{self.WIDTH}x{max(1, int(round(height)))}+{int(x)}+{int(y)}")
        try:
            self.attributes("-topmost", True)
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:       # noqa: BLE001  托盘场景下窗口管理不该把卡片拖死
            pass
        self._watch_foreground()
        return self

    def popup_near(self, cx: int, cy: int) -> "TrayCard":
        """贴在托盘图标旁边：右缘对着光标、向上展开，落在这块屏幕的工作区里。"""
        self.update_idletasks()
        height = self.card.winfo_reqheight() + 2
        size = (self._px(self.WIDTH), height)
        area = work_area((cx, cy))
        if area[2] <= area[0] or area[3] <= area[1]:
            area = (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        x, y = card_position((cx, cy), size, area)
        return self.popup(x, y)

    def _watch_foreground(self) -> None:
        if self._closed:
            return
        try:
            self._poll_job = self.after(150, self._check_foreground)
        except Exception:        # noqa: BLE001
            self._poll_job = None

    def _check_foreground(self) -> None:
        """前台不再是这张卡片就关：无边框窗口拿不到可靠的 FocusOut，只能问系统。"""
        self._poll_job = None
        if self._closed:
            return
        if not self._is_ours():
            self.close()
            return
        self._watch_foreground()

    def _is_ours(self) -> bool:
        try:
            user32 = ctypes.windll.user32          # type: ignore[attr-defined]
            foreground = int(user32.GetForegroundWindow() or 0)
            if not foreground:
                return True                        # 问不到就别乱关
            return foreground == int(user32.GetAncestor(int(self.winfo_id()), 2))   # GA_ROOT
        except Exception:      # noqa: BLE001  非 Windows 或缺 user32：当作是自己的
            return True

    def _on_root_click(self, event) -> None:
        if 0 <= event.x_root - self.winfo_rootx() < self.winfo_width() and \
                0 <= event.y_root - self.winfo_rooty() < self.winfo_height():
            return
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:  # noqa: BLE001
                pass
            self._poll_job = None
        callback, self._on_close = self._on_close, None
        try:
            self.destroy()
        except Exception:      # noqa: BLE001
            pass
        if callback is not None:
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

    @property
    def alive(self) -> bool:
        return not self._closed

    # ---- 两击确认 ----------------------------------------------------
    def arm(self, label: str, confirm_label: str, action: Callable[[], None], *,
            window: float = 2.0) -> None:
        """把某个动作换成两击确认；对不上 label 就什么都不做。"""
        text = self._labels.get(label)
        if text is None:
            return
        confirm = RepeatConfirm(label, confirm_label, window=window)
        self._confirms[label] = confirm

        def handler() -> bool:
            now = time.monotonic()
            if confirm.press(now):
                action()
                return True                    # 确认了：_fire 照常收卡片
            text.configure(text=confirm.text(now))
            self.after(int(window * 1000) + 80, lambda: self._disarm(label))
            return False                       # 只是上膛：卡片留着等第二击

        self._handlers[label] = handler

    def _disarm(self, label: str) -> None:
        confirm = self._confirms.get(label)
        text = self._labels.get(label)
        if confirm is None or text is None or self._closed:
            return
        if not confirm.armed(time.monotonic()):
            text.configure(text=confirm.label)
