"""DSH 控制台 - DeepSeek Harness 桌面图形界面 (customtkinter · 蓝鲸主题)

双击 exe / 运行本脚本即可打开窗口。功能与旧版一致：
  启动 Harness、开启手机访问（端口转发+信任来源）、恢复本机、复制手机地址、
  生成二维码（窗口内显示，刷新/关闭即清除，不落盘）、停止 Harness、实时查看状态。

UI 以 DeepSeek 品牌蓝 #4D6BFE 为主基调，深色科技风，头部展示 DeepSeek 鲸鱼娘图标。
"""
from __future__ import annotations

import dataclasses
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
                        psrun, resources, single, snapshot, status, tasks, textutil, tray,
                        ui_theme, widgets)
from dshconsole.ui_theme import (AMBER, AMBER_DARK, BG, BORDER, CARD, CARD2, CYAN, DIM, PHASE_WORD,
                                 DRAWER_WIDTH, FAINT, FONT, GREEN, GREEN_DARK, GREY,
                                 GREY_DARK, LOG_LINE_PX, LOG_ROWS_COLLAPSED, MONO,
                                 PHASE_STYLE, PRIMARY, PRIMARY_HOVER, RED, RED_DARK,
                                 RING_SIZE, SLATE, SLATE_DARK, TEAL, TEAL_DARK, TEXT,
                                 VIOLET, VIOLET_DARK, WHITE_PANEL)

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
# 配色 / 尺寸 / 五态样式集中在 dshconsole/ui_theme.py，上面 import 已带进本模块作用域。
# 未运行是中性灰而不是红：正常停机不是报警，红环会把「待机」渲染成「出事」。


