"""DSH 控制台 - DeepSeek Harness 桌面图形界面 (customtkinter · 蓝鲸主题)

双击 exe / 运行本脚本即可打开窗口。功能与旧版一致：
  启动 Harness、开启手机访问（端口转发+信任来源）、恢复本机、复制手机地址、
  生成二维码（窗口内显示，刷新/关闭即清除，不落盘）、停止 Harness、实时查看状态。

UI 以 DeepSeek 品牌蓝 #4D6BFE 为主基调，深色科技风，头部展示 DeepSeek 鲸鱼娘图标。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from dshconsole import (addresses, adopt, config, diagnostics, errors, logtail, probe,
                        psrun, resources, single, snapshot, status, tasks, textutil, tray)

CFG = config.resolve()          # 本机探测结果；缺项为 None，探测失败不抛异常
HARNESS = CFG.harness
LAUNCH_PS1 = resources.launch_ps1()      # 随包发布的脚本，不再依赖外部 harness 目录
SWITCH_PS1 = resources.switch_ps1()
TOKEN_LOG = CFG.token_log
ICON_FILE = resources.icon_path()
CREATE_NO_WINDOW = 0x08000000      # 自检里伪造进程时别闪出控制台窗口
PORT = CFG.port
APP_TITLE = "DSH 控制台"            # 单实例守卫靠窗口标题找回已有窗口，两处必须一致
_APP = None                        # 当前窗口实例：未捕获异常写日志用（见 _report）
MAX_LOG_LINES = 2000               # 日志框行数上限：超过就从顶部滚动丢弃旧行
LOG_POLL_INTERVAL = 0.4            # 跟随真实日志的轮询间隔（秒，≥0.3，不许 busy loop）
STATUS_TTL = 3.0                   # 状态缓存：连点刷新不重复扫描，手动刷新穿透

# ---------------- 主题（DeepSeek 蓝） ----------------
PRIMARY = "#4D6BFE"        # DeepSeek 品牌蓝
PRIMARY_HOVER = "#3A55E0"
CYAN = "#35D5F4"
GREEN = "#2BB673"
GREEN_DARK = "#1E8F5B"
RED = "#F0526B"
RED_DARK = "#C93A52"
VIOLET = "#8B5CF6"
VIOLET_DARK = "#6F43D8"
TEAL = "#14B8A6"
TEAL_DARK = "#0D9488"
SLATE = "#44527A"
SLATE_DARK = "#34405E"
BG = "#070C1A"             # 窗口底色
CARD = "#0E1830"           # 卡片
CARD2 = "#152242"          # 次级卡片
BORDER = "#1D2B4F"
TEXT = "#E6EDF8"
DIM = "#8A97B8"
FAINT = "#5C6B8E"
WHITE_PANEL = "#FFFFFF"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# 阶段 -> (颜色, 圆点)。UNKNOWN 用灰而不是红：查不到不等于未运行。
_PHASE_STYLE = {
    status.Phase.RUNNING: (GREEN, "●"),
    status.Phase.STARTING: (CYAN, "◔"),
    status.Phase.DEGRADED: (VIOLET, "◐"),
    status.Phase.STOPPED: (RED, "○"),
    status.Phase.UNKNOWN: (FAINT, "？"),
}


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def _mono(size: int) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=size)


def _icon_candidates() -> list[Path]:
    icon = CFG.icon or ICON_FILE
    return [icon] if icon else []


def _ps_args(include_chrome: bool = False) -> list[str]:
    """ps1 的值参数一律显式传；缺项不传，由脚本自己回退。"""
    pairs = [("-Harness", HARNESS), ("-NodeExe", CFG.node), ("-BinJs", CFG.bin_js),
             ("-DshHome", CFG.dsh_home), ("-Port", PORT)]
    if include_chrome:
        pairs.append(("-Chrome", CFG.chrome))
    args: list[str] = []
    for flag, value in pairs:
        if value:
            args += [flag, str(value)]
    return args


# ---------------- 探测与 ps 调用（统一走 psrun / probe，失败原因不再被吞） ----------------
def run_ps(script: Path, *args: str, timeout: int = 60) -> psrun.PsResult:
    """跑随包发布的 ps1；成功与否看返回对象，不从输出里抠值。"""
    return psrun.run_ps(script, *args, timeout=timeout)


def port_open(port: int | None = None) -> bool:
    return probe.port_open(PORT if port is None else port)


def dsh_pids() -> tuple[list[int] | None, str | None]:
    """命令行里带本机 bin.js 的 node 进程；None = 查不到（不是「没在跑」）。"""
    return probe.dsh_processes(CFG.bin_js)


def _report(text: str) -> None:
    """未捕获异常的出口：有窗口就写日志框，没有窗口就写 stderr —— 绝不静默。"""
    app = _APP
    if app is not None:
        try:
            app.log_async(text)
            return
        except Exception:  # noqa: BLE001 - 窗口已销毁：退回 stderr
            pass
    try:
        print(text, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _info_blocking(title: str, message: str) -> None:
    """没有窗口可用时的一次性说明框；连 Tk 都起不来就只写 stderr。"""
    try:
        root = ctk.CTk()
        root.withdraw()
        try:
            messagebox.showinfo(title, message, parent=root)
        finally:
            root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


def phone_ready() -> tuple[bool | None, str | None]:
    """手机访问是否真的开启：端口转发指向本机端口 + 防火墙规则都在。"""
    ok, _targets, notes = status.probe_phone(CFG)
    return ok, (notes[0] if notes else None)


def token_suffix(url: str) -> str:
    """从带 token 的地址里抠出 token 本身（剪贴板放完整地址是功能）。"""
    return url.split("token=", 1)[1] if "token=" in url else url


def token_url() -> str | None:
    if TOKEN_LOG is None:
        return None
    try:
        text = TOKEN_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(rf"dsh web: (http://127\.0\.0\.1:{PORT}/\?token=[A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else None



def make_qr(url: str):
    """生成二维码 PIL 图像（仅在内存中，不落盘）。"""
    import qrcode  # 本地 venv 已安装

    qr = qrcode.QRCode(border=2, box_size=7)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


def mascot_image() -> Image.Image | None:
    """读取 DeepSeek 鲸鱼娘图标（256x256 RGBA，取最大帧）。"""
    candidates = _icon_candidates()
    for ico in candidates:
        try:
            if ico.is_file():
                img = Image.open(ico)
                sizes = list(img.info.get("sizes") or [])
                if sizes:
                    idx = max(range(len(sizes)), key=lambda i: sizes[i][0] * sizes[i][1])
                    img.seek(idx)
                else:
                    img.seek(0)
                return img.convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------- 主窗口 ----------------
class ConsoleApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self._set_icon()
        self.geometry("720x880")
        self.minsize(660, 780)
        self.configure(fg_color=BG)
        self._qr_photo = None
        self._token: str | None = None
        self._candidates: list[adopt.Candidate] = []   # 端口被占用时查到的别的 DSH 进程
        self._adopt_shown = False
        self._last_status: status.Status | None = None  # 上次探测结果：刷新时先显示它
        self._last_raw = None                          # 上次的原始探测数据，只给诊断包用
        # 可注入的探测口：自检用替身，不再改写模块全局（B2-3）
        self._pids_provider = dsh_pids
        self._port_open = port_open
        self._status_provider = self._load_status
        self._snapshot = snapshot.Snapshot(lambda: self._status_provider(), ttl=STATUS_TTL)
        self._queue = tasks.TaskQueue(post=self._post, on_change=self._on_queue_change)
        self._activator = single.Activator()    # 第二个实例叫醒窗口用（见 _poll_activate）
        self._tray: tray.Tray | None = None
        self._tail: logtail.LogTailer | None = None
        self._close_to_tray = config.close_to_tray()
        self.report_callback_exception = self._on_callback_error
        self._build()
        self.logline(f"DSH：{HARNESS or '未检测到'}  ·  端口 {PORT}  ·  node：{CFG.node or '未检测到'}")
        self._start_tray()
        self._start_log_tail()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self.refresh)
        self.after(400, self._poll_activate)

    # ---------------- 线程投递 / 关闭 / 托盘 ----------------
    def _post(self, fn, *args) -> None:
        """把工作线程或托盘线程的回调投递回 Tk 主线程（跨线程碰控件是禁忌）。"""
        try:
            self.after(0, fn, *args)
        except Exception:      # noqa: BLE001 - 窗口已销毁：没人需要这个回调了
            pass

    def _start_log_tail(self) -> None:
        """跟随真实日志文件（dsh-web.stdout.log / .stderr.log）。"""
        try:
            self._tail = logtail.LogTailer(CFG.log_files, self._on_tail_lines,
                                           interval=LOG_POLL_INTERVAL)
            self._tail.start()
            self.logline("正在跟随日志：" + "、".join(Path(p).name for p in CFG.log_files))
        except Exception as exc:      # noqa: BLE001 - 跟随失败不该影响主功能
            self._tail = None
            self.logline(f"日志跟随没能启动：{exc}（只显示界面事件）")

    def _on_tail_lines(self, path, lines) -> None:
        """后台线程回调：内容已经脱敏（logtail 里过过 redact_text），这里只投递。"""
        self._post(self._append_log, lines, f"[{Path(path).name}] ")

    def _start_tray(self) -> bool:
        if not self._close_to_tray:
            return False                # 用户选了「关闭即退出」：不起托盘
        self._tray = tray.Tray(post=self._post, on_lost=self._on_tray_lost)
        ok, why = self._tray.start(self._tray_items())
        if ok:
            self.logline("托盘已就绪：关闭按钮会收进托盘，真退出请用托盘菜单「退出」。")
            return True
        self._tray = None
        self._close_to_tray = False     # 起不来就退回普通窗口，别把用户锁在托盘里
        self._sync_close_switch()
        self.logline(f"{why}：本次按普通窗口运行，关闭按钮＝退出。")
        return False

    def _on_tray_lost(self, reason: str) -> None:
        """托盘线程没了：立刻退回普通窗口，否则用户会以为程序还在。"""
        self.logline(f"{reason}：退回普通窗口，关闭按钮＝退出。")
        self._tray = None
        self._close_to_tray = False
        self._sync_close_switch()

    def _tray_items(self):
        return [
            (self._window_label, self._toggle_window),
            ("复制手机访问地址", self._tray_copy),
            ("停止 DSH", self.on_stop),
            ("退出", self._quit),
        ]

    def _tray_copy(self) -> None:
        """托盘里点「复制」：不走弹窗（托盘场景下用户可能看不见窗口）。"""
        known, _unknown = self._address_options()
        token = self._current_token()
        if not token or not known:
            self.logline("还没有可复制的手机地址：先启动 Harness 并确认地址。")
            return
        addr = known[0][1]
        url = f"{addr.url(PORT)}?token={token_suffix(token)}"
        self.clipboard_clear()
        self.clipboard_append(url)
        self.logline(f"已复制（{addr.label}）：" + textutil.redact(url))

    def _window_label(self) -> str:
        try:
            return "隐藏主窗口" if self.state() == "normal" else "显示主窗口"
        except Exception:      # noqa: BLE001
            return "显示主窗口"

    def _show_window(self) -> None:
        """从托盘/最小化里把窗口显示出来并聚焦（收进托盘时是 withdraw 状态）。"""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:      # noqa: BLE001
            return

    def _toggle_window(self) -> None:
        """托盘菜单的显示/隐藏（在主线程执行，见 Tray 的 post）。"""
        try:
            if self.state() == "normal":
                self.withdraw()
            else:
                self._show_window()
        except Exception:      # noqa: BLE001
            return
        if self._tray is not None:
            self._tray.update_menu(self._tray_items())

    def _poll_activate(self) -> None:
        """轮询「叫醒」事件：另一个实例双击时，收在托盘里的窗口要自己回来。"""
        try:
            if self._activator.wait(0):
                self._show_window()
                if self._tray is not None:
                    self._tray.update_menu(self._tray_items())
                self.logline("另一个实例请求显示窗口，已显示并聚焦。")
        except Exception:      # noqa: BLE001 - 轮询本身不该炸掉事件循环
            pass
        try:
            self.after(500, self._poll_activate)
        except Exception:      # noqa: BLE001 - 窗口已销毁
            pass

    def _sync_close_switch(self) -> None:
        """把开关拨到当前真实行为上（不起托盘时不该显示成「收进托盘」）。"""
        try:
            if self._close_to_tray:
                self.sw_tray.select()
            else:
                self.sw_tray.deselect()
        except Exception:      # noqa: BLE001
            pass

    def _on_close_mode_change(self) -> None:
        """一键在「关闭收进托盘」与「关闭即退出」之间切换，并写回 config.json。"""
        want = bool(self.sw_tray.get())
        self._close_to_tray = want
        try:
            config.set_close_to_tray(want)
        except Exception as exc:      # noqa: BLE001 - 写不进去也要让本次生效
            self.logline(f"关闭行为没能写进 config.json：{exc}（本次仍然生效）")
        if want:
            if self._tray is None or not self._tray.running:
                self._start_tray()
            self.logline("关闭按钮＝收进托盘。")
        else:
            if self._tray is not None:
                self._tray.stop()
                self._tray = None
            self.logline("关闭按钮＝退出程序。")
        self._sync_close_switch()

    def _on_close(self) -> None:
        """关闭按钮：收进托盘（可一键改回退出），绝不悄悄退掉。"""
        if self._close_to_tray and self._tray is not None:
            self.clear_qr()
            try:
                self.withdraw()
            except Exception:      # noqa: BLE001
                self._quit()
                return
            self._tray.update_menu(self._tray_items())
            self.logline("已收进托盘；要退出请用托盘右键菜单「退出」。")
            return
        self._quit()

    def _quit(self) -> None:
        """真退出：先停后台线程（日志跟随、托盘），再销毁窗口。"""
        self.clear_qr()
        tail, self._tail = self._tail, None
        if tail is not None:
            tail.stop()
        tray_icon, self._tray = self._tray, None
        if tray_icon is not None:
            tray_icon.stop()
        try:
            self.destroy()
        except Exception:      # noqa: BLE001 - 已经在销毁路径上
            pass

    def _set_icon(self) -> None:
        candidates = _icon_candidates()
        for ico in candidates:
            try:
                if ico.is_file():
                    self.iconbitmap(default=str(ico))
                    return
            except Exception:  # noqa: BLE001
                pass

    # ---------------- UI ----------------
    def _build(self) -> None:
        # --- 头部：鲸鱼娘 + 标题 ---
        head = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        head.pack(fill="x", padx=14, pady=(14, 8))
        mascot = mascot_image()
        if mascot is not None:
            ctk.CTkLabel(head, text="", image=ctk.CTkImage(light_image=mascot, dark_image=mascot, size=(56, 56))).pack(side="left", padx=(16, 12), pady=12)
        title_box = ctk.CTkFrame(head, fg_color="transparent")
        title_box.pack(side="left", pady=10)
        ctk.CTkLabel(title_box, text="DeepSeek Harness 控制台", font=_font(17, True),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(title_box, text="本地入口 · 手机访问管理", font=_font(11),
                     text_color=DIM, anchor="w").pack(anchor="w")

        # --- 状态卡片 ---
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=14, pady=6)
        self.lbl_service = ctk.CTkLabel(card, text="服务状态：--", font=_font(12, True),
                                        text_color=FAINT, anchor="w")
        self.lbl_service.pack(fill="x", padx=14, pady=(12, 4))
        self.lbl_phone = ctk.CTkLabel(card, text="手机访问：--", font=_font(12, True),
                                      text_color=FAINT, anchor="w")
        self.lbl_phone.pack(fill="x", padx=14, pady=4)
        self.lbl_net = ctk.CTkLabel(card, text="网络：--", font=_font(11),
                                    text_color=DIM, anchor="w", justify="left")
        self.lbl_net.pack(fill="x", padx=14, pady=(4, 12))
        # 采纳按钮：只有「异常（端口被占用）且查到占用者」时才 pack 出来（见 _sync_adopt_button）
        self.btn_adopt = ctk.CTkButton(
            card, text="改为控制运行中的实例", command=self.on_adopt,
            fg_color=VIOLET, hover_color=VIOLET_DARK, text_color="#FFFFFF",
            font=_font(12, True), height=36, corner_radius=10, cursor="hand2")
        # 队列说明：排队/执行中的状态写在这里，按钮本身从不禁用（C5）
        self.lbl_queue = ctk.CTkLabel(card, text="", font=_font(11), text_color=DIM,
                                      anchor="w", justify="left")
        self.lbl_queue.pack(fill="x", padx=14, pady=(0, 10))

        # --- 按钮区 ---
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=6)
        for col in range(2):
            grid.columnconfigure(col, weight=1)
        buttons = [
            ("▶  启动 DeepSeek Harness", self.on_start, PRIMARY, PRIMARY_HOVER),
            ("⏹  停止 DeepSeek Harness", self.on_stop, RED, RED_DARK),
            ("📱  开启手机访问（需 UAC）", self.on_phone_on, GREEN, GREEN_DARK),
            ("🏠  恢复本机模式（需 UAC）", self.on_phone_off, SLATE, SLATE_DARK),
            ("📋  复制手机地址", self.on_copy, VIOLET, VIOLET_DARK),
            ("🔳  Tailscale 二维码", self.on_qr_ts, TEAL, TEAL_DARK),
            ("🔳  局域网 二维码", self.on_qr_lan, TEAL, TEAL_DARK),
            ("🔄  刷新状态", self.on_refresh, SLATE, SLATE_DARK),
            ("🩺  导出诊断包", self.on_export_diag, SLATE, SLATE_DARK),
            ("✖  取消排队", self.on_cancel_queue, SLATE, SLATE_DARK),
        ]
        for i, (text, cmd, color, hover) in enumerate(buttons):
            btn = ctk.CTkButton(grid, text=text, command=cmd, fg_color=color,
                                hover_color=hover, text_color="#FFFFFF",
                                font=_font(12, True), height=42, corner_radius=10,
                                cursor="hand2")
            btn.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)

        # --- 二维码卡片 ---
        qr_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                               border_width=1, border_color=BORDER)
        qr_card.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(qr_card, text="手机地址二维码", font=_font(12, True),
                     text_color=TEXT, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.qr_label = ctk.CTkLabel(
            qr_card, text="点「二维码」按钮生成，直接显示在这里；\n刷新状态或关闭窗口后自动清除",
            font=_font(11), text_color=FAINT, width=252, height=252,
            fg_color=WHITE_PANEL, corner_radius=10)
        self.qr_label.pack(pady=(2, 12))

        # --- 日志卡片 ---
        log_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                                border_width=1, border_color=BORDER)
        log_card.pack(fill="both", expand=True, padx=14, pady=6)
        ctk.CTkLabel(log_card, text="运行日志", font=_font(12, True),
                     text_color=TEXT, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.log = ctk.CTkTextbox(log_card, height=150, fg_color="#0A1226",
                                  text_color="#C7D3EA", font=_mono(12),
                                  corner_radius=10, border_width=1, border_color=BORDER,
                                  wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # --- 底栏 ---
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(foot, text=f"本机：http://127.0.0.1:{PORT}", font=_font(11),
                     text_color=DIM, anchor="w").pack(side="left")
        # 关闭行为一键切换：把用户锁死在托盘里是不可接受的
        self.sw_tray = ctk.CTkSwitch(foot, text="关闭窗口时收进托盘",
                                     command=self._on_close_mode_change,
                                     font=_font(11), text_color=DIM,
                                     progress_color=PRIMARY, width=150)
        self.sw_tray.pack(side="right", padx=(8, 0))
        ctk.CTkButton(foot, text="复制本机地址", command=self.on_copy_local, width=110,
                      height=28, corner_radius=8, fg_color=CARD2, hover_color="#1D2D55",
                      text_color=TEXT, font=_font(11), cursor="hand2").pack(side="right")
        self._sync_close_switch()

    # ---------------- helpers ----------------
    def logline(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self._scroll_log_to_end()
        self.log.configure(state="disabled")

    def log_async(self, msg: str) -> None:
        """线程安全写日志：委托回 Tk 主线程，避免跨线程操作控件。

        窗口已销毁时 Tk 会拒绝投递（RuntimeError/TclError），此时退回 stderr，
        绝不让工作线程自己炸掉。
        """
        try:
            self.after(0, self.logline, msg)
        except Exception:  # noqa: BLE001 - 退出路径上窗口可能已经没了
            print(msg, file=sys.stderr)

    def _append_log(self, lines, prefix: str = "", limit: int = MAX_LOG_LINES) -> None:
        """往日志框追加若干行，超过上限就从顶部丢（滚动丢弃旧行）。"""
        try:
            self.log.configure(state="normal")
            for line in lines:
                self.log.insert("end", prefix + line + "\n")
            self._trim_log(limit)
            self._scroll_log_to_end()
            self.log.configure(state="disabled")
        except Exception:  # noqa: BLE001 - 窗口已销毁：没人看日志了
            pass

    def _scroll_log_to_end(self) -> None:
        """滚到末尾。用 yview_moveto 而不是 see("end")：see 要先算出末尾的 bbox，
        实测一次能吃掉 56 ms（日志几千行时更久），yview_moveto 近乎免费。"""
        try:
            self.log.yview_moveto(1.0)
        except Exception:  # noqa: BLE001 - 控件替身/已销毁
            try:
                self.log.see("end")
            except Exception:  # noqa: BLE001
                pass

    def _trim_log(self, limit: int = MAX_LOG_LINES) -> None:
        try:
            total = int(str(self.log.index("end-1c")).split(".")[0])
        except Exception:  # noqa: BLE001 - 控件替身/已销毁
            return
        if total <= limit:
            return
        try:
            self.log.delete("1.0", f"{total - limit + 1}.0")
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 串行队列（替代原来的全局 _busy） ----------------
    def _submit(self, name: str, work, on_done=None):
        """把一个后台操作放进串行队列：界面保持可点，排队中的还能取消。"""
        def run():
            try:
                return work()
            except Exception as exc:  # noqa: BLE001 - 后台异常必须显式落到日志
                self.log_async(f"出错：{exc}\n"
                               + errors.summarize(type(exc), exc, exc.__traceback__))
                raise
            finally:
                self._snapshot.invalidate()   # 操作之后的状态不该从旧缓存里拿
                self._post(self.refresh)
        return self._queue.submit(name, run, on_done)

    def _on_queue_change(self) -> None:
        """队首/排队数变了就更新一行说明；按钮从不因此被禁用。"""
        try:
            running = self._queue.running
            pending = self._queue.pending()
        except Exception:  # noqa: BLE001
            return
        if running is None and not pending:
            text = ""
        elif running is not None:
            text = f"⏳ 执行中：{running.name}"
            if pending:
                text += f"；排队中 {len(pending)} 个（可以取消）"
        else:
            text = f"⏳ 排队中（前面还有 {len(pending)} 个）"
        try:
            self.lbl_queue.configure(text=text)
        except Exception:  # noqa: BLE001
            pass

    def on_cancel_queue(self) -> None:
        """取消所有还在排队的任务（正在执行的不强杀，等它自己结束）。"""
        count = self._queue.cancel_all_pending()
        if count:
            self.logline(f"已取消 {count} 个排队中的任务；正在执行的那个会跑完。")
        else:
            self.logline("没有排队中的任务可取消。")

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        """Tk 回调里的异常：写脱敏 traceback，绝不静默吞掉。"""
        text = errors.summarize(exc_type, exc, tb)
        try:
            self.logline("界面回调异常：\n" + text)
        except Exception:  # noqa: BLE001 - 日志框都坏了也不能把异常吞掉
            print("界面回调异常：\n" + text, file=sys.stderr)

    # ---------------- status ----------------
    def _load_status(self) -> "status.Status":
        """一次探测：原始数据留给诊断包，状态留给界面。"""
        raw = probe.probe_all(int(PORT), CFG.tailscale)
        state = status.probe_status_batch(CFG, raw=raw)
        self._last_raw = raw
        return state

    def on_refresh(self) -> None:
        """手动刷新：强制穿透缓存 —— 用户点它就是要看现在的真相。"""
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """非阻塞刷新：先显示上次结果 + 「刷新中…」，后台跑完再回填。

        探测要 spawn PowerShell（本机约 2 秒），绝不能放在主线程上：窗口打开、
        点刷新、任务结束时的刷新都走这条路，界面一次都不该冻住。
        """
        try:
            self.clear_qr()   # 刷新即清除旧二维码，避免堆积/残留
        except Exception:  # noqa: BLE001
            pass
        self._show_refreshing()

        def work() -> None:
            try:
                state, _cached = self._snapshot.get(force=force)
            except Exception as exc:  # noqa: BLE001
                self.log_async(f"状态刷新失败：{exc}\n"
                               + errors.summarize(type(exc), exc, exc.__traceback__))
                self._post(self._show_refresh_failed, str(exc))
                return
            # token 要在后台线程里读：主线程读日志 + 正则会和探测线程抢 GIL
            self._post(self._apply_status, state, token_url())

        threading.Thread(target=work, daemon=True, name="dsh-refresh").start()

    def _show_refreshing(self) -> None:
        try:
            if self._last_status is None:
                self.lbl_service.configure(text="⟳  刷新中…", text_color=CYAN)
                return
            color, dot = _PHASE_STYLE[self._last_status.phase]
            self.lbl_service.configure(
                text=f"{dot}  服务状态：{self._last_status.phase.label}　⟳ 刷新中…",
                text_color=color)
        except Exception:  # noqa: BLE001 - 窗口已销毁
            pass

    def _show_refresh_failed(self, why: str) -> None:
        try:
            self.lbl_service.configure(text=f"？  状态未知：刷新失败（{why[:60]}）",
                                       text_color=FAINT)
        except Exception:  # noqa: BLE001
            pass

    def _apply_status(self, state: "status.Status", token: "str | None" = None) -> None:
        """回填一次状态：所有控件改动都压在一次回调里，且每个控件只 configure 一次。

        这个函数跑在 Tk 主线程上，探测线程还在收尾时会跟它抢 GIL —— 实测空闲时
        一次 ~15 ms，抢 GIL 时一次 Tk 调用就要 20 ms 上下。所以这里的原则是
        「少调用」：说明文字合成一次 insert，能后台算的（token）都在后台算。
        """
        self._last_status = state
        color, dot = _PHASE_STYLE[state.phase]
        self.lbl_service.configure(text=f"{dot}  服务状态：{state.phase.label}", text_color=color)
        if state.phone_open is None:
            phone_text, phone_dot, phone_color = "未知（原因见日志）", "？", FAINT
        elif state.phone_open:
            phone_text, phone_dot, phone_color = "已开启（Tailscale / 局域网可访问）", "●", GREEN
        else:
            phone_text, phone_dot, phone_color = "本机模式", "○", DIM
        self.lbl_phone.configure(text=f"{phone_dot}  手机访问：{phone_text}", text_color=phone_color)
        ts = state.ts_ip or "未知"
        lans = "、".join(state.lan_ips) if state.lan_ips else "未知"
        self._token = token if token is not None else token_url()
        self.lbl_net.configure(
            text=f"Tailscale：{ts}\n局域网：{lans}\n"
                 f"Token：{'已获取（点「复制手机地址」发送）' if self._token else '未获取（启动后生成）'}")
        if state.notes:
            stamp = time.strftime("[%H:%M:%S] ")
            self._append_log([stamp + note for note in state.notes])
        self._candidates = (adopt.from_processes(state.others)
                            if state.phase is status.Phase.DEGRADED else [])
        self._sync_adopt_button()

    def _sync_adopt_button(self) -> None:
        """异常（端口被占用）且查到占用者时才摆出采纳按钮；状态一正常就收起。"""
        if not self._candidates:
            if self._adopt_shown:
                self.btn_adopt.pack_forget()
                self._adopt_shown = False
            return
        count = len(self._candidates)
        text = (f"🔧  改为控制运行中的实例（PID {self._candidates[0].pid}）" if count == 1
                else f"🔧  改为控制运行中的实例（{count} 个候选，点击后选择）")
        self.btn_adopt.configure(text=text)
        if not self._adopt_shown:
            self.btn_adopt.pack(fill="x", padx=14, pady=(0, 12))
            self._adopt_shown = True

    # ---------------- actions ----------------
    def on_adopt(self) -> None:
        """采纳正在跑的那处安装：把它的 harness 写回 config.json。"""
        self._submit("采纳运行中的实例", self._adopt)

    def _adopt(self) -> None:
        global CFG, HARNESS, TOKEN_LOG, PORT
        cands = list(self._candidates)
        if not cands:
            self.log_async("没有可采纳的候选进程（先刷新状态再试）。")
            return
        if len(cands) == 1:
            chosen = cands[0]
        else:
            index = self._ask_main(self._pick_candidate, cands)
            if index is None:
                self.log_async("已取消，config.json 未改动。")
                return
            chosen = cands[index]
        new_cfg, reason = adopt.adopt(CFG, chosen)
        if new_cfg is None:
            self.log_async(reason)
            self._ask_main(messagebox.showerror, "无法采纳", reason)
            return
        CFG, HARNESS, PORT = new_cfg, new_cfg.harness, new_cfg.port
        TOKEN_LOG = new_cfg.token_log
        self.log_async(reason)
        # 采纳成功就没得选了：先把按钮收起来，别让用户对着一个过时的按钮再点一次。
        # （完整重探由 _wrap 的 finally 触发，探测要十几秒，等它回来才收太迟钝。）
        self._candidates = []
        self.after(0, self._sync_adopt_button)

    def _pick_candidate(self, cands: list) -> "int | None":
        """多个候选时让用户选序号，不默认第一个（选错就去控制错误的实例了）。"""
        listing = "\n".join(f"{i + 1}. {c.label}" for i, c in enumerate(cands))
        dialog = ctk.CTkInputDialog(
            text=f"检测到 {len(cands)} 处正在运行的 DSH，请输入要接管的序号：\n{listing}",
            title="选择要控制的实例")
        raw = dialog.get_input()
        if not raw:
            return None
        try:
            index = int(raw.strip()) - 1
        except ValueError:
            return None
        return index if 0 <= index < len(cands) else None
    def on_start(self) -> None:
        self._submit("启动 DeepSeek Harness", self._start)

    def _start(self) -> None:
        self.log_async("正在启动 DeepSeek Harness…")
        r = run_ps(LAUNCH_PS1, *_ps_args(include_chrome=True), timeout=90)
        out = (r.stdout or "").strip()
        if out:
            self.log_async(out[-300:])
        self.log_async("启动完成。")

    def on_stop(self) -> None:
        """先查出将被结束的 PID 让用户确认，再动手；不确定就一个都不杀。"""
        self._submit("停止 DeepSeek Harness", self._stop_prepare)

    def _stop_prepare(self) -> None:
        pids, err = self._pids_provider()
        if pids is None:
            self.log_async(f"未知：node 进程查不到（{err}），已取消停止，避免误杀。")
            self._ask_main(messagebox.showerror, "无法停止",
                           f"查不到正在运行的 node 进程：\n{err}\n\n"
                           "无法确认哪些进程是 DSH，本次没有结束任何进程。")
            return
        if not pids:
            self.log_async("没有找到正在运行的 DSH 进程，未做任何操作。")
            self._ask_main(messagebox.showinfo, "未在运行", "没有找到正在运行的 DSH 进程。")
            return
        listing = "\n".join(f"    PID {pid}" for pid in pids)
        bin_js = str(CFG.bin_js) if CFG.bin_js else "（未探测到 bin.js）"
        if not self._ask_main(messagebox.askyesno, "停止确认",
                              f"将结束以下 node 进程：\n{listing}\n\n"
                              f"识别依据：命令行里含\n    {bin_js}\n\n"
                              "当前网页会断开（会话已存档可重开）。继续吗？"):
            self.log_async("已取消停止，未结束任何进程。")
            return
        self.log_async(f"准备结束 PID：{'、'.join(str(p) for p in pids)}")
        self._stop(pids)

    def _stop(self, pids: list[int]) -> None:
        for pid in pids:
            result = psrun.run_ps_cmd(
                f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop; 'stopped'")
            if result.ok and "stopped" in result.stdout:
                self.log_async(f"已结束 node.exe PID {pid}")
            else:
                self.log_async(f"停止 PID {pid} 失败：{result.why() or result.text.strip()[:200]}")
        for _ in range(20):
            time.sleep(0.3)
            if not self._port_open():
                break
        if self._port_open():
            left, err = self._pids_provider()
            if left is None:
                self.log_async(f"警告：{PORT} 仍在监听，且剩余进程查不到（{err}）。")
            else:
                shown = "、".join(str(pid) for pid in left) or "无"
                self.log_async(f"警告：{PORT} 仍在监听，未完全停止（剩余 PID：{shown}）。")
        else:
            self.log_async("DeepSeek Harness 已停止。")

    def _ask_main(self, fn, *args):
        """在工作线程里等主线程弹一次对话框（Tk 控件只能主线程碰）。"""
        box: dict[str, object] = {}
        done = threading.Event()

        def call() -> None:
            try:
                box["value"] = fn(*args)
            finally:
                done.set()

        self.after(0, call)
        done.wait(timeout=120)
        return box.get("value")
    def on_phone_on(self) -> None:
        self._submit("开启手机访问", self._phone_on)

    def _phone_on(self) -> None:
        self.log_async("正在开启手机访问（将弹出 UAC 提权窗口，请点“是”并等待）…")
        result = run_ps(SWITCH_PS1, *_ps_args(), "-NoPause", timeout=90)
        self.log_async((result.stdout or "").strip()[-400:] or "切换脚本已在后台运行。")
        warned = False
        for _ in range(40):
            time.sleep(0.5)
            ok, why = phone_ready()
            if ok is True:
                self.log_async("手机访问已开启。用“复制手机地址”把地址发到手机。")
                return
            if ok is None and not warned:
                self.log_async(f"未知：{why}（继续等待）")
                warned = True
        self.log_async("等待超时：请检查弹窗是否已确认提权。")
    def on_phone_off(self) -> None:
        if not messagebox.askyesno("恢复本机", "确定恢复本机模式并关闭手机访问吗？\n（会重启 DSH 服务，当前网页会断开）"):
            return
        self._submit("恢复本机模式", self._phone_off)

    def _phone_off(self) -> None:
        self.log_async("正在恢复本机模式（UAC 提权窗口请点“是”）…")
        r = run_ps(SWITCH_PS1, *_ps_args(), "-Restore", "-NoPause", timeout=90)
        self.log_async((r.stdout or "").strip()[-300:] or "已提交。")

    # ---------------- 地址选择（C4：下拉 + 可改端口，不再手输 IP） ----------------
    def _current_token(self) -> "str | None":
        return getattr(self, "_token", None) or token_url()

    def _address_options(self, kinds=None) -> "tuple[list, list[str]]":
        """(可选地址行, 未知项说明)。用最近一次状态，没刷新过就只给本机。"""
        state = self._last_status
        if state is None:
            rows = [(addr.display(PORT), addr)
                    for addr in addresses.build(None, None, None, port=PORT)]
        else:
            rows = addresses.menu(state.ts_ip, state.lan_ips, state.lan_sources,
                                  port=PORT, ts_error=state.ts_error,
                                  lan_error=state.lan_error)
        known = [(text, addr) for text, addr in rows if addr is not None]
        if kinds:
            known = [(text, addr) for text, addr in known if addr.kind in kinds]
        unknown = [text for text, addr in rows if addr is None]
        return known, unknown

    def _ask_address(self, title: str, kinds=None) -> "tuple | None":
        """选地址 + 改端口。返回 (Address, port)；用户取消或没有可选地址返回 None。"""
        known, unknown = self._address_options(kinds)
        if not known:
            detail = "；".join(unknown) or "探测结果为空"
            messagebox.showinfo("没有可用地址", f"未检测到可用地址：\n{detail}")
            return None
        picked: dict = {}
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("560x310")
        win.resizable(False, False)
        win.configure(fg_color=BG)
        win.transient(self)
        ctk.CTkLabel(win, text=title, font=_font(14, True), text_color=TEXT,
                     anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(win, text="访问地址", font=_font(11), text_color=DIM,
                     anchor="w").pack(fill="x", padx=18)
        displays = [text for text, _addr in known]
        menu = ctk.CTkOptionMenu(win, values=displays, width=520, height=34,
                                 fg_color=CARD2, button_color=SLATE,
                                 button_hover_color=SLATE_DARK, text_color=TEXT,
                                 font=_font(11), dropdown_font=_font(11),
                                 dynamic_resizing=False)
        menu.set(displays[0])
        menu.pack(padx=18, pady=(2, 10))
        port_row = ctk.CTkFrame(win, fg_color="transparent")
        port_row.pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(port_row, text="端口", font=_font(11), text_color=DIM,
                     width=60, anchor="w").pack(side="left")
        port_entry = ctk.CTkEntry(port_row, width=120, height=32, fg_color=CARD2,
                                  border_color=BORDER, text_color=TEXT,
                                  font=_font(11))
        port_entry.insert(0, str(PORT))
        port_entry.pack(side="left", padx=(0, 10))
        hint = ctk.CTkLabel(port_row, text="1-65535，默认 3080", font=_font(10),
                            text_color=FAINT, anchor="w")
        hint.pack(side="left")
        if unknown:
            # 探测失败必须显式写原因，不许静默给个空列表
            ctk.CTkLabel(win, text="；".join(unknown), font=_font(10),
                         text_color=FAINT, anchor="w", justify="left",
                         wraplength=500).pack(fill="x", padx=18)
        err = ctk.CTkLabel(win, text="", font=_font(10), text_color=RED, anchor="w")
        err.pack(fill="x", padx=18, pady=(4, 0))

        def confirm() -> None:
            try:
                port = addresses.validate_port(port_entry.get())
            except ValueError as exc:
                err.configure(text=str(exc))     # 就地提示，不弹第二个窗口
                return
            index = displays.index(menu.get()) if menu.get() in displays else 0
            picked["value"] = (known[index][1], port)
            win.destroy()

        buttons = ctk.CTkFrame(win, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkButton(buttons, text="取消", width=96, height=32, corner_radius=8,
                      fg_color=CARD2, hover_color=SLATE_DARK, text_color=TEXT,
                      font=_font(11), command=win.destroy,
                      cursor="hand2").pack(side="right")
        ctk.CTkButton(buttons, text="确定", width=96, height=32, corner_radius=8,
                      fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color="#FFFFFF",
                      font=_font(11, True), command=confirm,
                      cursor="hand2").pack(side="right", padx=(0, 10))
        win.bind("<Return>", lambda _e: confirm())
        win.bind("<Escape>", lambda _e: win.destroy())
        try:
            win.wait_visibility()
            win.grab_set()
        except Exception:  # noqa: BLE001 - 无窗口管理器/已销毁
            pass
        self.wait_window(win)
        return picked.get("value")

    def on_copy(self) -> None:
        """复制访问地址：下拉选地址、端口可改，日志里 token 打码。"""
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        chosen = self._ask_address("复制访问地址")
        if chosen is None:
            return
        addr, port = chosen
        url = f"{addr.url(port)}?token={token_suffix(token)}"
        self.clipboard_clear()
        self.clipboard_append(url)               # 剪贴板放完整地址：这是功能
        self.logline(f"已复制（{addr.label}）：" + textutil.redact(url))

    # ---------------- 诊断包（C3：整包脱敏） ----------------
    def on_export_diag(self) -> None:
        """导出脱敏诊断包：内容在写进 zip 之前就全部打码（见 diagnostics.build）。"""
        default = f"dsh-console-diag-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        try:
            path = filedialog.asksaveasfilename(
                title="保存诊断包", defaultextension=".zip", initialfile=default,
                filetypes=[("ZIP 压缩包", "*.zip")])
        except Exception as exc:      # noqa: BLE001 - 没有可用的文件对话框
            self.logline(f"选择保存位置失败：{exc}")
            return
        if not path:
            return
        state, raw = self._last_status, self._last_raw

        def work() -> str:
            return str(diagnostics.export(path, cfg=CFG, status=state, raw=raw))

        self._submit("导出诊断包", work, on_done=self._on_diag_done)

    def _on_diag_done(self, task) -> None:
        if task.state is not tasks.State.DONE:
            reason = str(task.error or "未知原因")
            self.logline(f"诊断包导出失败：{reason}")
            messagebox.showerror("导出失败", f"没能生成诊断包：\n{reason}")
            return
        self.logline(f"诊断包已保存：{task.result}（token / 密钥已打码）")
        messagebox.showinfo("诊断包已生成",
                            f"{task.result}\n\n包里不含明文 token、cookie 或 API key。")

    def on_copy_local(self) -> None:
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        self.clipboard_clear()
        self.clipboard_append(token)             # 剪贴板放完整地址
        self.logline("本机地址已复制：" + textutil.redact(token))

    def on_qr_ts(self) -> None:
        self._qr_for({"tailscale"}, "Tailscale")

    def on_qr_lan(self) -> None:
        self._qr_for({"lan"}, "局域网")

    def _qr_for(self, kinds, label: str) -> None:
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        chosen = self._ask_address(f"{label}二维码", kinds)
        if chosen is None:
            return
        addr, port = chosen
        self._qr(f"{addr.url(port)}?token={token_suffix(token)}", label)

    def _qr(self, url: str, label: str) -> None:
        try:
            img = make_qr(url)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(img.width, img.height))
            self._qr_photo = ctk_img  # 保持引用防 GC
            self.qr_label.configure(image=ctk_img, text="", width=252, height=252,
                                    fg_color=WHITE_PANEL)
            self.logline(f"{label}二维码已显示在窗口中（仅在内存，刷新/关闭即清除）。")
        except Exception as exc:  # noqa: BLE001
            self.logline(f"二维码生成失败：{exc}")

    def clear_qr(self) -> None:
        """清除窗口内二维码（内存引用一并释放，不产生任何文件）。"""
        self._qr_photo = None
        try:
            self.qr_label.configure(image=None,
                                    text="点「二维码」按钮生成，直接显示在这里；\n刷新状态或关闭窗口后自动清除",
                                    width=252, height=252, fg_color=WHITE_PANEL)
        except Exception:  # noqa: BLE001
            pass


def _quiet_status() -> "status.Status":
    """自检用的状态替身：不探测本机、不受真实 DSH 影响，CI 里也不会拖慢。"""
    return status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[])


def _degraded_status(pid: int = 4321) -> "status.Status":
    """自检用：假装端口被另一处安装占着，用来验证采纳按钮的露出与收起。"""
    return status.Status(
        phase=status.Phase.DEGRADED, pids=[], port_open=True, phone_open=False,
        ts_ip=None, lan_ips=None, notes=[],
        others=[(pid, "C:\\自检\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js")])


def selftest() -> int:
    app = ConsoleApp()
    app._status_provider = _quiet_status      # 自检不依赖本机真实端口与进程
    app._snapshot.invalidate()
    # 先让启动时的自动刷新（150ms 后）跑完，再验证二维码显示/清除
    time.sleep(0.6)
    app.update()
    app._qr("http://100.124.206.105:3080/?token=selftest", "自检")
    app.update()
    ok_qr = app._qr_photo is not None
    app.clear_qr()
    app.update()
    ok_clear = app._qr_photo is None
    # 采纳按钮：异常（端口被占用）且有候选时露出，状态恢复正常后收起
    app._apply_status(_degraded_status())
    app.update()
    ok_adopt_shown = bool(app._candidates) and app._adopt_shown
    app._apply_status(_quiet_status())
    app.update()
    ok_adopt_hidden = not app._candidates and not app._adopt_shown
    # 日志滚动上限：塞 2100 行后行数必须回到上限以内（C2）
    app._append_log([f"自检第 {i} 行" for i in range(MAX_LOG_LINES + 100)])
    app.update()
    try:
        log_lines = int(str(app.log.index("end-1c")).split(".")[0])
    except Exception:      # noqa: BLE001 - 取不到就直接判失败
        log_lines = -1
    ok_trim = 0 < log_lines <= MAX_LOG_LINES
    # 地址下拉：本机那一项永远在（C4 不该给出空列表）
    try:
        ok_addr = bool(app._address_options()[0])
    except Exception:      # noqa: BLE001
        ok_addr = False
    app.after(200, app.destroy)
    app.mainloop()
    ok = ok_qr and ok_clear and ok_adopt_shown and ok_adopt_hidden and ok_trim and ok_addr
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-gui-selftest.txt"
    marker.write_text(
        f"OK {time.strftime('%Y-%m-%d %H:%M:%S')} qr={ok_qr} clear={ok_clear} "
        f"adopt_shown={ok_adopt_shown} adopt_hidden={ok_adopt_hidden} "
        f"log_lines={log_lines} trim={ok_trim} addresses={ok_addr}\n", encoding="utf-8")
    if sys.stdout:
        print(f"SELFTEST {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def stop_selftest() -> int:
    """模拟完整点击路径：伪造 node 进程 → 跳过确认框 → on_stop → 验证被杀。

    替身走实例上的 _pids_provider / _status_provider（探测层本来就可注入），
    不再改写模块全局，也绝不碰真实的 DSH 进程。
    """
    node = shutil.which("node.exe") or r"D:\Program Files\nodejs\node.exe"
    fake = subprocess.Popen(
        [node, "-e", "setTimeout(()=>{},60000)", "bin.js", "web"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW)
    lines: list[str] = [f"fake_pid={fake.pid}"]
    alive, stopped, busy_left = True, False, True
    try:
        time.sleep(1.2)
        lines.append(f"detected={dsh_pids()}")     # 真探测层：伪造进程不该被认成本机 DSH
        app = ConsoleApp()
        app.withdraw()
        app._status_provider = _quiet_status
        app._snapshot.invalidate()
        # 只杀伪造进程：探测口返回它，进程一死就返回空
        app._pids_provider = lambda: ([] if fake.poll() is not None else [fake.pid], None)
        app._port_open = lambda: False            # 端口探测也注入，自检不受本机真实 3080 影响
        app._ask_main = lambda fn, *args: True     # 确认框一律「是」，自检不阻塞
        captured = {"log": "", "queue_idle": False}
        deadline = time.monotonic() + 12

        def finish() -> None:
            captured["log"] = app.log.get("1.0", "end")
            captured["queue_idle"] = app._queue.idle()   # 队列必须回到空闲（C5）
            app.destroy()

        def poll() -> None:
            # 真实事件循环在跑，工作线程投递回来的日志与状态都在这里被消费
            if "已停止" in app.log.get("1.0", "end") or time.monotonic() > deadline:
                app.after(300, finish)
            else:
                app.after(200, poll)

        app.after(0, app.on_stop)
        app.after(400, poll)
        app.mainloop()          # 必须进 mainloop：否则 after() 从工作线程投递会被 Tk 拒绝
        alive = fake.poll() is None
        stopped = "已停止" in captured["log"]
        busy_left = not captured["queue_idle"]
        lines.append(f"fake_alive_after_click={alive}")
        lines.append(f"log_has_stopped={stopped}")
        lines.append(f"queue_idle={not busy_left} pending={app._queue.pending()}")
        lines.append(f"log_snippet={captured['log'][:400]!r}")
        if alive:
            fake.kill()
    finally:
        if fake.poll() is None:
            fake.kill()
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-stop-selftest.txt"
    marker.write_text("OK\n" + "\n".join(lines) + "\n", encoding="utf-8")
    ok = (not alive) and stopped and not busy_left
    if sys.stdout:
        print(f"STOP SELFTEST {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def ensure_ready() -> bool:
    """探测不到 harness/node 时让用户选目录，写进 config.json 再继续。"""
    global CFG, HARNESS, TOKEN_LOG, PORT
    if CFG.ready:
        return True
    root = ctk.CTk()
    root.withdraw()
    chosen = ""
    try:
        messagebox.showinfo(
            "首次运行：DSH 装在哪？",
            "没有自动找到 DeepSeek Harness（它应含有 node_modules\\@deepseek-ai\\dsh 目录）。\n"
            "下一步请选择它的安装目录；选好后会记到 config.json，下次不再询问。",
            parent=root)
        chosen = filedialog.askdirectory(title="选择 DeepSeek Harness 安装目录", parent=root)
    finally:
        root.destroy()
    if chosen:
        CFG = config.resolve(explicit_harness=chosen)
        if CFG.ready:
            config.save(CFG)
            HARNESS, TOKEN_LOG, PORT = CFG.harness, CFG.token_log, CFG.port
            return True
    root = ctk.CTk()
    root.withdraw()
    try:
        messagebox.showerror(
            "无法启动",
            "仍然找不到可用的 DeepSeek Harness，或系统里没有 Node.js。\n"
            "请先装好 DSH 与 Node.js 再重新打开本程序；\n"
            "也可以直接编辑 config.json 指定 harness / node 路径。\n\n点「确定」退出。",
            parent=root)
    finally:
        root.destroy()
    return False


def _cli_error(message: str) -> None:
    """参数不合法：先写 stderr，双击启动（无控制台）时再弹窗，避免静默退出。"""
    print(message, file=sys.stderr)
    try:
        root = ctk.CTk()
        root.withdraw()
        try:
            messagebox.showerror("参数错误", message, parent=root)
        finally:
            root.destroy()
    except Exception:
        pass


def _utf8_stdio() -> None:
    """把 stdout/stderr 掰成 UTF-8：GBK 代码页下中文会显示成乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 被重定向、已关闭或不是 TextIOWrapper：保持原样


