"""自绘控件（批次 E「无环单列信息流」）：状态灯、模态浮层、全屏日志窗。

只负责「长什么样 + 怎么关」，不承载业务：浮层里的每一个动作都由调用方 dsh_gui 传进来。
所有颜色与尺寸取自 ui_theme，改皮肤不必动这里。抽屉菜单已随「大环 + 抽屉」一起删除：
操作全部平铺在主窗口里，不再有需要展开才知道存在的入口。
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from . import status as app_status
from . import ui_theme

MenuItem = tuple[str, Callable[[], None]]


def trim_textbox(box, limit: int) -> None:
    """行数自愈：超过 limit 就从顶部丢旧行。

    与主日志框同一套算法，放在这里给全屏窗复用；控件已销毁时静默返回。
    """
    try:
        total = int(str(box.index("end-1c")).split(".")[0])
    except Exception:
        return
    if total <= limit:
        return
    try:
        box.delete("1.0", "%d.0" % (total - limit + 1))
    except Exception:
        return


def snap_to_line(textbox) -> None:
    """把视口上沿对齐到整行，消掉顶部被切一半的那行。

    贴底（yview_moveto(1.0)）只保证最后一行可见，视口高度不是行高整数倍时，
    顶部那行就会只露下半截——而 index("@0,0") 报的是逻辑行，换行续行看不出错位。
    这里用内层控件的 dlineinfo 读那行的真实像素位置（y<0 表示行顶在视口之上），
    再按像素回滚。控件替身没有 _textbox，直接早退。
    """
    inner = getattr(textbox, "_textbox", None)
    if inner is None:
        return
    try:
        info = inner.dlineinfo("@0,0")
        if not info:
            return
        if info[1] < 0:
            inner.yview_scroll(info[1], "pixels")
    except Exception:  # noqa: BLE001 - 已销毁 / 控件替身
        return


class StatusLamp(ctk.CTkCanvas):
    """状态灯：一颗小圆点替代原来的 120px 大环，颜色 + 填充比例表达五态。

    读法：实心点＝走满一圈（未运行 / 运行中 / 异常），缺口弧＝还在路上（启动中 / 未知）。
    灯本身只有颜色和形状，状态词永远并列写在状态条上 —— 灰度截图与色弱用户靠那行字。
    Canvas 不吃 CTk 的几何缩放，尺寸按设计稿像素给，字与点的比例才稳。
    """

    def __init__(self, master, size: int = ui_theme.STATUS_LAMP, **kwargs) -> None:
        background = kwargs.pop("bg", ui_theme.CARD)
        pad = 3
        box = int(size) + pad * 2
        super().__init__(master, width=box, height=box, bg=background,
                         highlightthickness=0, bd=0, **kwargs)
        self._box = box
        self._pad = pad
        coords = (pad, pad, box - pad, box - pad)
        self.phase_text = ui_theme.PHASE_WORD[app_status.Phase.UNKNOWN]
        self.color = ui_theme.FAINT
        self.sweep = 0.0
        self._core = self.create_oval(*coords, outline=ui_theme.FAINT, fill=ui_theme.FAINT)
        self._arc = self.create_arc(*coords, start=90, extent=-90, style="arc",
                                    outline=ui_theme.FAINT, width=2)
        self._hollow = self.create_oval(*coords, outline=ui_theme.FAINT, width=1, fill="")
        self.render(ui_theme.FAINT, 0.0)

    def render(self, color: str, sweep: float) -> None:
        """重画一次：走满的实心、没走满的留弧、比例为 0 的只剩一圈空心。"""
        ratio = max(0.0, min(1.0, float(sweep)))
        filled = ratio >= 1.0
        partial = 0.0 < ratio < 1.0
        self.itemconfigure(self._core, fill=color, outline=color,
                           state="normal" if filled else "hidden")
        # 封顶 359 度：整圈会被 Tk 9 归零，画出来什么都没有。
        self.itemconfigure(self._arc, outline=color, extent=-359.0 * ratio,
                           state="normal" if partial else "hidden")
        self.itemconfigure(self._hollow, outline=color,
                           state="normal" if not filled and not partial else "hidden")
        self.color = color
        self.sweep = ratio

    def set_status(self, phase) -> None:
        """按阶段点亮：颜色与填充比例都取自 PHASE_STYLE。"""
        style = ui_theme.PHASE_STYLE.get(phase) or ui_theme.PHASE_STYLE[app_status.Phase.UNKNOWN]
        word = ui_theme.PHASE_WORD.get(phase) or ui_theme.PHASE_WORD[app_status.Phase.UNKNOWN]
        self.render(style.color, style.sweep)
        self.phase_text = word

class _PopLayer(ctk.CTkToplevel):
    """浮层共同骨架：无边框、居中、Esc 关闭、点外部关闭、✕ 关闭。

    grab_set 之后窗外的点击也会投给本窗口，所以用 x_root/y_root 判断点在不在里面。
    """

    def __init__(self, master, *, width: int, height: int, on_close=None) -> None:
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(fg_color=ui_theme.BORDER)
        self._width = int(width)
        self._height = int(height)
        self._on_close = on_close
        self._closed = False
        self.card = ctk.CTkFrame(self, fg_color=ui_theme.CARD, corner_radius=14)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Button-1>", self._on_root_click)

    def _on_root_click(self, event) -> None:
        if 0 <= event.x_root - self.winfo_rootx() < self.winfo_width() and \
                0 <= event.y_root - self.winfo_rooty() < self.winfo_height():
            return
        self.close()

    def _center(self) -> tuple[int, int]:
        try:
            master = self.master
            width, height = master.winfo_width(), master.winfo_height()
            if width > 1 and height > 1:
                return (master.winfo_rootx() + (width - self._width) // 2,
                        master.winfo_rooty() + (height - self._height) // 2)
        except Exception:
            pass
        return ((self.winfo_screenwidth() - self._width) // 2,
                (self.winfo_screenheight() - self._height) // 2)

    def show(self):
        self.update_idletasks()
        x, y = self._center()
        self.geometry("%dx%d+%d+%d" % (self._width, self._height, x, y))
        self.deiconify()
        try:
            self.attributes("-topmost", True)
            self.transient(self.master)
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass
        return self

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        callback, self._on_close = self._on_close, None
        try:
            self.destroy()
        except Exception:
            pass
        if callback is not None:
            try:
                callback()
            except Exception:
                pass


def overlay_header(layer: _PopLayer, title: str, subtitle: str = "") -> ctk.CTkFrame:
    """浮层标题栏：左标题（可带副标题）+ 右 ✕。返回下方内容容器。"""
    head = ctk.CTkFrame(layer.card, fg_color="transparent")
    head.pack(fill="x", padx=16, pady=(14, 8))
    left = ctk.CTkFrame(head, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(left, text=title, anchor="w", text_color=ui_theme.TEXT,
                 font=ctk.CTkFont(family=ui_theme.FONT, size=15, weight="bold")).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(left, text=subtitle, anchor="w", text_color=ui_theme.DIM,
                     font=ctk.CTkFont(family=ui_theme.FONT, size=11)).pack(anchor="w")
    ctk.CTkButton(head, text="✕", width=30, height=28, corner_radius=8, cursor="hand2",
                  fg_color="transparent", hover_color=ui_theme.CARD2,
                  text_color=ui_theme.DIM, font=ctk.CTkFont(family=ui_theme.FONT, size=13),
                  command=layer.close).pack(side="right", padx=(8, 0))
    body = ctk.CTkFrame(layer.card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
    return body


class QrOverlay(_PopLayer):
    """手机访问浮层：地址下拉 + 二维码 + 复制。关闭后主界面不留二维码。"""

    def __init__(self, master, *, on_close=None) -> None:
        width, height = ui_theme.OVERLAY_QR
        super().__init__(master, width=width, height=height, on_close=on_close)
        body = overlay_header(self, "手机访问", "同一 Wi-Fi 局域网，或已登录的 Tailscale")
        self.picker = ctk.CTkOptionMenu(
            body, values=["（尚未探测到地址）"], height=32, corner_radius=8,
            fg_color=ui_theme.CARD2, button_color=ui_theme.SLATE,
            button_hover_color=ui_theme.SLATE_DARK, text_color=ui_theme.TEXT,
            dropdown_fg_color=ui_theme.CARD2, dropdown_hover_color=ui_theme.SLATE,
            dropdown_text_color=ui_theme.TEXT,
            font=ctk.CTkFont(family=ui_theme.FONT, size=12),
            dropdown_font=ctk.CTkFont(family=ui_theme.FONT, size=12))
        self.picker.pack(fill="x")
        self.panel = ctk.CTkFrame(body, fg_color=ui_theme.WHITE_PANEL, corner_radius=12)
        self.panel.pack(fill="both", expand=True, pady=12)
        self.image_label = ctk.CTkLabel(self.panel, text="", fg_color=ui_theme.WHITE_PANEL,
                                        text_color=ui_theme.SLATE, width=252, height=252)
        self.image_label.pack(expand=True)
        self.hint = ctk.CTkLabel(body, text="", anchor="w", text_color=ui_theme.DIM,
                                 font=ctk.CTkFont(family=ui_theme.MONO, size=11))
        self.hint.pack(fill="x")
        self.actions = ctk.CTkFrame(body, fg_color="transparent")
        self.actions.pack(fill="x", pady=(10, 0))

    def bind_actions(self, copy_command: Callable[[], None],
                     on_select: Callable[[str], None] | None = None) -> None:
        ctk.CTkButton(self.actions, text="复制这个地址", height=34, corner_radius=8,
                      fg_color=ui_theme.SLATE, hover_color=ui_theme.SLATE_DARK,
                      text_color=ui_theme.TEXT,
                      font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=copy_command, cursor="hand2").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.actions, text="关闭", height=34, corner_radius=8,
                      fg_color="transparent", border_width=1, border_color=ui_theme.BORDER,
                      hover_color=ui_theme.CARD2, text_color=ui_theme.DIM,
                      font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=self.close, cursor="hand2").pack(side="left", padx=(10, 0))
        if on_select is not None:
            self.picker.configure(command=on_select)


class LogOverlay(_PopLayer):
    """全屏日志：镜像主日志框的内容，跟随/打码/截断都由主框先做一遍。"""

    def __init__(self, master, *, limit: int, on_close=None) -> None:
        width, height = ui_theme.OVERLAY_LOG
        super().__init__(master, width=width, height=height, on_close=on_close)
        body = overlay_header(self, "运行日志", "与主界面同一份内容 · 最多 %d 行" % limit)
        self._limit = int(limit)
        self.textbox = ctk.CTkTextbox(
            body, fg_color=ui_theme.BG, text_color=ui_theme.LOG_TEXT,
                      corner_radius=10,
            border_width=1, border_color=ui_theme.BORDER, wrap="word",
            font=ctk.CTkFont(family=ui_theme.MONO, size=12), state="disabled")
        self.textbox.pack(fill="both", expand=True)
        ctk.CTkButton(body, text="收起（Esc）", height=32, corner_radius=8,
                      fg_color=ui_theme.SLATE, hover_color=ui_theme.SLATE_DARK,
                      text_color=ui_theme.TEXT,
                      font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=self.close, cursor="hand2").pack(anchor="e", pady=(10, 0))
        self.line_count = 0

    def fill(self, text: str) -> None:
        """整体替换：调用方已经把内容打码并截断过一次，这里只做长度保险。"""
        try:
            self.textbox.configure(state="normal")
            self.textbox.delete("1.0", "end")
            if text:
                self.textbox.insert("1.0", text + "\n")
            trim_textbox(self.textbox, self._limit)
            self.textbox.configure(state="disabled")
            self.line_count = int(str(self.textbox.index("end-1c")).split(".")[0])
        except Exception:
            return

    def follow(self) -> None:
        """贴到末尾，再把上沿对齐到行首：只做 yview_moveto(1.0) 会让第一行只露下半截。"""
        try:
            self.textbox.yview_moveto(1.0)
        except Exception:
            return
        snap_to_line(self.textbox)
        # 首次显示时行高还没量出来（dlineinfo 返回空），窗口画完再对一次。
        try:
            self.textbox.after(80, lambda: snap_to_line(self.textbox))
        except Exception:  # noqa: BLE001 - 已销毁
            pass