def primary_action(phase) -> tuple[str, str, str, str]:
    """五态各自的主操作 -> (按钮文案, 回调名, 颜色, 悬停色)。

    一屏只留这一颗主按钮：十颗按钮并排时，用户得自己判断哪颗现在能用。
    回调名与原有的 on_start / on_stop 同名，所以点下去的业务与改动前完全一致。
    """
    if phase is status.Phase.STOPPED:
        return "启动 DSH", "start", PRIMARY, PRIMARY_HOVER
    if phase is status.Phase.DEGRADED:
        return "修复/重启", "restart", AMBER, AMBER_DARK
    if phase is status.Phase.UNKNOWN:
        return "重新探测", "refresh", SLATE, SLATE_DARK
    return "停止 DSH", "stop", RED, RED_DARK      # 启动中 / 运行中


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
        self.geometry("660x800")
        self.minsize(620, 720)
        self.configure(fg_color=BG)
        self._qr_photo = None
        self._qr_overlay: widgets.QrOverlay | None = None
        self._log_overlay: widgets.LogOverlay | None = None
        self._drawer: widgets.DrawerMenu | None = None
        self._log_rows = LOG_ROWS_COLLAPSED      # 日志区露几行（要更多走浮层）
        self._log_follow = True                  # 日志跟随开关，从「⋯」里切
        self._primary_name = "start"             # 主按钮当前绑的回调名
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
        self._log_follow = True
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
        self._sync_close_hint()
        self.logline(f"{why}：本次按普通窗口运行，关闭按钮＝退出。")
        return False

    def _on_tray_lost(self, reason: str) -> None:
        """托盘线程没了：立刻退回普通窗口，否则用户会以为程序还在。"""
        self.logline(f"{reason}：退回普通窗口，关闭按钮＝退出。")
        self._tray = None
        self._close_to_tray = False
        self._sync_close_hint()

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

    def _sync_close_hint(self) -> None:
        """页脚只留一行当前行为（开关本体搬进「⋯」抽屉，底栏不再挤两个控件）。"""
        text = "关闭按钮：收进托盘" if self._close_to_tray else "关闭按钮：退出程序"
        try:
            self.lbl_close_hint.configure(text=text)
        except Exception:      # noqa: BLE001 - 控件替身/未建好
            pass

    def on_toggle_close_mode(self) -> None:
        """一键在「关闭收进托盘」与「关闭即退出」之间切换，并写回 config.json。"""
        want = not self._close_to_tray
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
        self._sync_close_hint()

    def _close_overlays(self) -> None:
        """收起抽屉与浮层，并释放二维码的内存引用（不产生任何文件）。"""
        for attr in ("_qr_overlay", "_log_overlay", "_drawer"):
            layer = getattr(self, attr, None)
            if layer is None:
                continue
            try:
                layer.close()
            except Exception:      # noqa: BLE001 - 已经在销毁路径上
                pass
            setattr(self, attr, None)
        self.clear_qr()

    def _on_close(self) -> None:
        """关闭按钮：收进托盘（可一键改回退出），绝不悄悄退掉。"""
        if self._close_to_tray and self._tray is not None:
            self._close_overlays()
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
        self._close_overlays()
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
        """大环 + 抽屉：一颗状态环、一颗主按钮、其余操作收进「⋯」，日志只露末尾 15 行。"""
        # --- 头部：鲸鱼娘 + 标题 +「⋯」 ---
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
        # 抽屉入口：应用内菜单。托盘右键菜单是 Host 语义，两者互不复用。
        self.btn_menu = ctk.CTkButton(head, text="⋯", width=40, height=34, corner_radius=10,
                                      fg_color=CARD2, hover_color="#1D2D55", text_color=TEXT,
                                      font=_font(18, True), cursor="hand2",
                                      command=self._open_drawer)
        self.btn_menu.pack(side="right", padx=(8, 16))

        # --- 状态卡片：状态环 + 右侧文字 ---
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=14, pady=6)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 6))
        self.ring = widgets.StatusRing(row, bg=CARD)
        self.ring.pack(side="left")
        side = ctk.CTkFrame(row, fg_color="transparent")
        side.pack(side="left", fill="both", expand=True, padx=(16, 0))
        wrap = 330
        self.lbl_service = ctk.CTkLabel(side, text="服务状态：--", font=_font(12, True),
                                        text_color=FAINT, anchor="w", justify="left",
                                        wraplength=wrap)
        self.lbl_service.pack(fill="x")
        self.lbl_phone = ctk.CTkLabel(side, text="手机访问：--", font=_font(12, True),
                                      text_color=FAINT, anchor="w", justify="left",
                                      wraplength=wrap)
        self.lbl_phone.pack(fill="x", pady=(6, 0))
        self.lbl_net = ctk.CTkLabel(side, text="网络：--", font=_font(11),
                                    text_color=DIM, anchor="w", justify="left",
                                    wraplength=wrap)
        self.lbl_net.pack(fill="x", pady=(6, 0))
        # 采纳按钮：只有「异常（端口被占用）且查到占用者」时才 pack 出来（见 _sync_adopt_button）
        self.btn_adopt = ctk.CTkButton(
            card, text="改为控制运行中的实例", command=self.on_adopt,
            fg_color=VIOLET, hover_color=VIOLET_DARK, text_color="#FFFFFF",
            font=_font(12, True), height=36, corner_radius=10, cursor="hand2")
        # 队列说明：排队/执行中的状态写在这里，按钮本身从不禁用（C5）
        self.lbl_queue = ctk.CTkLabel(card, text="", font=_font(11), text_color=DIM,
                                      anchor="w", justify="left")
        self.lbl_queue.pack(fill="x", padx=14, pady=(0, 10))

        # --- 主按钮：只有一颗，文案与颜色随状态换 ---
        self.btn_primary = ctk.CTkButton(self, text="启动 DSH", command=self._run_primary,
                                         height=52, corner_radius=12, font=_font(15, True),
                                         fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
                                         text_color="#FFFFFF", cursor="hand2")
        self.btn_primary.pack(fill="x", padx=14, pady=(8, 4))

        # --- 日志卡片：15 行是下限不是上限，窗口更高就多露几行（行数上限仍由 2000 行裁剪切控制） ---
        log_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                                border_width=1, border_color=BORDER)
        log_card.pack(fill="both", expand=True, padx=14, pady=(6, 8))
        log_head = ctk.CTkFrame(log_card, fg_color="transparent")
        log_head.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(log_head, text="运行日志", font=_font(12, True),
                     text_color=TEXT, anchor="w").pack(side="left")
        ctk.CTkButton(log_head, text="展开全屏", width=84, height=26, corner_radius=8,
                      fg_color=CARD2, hover_color="#1D2D55", text_color=TEXT,
                      font=_font(11), cursor="hand2",
                      command=self.on_expand_log).pack(side="right")
        self.lbl_log_hint = ctk.CTkLabel(log_head, text=f"仅显示末尾 {self._log_rows} 行",
                                         font=_font(11), text_color=FAINT, anchor="e")
        self.lbl_log_hint.pack(side="right", padx=(0, 10))
        self.log = ctk.CTkTextbox(log_card, height=self._log_rows * LOG_LINE_PX,  # 15 行＝下限
                                  fg_color="#0A1226", text_color="#C7D3EA", font=_mono(12),
                                  corner_radius=10, border_width=1, border_color=BORDER,
                                  wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # --- 底栏 ---
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(foot, text=f"本机：http://127.0.0.1:{PORT}", font=_font(11),
                     text_color=DIM, anchor="w").pack(side="left")
        # 关闭行为只显示一行字，切换开关在「⋯」里（把用户锁死在托盘里不可接受）
        self.lbl_close_hint = ctk.CTkLabel(foot, text="", font=_font(11),
                                           text_color=DIM, anchor="e")
        self.lbl_close_hint.pack(side="right", padx=(8, 0))
        ctk.CTkButton(foot, text="复制本机地址", command=self.on_copy_local, width=110,
                      height=28, corner_radius=8, fg_color=CARD2, hover_color="#1D2D55",
                      text_color=TEXT, font=_font(11), cursor="hand2").pack(side="right")
        self._sync_close_hint()

    # ---------------- helpers ----------------
    def logline(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self._scroll_log_to_end()
        self._mirror_log()
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
            self._mirror_log()
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

    def _mirror_log(self) -> None:
        """把主日志框的内容搬到全屏窗：内容早就在主框里打码并截断过，这里只搬运。"""
        overlay = self._log_overlay
        if overlay is None:
            return
        try:
            overlay.fill(self.log.get("1.0", "end-1c"))
            overlay.follow()
        except Exception:      # noqa: BLE001 - 浮层已关
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
        # 二维码不再随刷新清除：它住在浮层里，关掉浮层才清（否则刷一次闪一下）。
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
            style = PHASE_STYLE[self._last_status.phase]
            self.lbl_service.configure(
                text=f"{style.dot}  服务状态：{self._last_status.phase.label}　⟳ 刷新中…",
                text_color=style.color)
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
        style = PHASE_STYLE[state.phase]
        self.lbl_service.configure(
            text=f"{style.dot}  服务状态：{state.phase.label}", text_color=style.color)
        self._sync_primary(state.phase)          # 主按钮的文案与颜色跟着状态走
        ring = getattr(self, "ring", None)
        if ring is not None:
            ring.set_status(state.phase, state.pids)   # 环：颜色 + 状态词 + PID
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

    # ---------------- 大环 / 抽屉 / 浮层 ----------------
    def _run_primary(self) -> None:
        """主按钮：永远调当前状态对应的那颗老回调（不新写业务）。"""
        handler = getattr(self, "on_" + self._primary_name, None)
        if handler is not None:
            handler()

    def _sync_primary(self, phase) -> None:
        """按状态换主按钮的文案与颜色；文案是主体，颜色只是辅助。"""
        label, name, color, hover = primary_action(phase)
        self._primary_name = name
        button = getattr(self, "btn_primary", None)
        if button is None:          # 控件替身 / 还没建好
            return
        try:
            button.configure(text=label, fg_color=color, hover_color=hover)
        except Exception:      # noqa: BLE001
            pass

    def _drawer_items(self) -> list:
        """抽屉条目：其余操作都收在这里。托盘右键菜单是 Host 语义，两者不复用。"""
        follow = "暂停日志跟随" if self._log_follow else "继续日志跟随"
        mode = "关闭窗口时：退出程序" if self._close_to_tray else "关闭窗口时：收进托盘"
        try:
            pending = len(self._queue.pending())
        except Exception:      # noqa: BLE001
            pending = 0
        items = [
            ("🔄  刷新状态", self.on_refresh),
            ("♻  重启 DSH", self.on_restart),
            ("🔢  切换 Web 端口…", self.on_change_port),
            ("📱  手机访问（二维码）", self.on_phone_access),
            ("📋  复制手机访问地址", self.on_copy),
            ("🖥  复制本机地址", self.on_copy_local),
            ("📶  开启手机访问（需 UAC）", self.on_phone_on),
            ("🏠  恢复本机模式（需 UAC）", self.on_phone_off),
            ("🩺  导出诊断包", self.on_export_diag),
            (f"📜  {follow}", self.on_toggle_log_follow),
            (f"📌  {mode}", self.on_toggle_close_mode),
        ]
        if pending:
            items.append((f"✖  取消排队（{pending} 个）", self.on_cancel_queue))
        items.append(("🚪  退出", self._quit))
        return items

    def _open_drawer(self) -> None:
        """「⋯」抽屉：每次打开都重建，动态文案（跟随 / 关闭行为 / 队列）才是当下的。"""
        if self._drawer is not None:
            self._drawer.close()
            self._drawer = None
        try:
            x = self.btn_menu.winfo_rootx() + self.btn_menu.winfo_width() - DRAWER_WIDTH
            y = self.btn_menu.winfo_rooty() + self.btn_menu.winfo_height() + 6
        except Exception:      # noqa: BLE001 - 控件已销毁
            x = y = 120
        self._drawer = widgets.DrawerMenu(self, self._drawer_items(), x=x, y=y,
                                          on_close=self._on_drawer_closed)
        self._drawer.show()
        self._place_drawer()

    def _place_drawer(self) -> None:
        """把抽屉钉在「⋯」右下角：宽度要等窗口画出来才知道（高 DPI 下不等于设计值）。"""
        menu = self._drawer
        if menu is None:
            return
        try:
            self.update_idletasks()
            right = self.btn_menu.winfo_rootx() + self.btn_menu.winfo_width()
            x = max(self.winfo_rootx() + 6, right - menu.winfo_width())
            y = self.btn_menu.winfo_rooty() + self.btn_menu.winfo_height() + 6
            menu.geometry("+%d+%d" % (int(x), int(y)))
        except Exception:      # noqa: BLE001 - 控件已销毁
            pass

    def _on_drawer_closed(self) -> None:
        self._drawer = None

    def on_toggle_log_follow(self) -> None:
        """日志跟随开关：关掉只是不再读新行，框里已有的内容照旧留着。"""
        if not self._log_follow:
            self._start_log_tail()
            return
        tail, self._tail = self._tail, None
        self._log_follow = False
        if tail is not None:
            tail.stop()
        self.logline("已暂停日志跟随（「⋯」里可以再打开）。")

    def on_expand_log(self) -> None:
        """全屏看日志：与主框同一份内容，关掉就回到末尾 15 行。"""
        overlay = self._log_overlay
        if overlay is not None:
            overlay.show()
            self._mirror_log()
            return
        self._log_overlay = widgets.LogOverlay(self, limit=MAX_LOG_LINES,
                                               on_close=self._on_log_overlay_closed)
        self._log_overlay.show()
        self._mirror_log()

    def _on_log_overlay_closed(self) -> None:
        self._log_overlay = None

    def on_change_port(self) -> None:
        """切换 Web 端口：写回 config.json 并刷新（新的端口下次启动生效）。"""
        global CFG, PORT
        dialog = ctk.CTkInputDialog(title="切换 Web 端口",
                                    text=f"当前端口 {PORT}，新端口（1-65535）：")
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            port = addresses.validate_port(raw)
        except ValueError as exc:
            messagebox.showinfo("端口不合法", str(exc))
            return
        try:
            new_cfg = dataclasses.replace(CFG, port=port)
            config.save(new_cfg)
        except Exception as exc:      # noqa: BLE001 - 写不进去就别假装成功
            messagebox.showinfo("没能保存", f"{exc}")
            return
        CFG = new_cfg
        PORT = port
        self._snapshot.invalidate()
        self.logline(f"Web 端口已改为 {port}（下次启动 DSH 生效）。")
        self.refresh(force=True)

    def on_restart(self) -> None:
        """重启 = 停止 + 启动：两条既有路径按顺序走，不新增业务分支。"""
        self._submit("重启 DSH", self._restart)

    def _restart(self) -> None:
        pids, err = self._pids_provider()
        if pids is None:
            self.log_async(f"未知：node 进程查不到（{err}），重启前不结束任何进程。")
            return
        if not pids:
            self.log_async("没有正在运行的 DSH，直接启动。")
        else:
            listing = "\n".join(f"    PID {pid}" for pid in pids)
            if not self._ask_main(messagebox.askyesno, "重启确认",
                                  f"将先结束以下 node 进程再重新启动：\n{listing}\n\n"
                                  "当前网页会断开（会话已存档可重开）。继续吗？"):
                self.log_async("已取消重启，未结束任何进程。")
                return
            self._stop(pids)
        self._start()

    def on_phone_access(self) -> None:
        """手机访问浮层：地址下拉 + 二维码 + 复制；主界面不再常驻二维码。"""
        if self._qr_overlay is not None:
            self._qr_overlay.show()
            return
        if not self._current_token():
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        overlay = widgets.QrOverlay(self, on_close=self._on_qr_overlay_closed)
        self._qr_overlay = overlay
        self._fill_qr_addresses()
        try:
            overlay.picker.configure(command=self._on_qr_pick)
            overlay.bind_actions(self.on_copy)
        except Exception:      # noqa: BLE001 - 浮层刚建就被关
            pass
        overlay.show()

    def _fill_qr_addresses(self) -> None:
        """把已知地址灌进下拉，并先画第一张（一个都没有时退回本机）。"""
        overlay = self._qr_overlay
        if overlay is None:
            return
        try:
            known, _unknown = self._address_options()
            options = [text for text, _addr in known] or [f"本机  127.0.0.1:{PORT}"]
            overlay.picker.configure(values=options)
            overlay.picker.set(options[0])
        except Exception:      # noqa: BLE001
            options = [f"本机  127.0.0.1:{PORT}"]
        self._on_qr_pick(options[0])

    def _on_qr_pick(self, choice: str) -> None:
        """选中哪个地址就立刻重画二维码（token 打码后才写进浮层的小字）。"""
        token = self._current_token()
        if not token:
            return
        try:
            known, _unknown = self._address_options()
        except Exception:      # noqa: BLE001
            known = []
        addr = next((item for text, item in known if text == choice), None)
        url = addr.url(PORT) if addr is not None else f"http://127.0.0.1:{PORT}/"
        self._qr(f"{url}?token={token_suffix(token)}", "手机访问")

    def _on_qr_overlay_closed(self) -> None:
        self._qr_overlay = None
        self.clear_qr()

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

    def _qr(self, url: str, label: str) -> None:
        """生成二维码放进浮层：只在内存，关掉浮层即清除，不落盘。"""
        try:
            img = make_qr(url)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(img.width, img.height))
            self._qr_photo = ctk_img      # 保持引用防 GC
            overlay = self._qr_overlay
            if overlay is not None:
                overlay.image_label.configure(image=ctk_img, text="")
                overlay.hint.configure(text=f"{label} · {textutil.redact(url)}")
            self.logline(f"{label}二维码已生成（仅在内存，关闭浮层即清除）。")
        except Exception as exc:  # noqa: BLE001
            self.logline(f"二维码生成失败：{exc}")

    def clear_qr(self) -> None:
        """清除二维码（内存引用一并释放，不产生任何文件）。"""
        self._qr_photo = None
        overlay = self._qr_overlay
        if overlay is None:
            return
        try:
            overlay.image_label.configure(image=None, text="")
            overlay.hint.configure(text="")
        except Exception:      # noqa: BLE001 - 浮层已销毁
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


def _running_status(pid: int = 4321) -> "status.Status":
    """自检用：五态里挑「运行中」验收状态环与主按钮（不碰真实进程）。"""
    return status.Status(phase=status.Phase.RUNNING, pids=[pid], port_open=True,
                         phone_open=True, ts_ip="100.124.206.105",
                         lan_ips=["192.168.1.20"], notes=[])


def selftest() -> int:
    app = ConsoleApp()
    app._status_provider = _quiet_status      # 自检不依赖本机真实端口与进程
    app._snapshot.invalidate()
    # 先让启动时的自动刷新（150ms 后）跑完，再逐块验证
    time.sleep(0.6)
    app.update()

    # 状态环 + 单主按钮：环里必须写着状态词（不能只靠颜色区分），按钮文案跟着变
    app._apply_status(_running_status())
    app.update()
    try:
        ring_text = app.ring.phase_text
    except Exception:      # noqa: BLE001 - 拿不到就直接判失败
        ring_text = ""
    ok_ring = ring_text == PHASE_WORD[status.Phase.RUNNING]
    try:
        ok_primary = app.btn_primary.cget("text") == "停止 DSH"
    except Exception:      # noqa: BLE001
        ok_primary = False

    # 采纳按钮：异常（端口被占用）且有候选时露出，状态恢复正常后收起
    app._apply_status(_degraded_status())
    app.update()
    ok_adopt_shown = bool(app._candidates) and app._adopt_shown
    try:
        ok_primary_deg = app.btn_primary.cget("text") == "修复/重启"
    except Exception:      # noqa: BLE001
        ok_primary_deg = False
    app._apply_status(_quiet_status())
    app.update()
    ok_adopt_hidden = not app._candidates and not app._adopt_shown

    # 二维码改住浮层：主界面不常驻，弹层关掉就清干净
    app._token = "selftest-token"    # 必须在最后一次 _apply_status 之后（否则被真 token 覆盖）
    app.on_phone_access()
    app.update()
    ok_qr = app._qr_photo is not None
    ok_overlay_open = app._qr_overlay is not None
    app._close_overlays()
    app.update()
    ok_overlay_closed = app._qr_overlay is None and app._log_overlay is None
    ok_clear = app._qr_photo is None

    # 「⋯」抽屉：其余操作都在里面
    app._open_drawer()
    app.update()
    try:
        menu_items = len(app._drawer.labels())
    except Exception:      # noqa: BLE001
        menu_items = -1
    app._close_overlays()
    app.update()
    ok_menu = menu_items >= 11

    # 日志滚动上限：塞 2100 行后行数必须回到上限以内（C2）
    app._append_log([f"自检第 {i} 行" for i in range(MAX_LOG_LINES + 100)])
    app.update()
    try:
        log_lines = int(str(app.log.index("end-1c")).split(".")[0])
    except Exception:      # noqa: BLE001 - 取不到就直接判失败
        log_lines = -1
    ok_trim = 0 < log_lines <= MAX_LOG_LINES

    # 日志默认只显示末尾 N 行，展开全屏就是同一份内容
    ok_collapsed = app._log_rows == LOG_ROWS_COLLAPSED
    app.on_expand_log()
    app.update()
    try:
        log_expanded = app._log_overlay is not None and app._log_overlay.line_count > 0
    except Exception:      # noqa: BLE001
        log_expanded = False
    log_collapsed = app._log_rows
    app._close_overlays()
    app.update()

    # 地址下拉：本机那一项永远在（C4 不该给出空列表）
    try:
        ok_addr = bool(app._address_options()[0])
    except Exception:      # noqa: BLE001
        ok_addr = False

    app.after(200, app.destroy)
    app.mainloop()
    ok = all([ok_qr, ok_clear, ok_adopt_shown, ok_adopt_hidden, ok_trim, ok_addr,
              ok_ring, ok_primary, ok_primary_deg, ok_menu, ok_overlay_open,
              ok_overlay_closed, ok_collapsed, log_expanded])
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-gui-selftest.txt"
    marker.write_text(
        f"OK {time.strftime('%Y-%m-%d %H:%M:%S')} qr={ok_qr} clear={ok_clear} "
        f"adopt_shown={ok_adopt_shown} adopt_hidden={ok_adopt_hidden} "
        f"log_lines={log_lines} trim={ok_trim} addresses={ok_addr} "
        f"ring={ring_text or '无'} menu_items={menu_items} "
        f"overlay_open={ok_overlay_open} overlay_closed={ok_overlay_closed} "
        f"log_collapsed={log_collapsed} log_expanded={log_expanded}\n", encoding="utf-8")
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