def main() -> int:
    _utf8_stdio()
    if "--selftest" in sys.argv:
        return selftest()
    if "--stop-selftest" in sys.argv:
        return stop_selftest()
    global CFG, HARNESS, TOKEN_LOG, PORT, _APP
    try:
        want_harness, want_port = config.parse_cli(sys.argv[1:])
    except config.CliError as exc:
        _cli_error(str(exc))
        return 2
    # 单实例：双击第二次时把已有窗口拉到前台，绝不弹第二个主窗口。
    # 放在探测与首次运行询问之前 —— 第二个实例不该再问一遍「DSH 装在哪」。
    guard = single.acquire()
    if guard.blocked:
        # 已有实例可能收在托盘里：先发「叫醒」事件，它自己会显示并聚焦
        woken = single.signal_activate()
        if woken or single.focus_window(APP_TITLE):
            # 已经把它拉到眼前了，再弹一个「你在重复打开」的对话框只是多要一次点击。
            print("已经有一个 DSH 控制台在运行，已把它的窗口显示出来；这个窗口不再打开。")
        else:
            _info_blocking(APP_TITLE,
                           "已经有一个 DSH 控制台在运行（没能把它切到前台，请从任务栏打开）。"
                           "\n这个窗口不再打开。")
        return 0
    if want_harness is not None or want_port is not None:
        CFG = config.resolve(explicit_harness=want_harness, explicit_port=want_port)
        HARNESS, TOKEN_LOG, PORT = CFG.harness, CFG.token_log, CFG.port
    if not ensure_ready():
        return 1
    app = ConsoleApp()
    _APP = app
    errors.install(_report)      # sys / threading 两处钩子；Tk 回调那处由 app 自己挂
    if guard.acquired is None:
        app.logline(f"单实例检查已跳过：{guard.reason}")
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
